"""Standalone opt-in inference worker. Never mounted on the AWS API by default."""
import hashlib
import os
import secrets
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="BidCheck ML Inference Worker")

class Notice(BaseModel):
    notice_id: str
    title: str

class ScoreRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    notices: list[Notice] = Field(min_length=1, max_length=150)

@lru_cache(maxsize=1)
def model():
    from .trainer import load_deep, deep_scorer
    folder = Path(os.environ["BIDCHECK_DL_MODEL_DIR"])
    name = os.getenv("BIDCHECK_DL_KIND", "cross_encoder")
    if name not in {"bi_encoder", "cross_encoder"}:
        raise ValueError("Invalid model kind")
    path = folder / (name + ".pt")
    return deep_scorer(load_deep(folder, name), os.getenv("BIDCHECK_DL_DEVICE","cpu")), name + "-" + hashlib.sha256(path.read_bytes()).hexdigest()[:16]

@app.post("/v1/score")
def predict(request: ScoreRequest, authorization: str | None = Header(default=None)):
    token = os.getenv("BIDCHECK_ML_REMOTE_TOKEN")
    if not token:
        raise HTTPException(status_code=503, detail="Inference not configured")
    if not authorization or not secrets.compare_digest(authorization, "Bearer " + token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        scoring, version = model()
        scores = [float(scoring({"query_text": request.query, "notice_text": item.title}))
                  for item in request.notices]
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Model unavailable") from exc
    return {"scores": scores, "model_version": version, "dataset_version": "local"}
