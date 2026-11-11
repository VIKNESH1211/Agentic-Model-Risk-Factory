"""Challenger model: gradient boosting on the same raw inputs."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from app.tools.datasets import RAW_FEATURES


def _design(d: pd.DataFrame, cols=None) -> pd.DataFrame:
    X = pd.get_dummies(d[RAW_FEATURES], dummy_na=True).astype(float)
    if cols is not None:
        X = X.reindex(columns=cols, fill_value=0.0)
    return X


def fit_predict(data: pd.DataFrame, seed: int = 42) -> np.ndarray:
    tr = data[data["split"] == "train"]
    Xtr = _design(tr)
    y = (tr["creditability"] == "bad").astype(int)
    clf = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200,
                                         l2_regularization=1.0, random_state=seed)
    clf.fit(Xtr, y)
    return clf.predict_proba(_design(data, Xtr.columns))[:, 1]
