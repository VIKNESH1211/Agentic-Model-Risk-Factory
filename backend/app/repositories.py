"""CRUD for every entity, plus versioning for the records agents draft and humans approve.

Services and agents go through these objects; nothing else builds queries for model knowledge.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Generic, Optional, TypeVar

from sqlmodel import SQLModel, select

from app.core.db import session
from app.domain.tables import (DataAsset, Model, ModelFile, PlanVersion, PolicyCheck, PromptTemplate,
                               SpecVersion)

T = TypeVar("T", bound=SQLModel)


class Repo(Generic[T]):
    def __init__(self, entity: type[T], order_by: str | None = None):
        self.entity = entity
        self.order_by = order_by

    def get(self, key: Any) -> Optional[T]:
        with session() as s:
            return s.get(self.entity, key)

    def list(self, **eq) -> list[T]:
        with session() as s:
            q = select(self.entity)
            for k, v in eq.items():
                q = q.where(getattr(self.entity, k) == v)
            if self.order_by:
                desc = self.order_by.startswith("-")
                col = getattr(self.entity, self.order_by.lstrip("-"))
                q = q.order_by(col.desc() if desc else col)
            return list(s.exec(q).all())

    def first(self, **eq) -> Optional[T]:
        rows = self.list(**eq)
        return rows[0] if rows else None

    def create(self, obj: T) -> T:
        with session() as s:
            s.add(obj)
            s.commit()
            s.refresh(obj)
            return obj

    def update(self, key: Any, **fields) -> T:
        with session() as s:
            obj = s.get(self.entity, key)
            if obj is None:
                raise KeyError(f"{self.entity.__name__} {key} not found")
            for k, v in fields.items():
                setattr(obj, k, v)
            s.add(obj)
            s.commit()
            s.refresh(obj)
            return obj

    def delete(self, key: Any) -> None:
        with session() as s:
            obj = s.get(self.entity, key)
            if obj is not None:
                s.delete(obj)
                s.commit()


class VersionedRepo(Repo[T]):
    """Rows keyed by (model_id[, kind], version) with draft → approved → superseded status."""

    def _scope(self, model_id: str, kind: str | None) -> dict:
        return {"model_id": model_id, **({"kind": kind} if kind else {})}

    def versions(self, model_id: str, kind: str | None = None) -> list[T]:
        return sorted(self.list(**self._scope(model_id, kind)), key=lambda r: r.version, reverse=True)

    def latest(self, model_id: str, kind: str | None = None) -> Optional[T]:
        v = self.versions(model_id, kind)
        return v[0] if v else None

    def approved(self, model_id: str, kind: str | None = None) -> Optional[T]:
        return next((r for r in self.versions(model_id, kind) if r.status == "approved"), None)

    def current(self, model_id: str, kind: str | None = None) -> Optional[T]:
        """What the engine should use: the approved version, else the newest draft."""
        return self.approved(model_id, kind) or self.latest(model_id, kind)

    def add_version(self, model_id: str, body: dict, author: str, note: str = "", kind: str | None = None, **extra) -> T:
        prev = self.latest(model_id, kind)
        with session() as s:
            for r in s.exec(select(self.entity).where(*[getattr(self.entity, k) == v for k, v in self._scope(model_id, kind).items()],
                                                      self.entity.status == "draft")).all():
                r.status = "superseded"
                s.add(r)
            row = self.entity(model_id=model_id, version=(prev.version + 1) if prev else 1, status="draft", author=author,
                              body=body, note=note, **({"kind": kind} if kind else {}), **extra)
            s.add(row)
            s.commit()
            s.refresh(row)
            return row

    def approve(self, row_id: int, by: str) -> T:
        with session() as s:
            row = s.get(self.entity, row_id)
            scope = [getattr(self.entity, k) == v for k, v in self._scope(row.model_id, getattr(row, "kind", None)).items()]
            for r in s.exec(select(self.entity).where(*scope, self.entity.status == "approved")).all():
                r.status = "superseded"
                s.add(r)
            row.status, row.approved_by, row.approved_at = "approved", by, datetime.now(timezone.utc)
            s.add(row)
            s.commit()
            s.refresh(row)
            return row


models = Repo(Model, order_by="id")
model_files = Repo(ModelFile, order_by="id")
assets = Repo(DataAsset, order_by="name")
specs = VersionedRepo(SpecVersion)
plans = VersionedRepo(PlanVersion)
policy_checks = Repo(PolicyCheck, order_by="code")
prompts = Repo(PromptTemplate, order_by="-version")


def current_asset(name: str) -> Optional[DataAsset]:
    return assets.first(name=name, is_current=True)
