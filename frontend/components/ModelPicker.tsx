"use client";
import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import Link from "next/link";
import { get } from "@/lib/api";

/** Tabs to switch the same screen between models: hrefFor(id) builds each link. */
export function ModelPicker({ current, hrefFor, filter }: { current: string; hrefFor: (id: string) => string; filter?: (m: any) => boolean }) {
  const q = useQuery({ queryKey: ["models"], queryFn: () => get<any[]>("/api/models") });
  const ms = (q.data || []).filter((m) => !filter || filter(m));
  if (!ms.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Model">
      {ms.map((m) => (
        <Link key={m.id} href={hrefFor(m.id)} role="tab" aria-selected={m.id === current}
          className={clsx("rounded-lg border px-3 py-1.5 text-sm font-semibold transition", m.id === current ? "border-teal bg-teal/10 text-teal" : "border-line text-muted hover:text-text hover:bg-white/5")}>
          <span className="mono">{m.id}</span>
        </Link>
      ))}
    </div>
  );
}
