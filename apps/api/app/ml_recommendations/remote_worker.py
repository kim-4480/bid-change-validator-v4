"""Standalone opt-in isolated inference worker.

Only a verified, manually approved deep-model registry can advertise an
approved HUMAN_REVIEWED_HOLDOUT. Unregistered local models remain test-only.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .registry import active_model_dir, file_sha256

app = FastAPI(title="BidCheck ML Inference Worker")


class Notice(BaseModel):
    notice_id: str
    title: str
    notice_text: str | None = None


class ScoreRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    notices: list[Notice] = Field(min_length=1, max_length=150)


@lru_cache(maxsize=8)
def _load_scoring(folder, name, sha, device):
    from .trainer import load_deep, deep_scorer
    scorer = deep_scorer(load_deep(Path(folder), name), device=device)
    return scorer, name + "-" + sha[:16]


def model():
    name = os.getenv("BIDCHECK_DL_KIND", "cross_encoder")
    if name not in {"bi_encoder", "cross_encoder"}:
        raise ValueError("Invalid model kind")
    registry = os.getenv("BIDCHECK_DL_REGISTRY_DIR")
    if registry:
        folder = active_model_dir(registry, expected_kind=name)
    else:
        # Legacy local experiments are explicitly not advertised as Champion.
        folder = Path(os.environ["BIDCHECK_DL_MODEL_DIR"])
    path = folder / (name + ".pt")
    sha = file_sha256(path)
    return _load_scoring(str(folder), name, sha, os.getenv("BIDCHECK_DL_DEVICE", "cpu"))


@app.post("/v1/score")
def predict(request: ScoreRequest, authorization: str | None = Header(default=None)):
    token = os.getenv("BIDCHECK_ML_REMOTE_TOKEN")
    if not token:
        raise HTTPException(status_code=503, detail="Inference not configured")
    if not authorization or not secrets.compare_digest(authorization, "Bearer " + token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        scoring, version = model()
        values = [
            float(scoring({"query_text": request.query, "notice_text": item.notice_text or item.title}))
            for item in request.notices
        ]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Non-finite model score")
        registry = os.getenv("BIDCHECK_DL_REGISTRY_DIR")
        if registry:
            directory = active_model_dir(registry,
                                         expected_kind=os.getenv("BIDCHECK_DL_KIND", "cross_encoder"))
            evaluation = json.loads((directory/"evaluation.json").read_text(encoding="utf-8"))
            approved = True
            dataset_version = evaluation["dataset_version"]
        else:
            approved = False
            dataset_version = "unreviewed-experiment"
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Model unavailable") from exc
    return {
        "scores": values, "model_version": version, "dataset_version": dataset_version,
        "evaluation_scope": "HUMAN_REVIEWED_HOLDOUT" if approved else "UNVERIFIED",
        "champion_approved": approved,
    }
