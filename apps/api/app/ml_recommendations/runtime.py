"""Inference-only recommendation scorer with deterministic safe fallback.

No training or network calls at import time. Remote inference is opt-in through
an environment variable and never contacted by unit tests.
"""
from __future__ import annotations
import hashlib
import json
import os
import math
import threading
from urllib.parse import urlsplit
from pathlib import Path

_LOCK=threading.Lock()
_CACHE={}

def lexical(query,title):
    import re
    a=set(re.findall(r"[\uac00-\ud7a3A-Za-z0-9]+",query.lower()))
    b=set(re.findall(r"[\uac00-\ud7a3A-Za-z0-9]+",title.lower()))
    return len(a&b)/max(1,len(a))

def _load_local(directory):
    path=Path(directory)/"lightgbm.txt"
    report=Path(directory)/"evaluation.json"
    if not path.is_file() or not report.is_file():
        raise FileNotFoundError("Model file or evaluation manifest missing")
    data=json.loads(report.read_text(encoding="utf-8"))
    actual=hashlib.sha256(path.read_bytes()).hexdigest()
    if actual!=data["model_sha256"]["lightgbm.txt"]:
        raise ValueError("Model SHA256 mismatch")
    from lightgbm import Booster
    return Booster(model_file=str(path)),data["dataset_version"],actual[:16]

def score_notices(query,notices,*,local_dir=None,remote_url=None,timeout=1.0):
    """Rank rows with notice_id/title, returning (items, model, dataset, source, fallback_reason)."""
    if not notices:
        return [],None,None,"lexical_fallback","no_candidates"
    registry_dir=os.getenv("BIDCHECK_ML_REGISTRY_DIR")
    registry_failure=None
    if local_dir is None and registry_dir:
        try:
            from .registry import active_model_dir
            local_dir=str(active_model_dir(registry_dir))
        except (ValueError, OSError, KeyError, TypeError) as error:
            # Never silently fall through to an arbitrary unapproved local dir.
            registry_failure=type(error).__name__
            local_dir=""
    else:
        local_dir=local_dir if local_dir is not None else os.getenv("BIDCHECK_ML_MODEL_DIR")
    remote_url=remote_url if remote_url is not None else os.getenv("BIDCHECK_ML_INFERENCE_URL")
    local_failure=registry_failure
    if local_dir:
        try:
            if (not registry_dir and os.getenv("BIDCHECK_ML_ALLOW_UNREGISTERED")!="1"
                and os.getenv("BIDCHECK_ML_ALLOW_SYNTHETIC")!="1"):
                raise ValueError("Manual Champion registry approval required")
            if os.getenv("BIDCHECK_ML_ALLOW_SYNTHETIC")!="1":
                audit=json.loads((Path(local_dir)/"evaluation.json").read_text(encoding="utf-8"))
                if audit.get("evaluation_scope") != "HUMAN_REVIEWED_HOLDOUT":
                    raise ValueError("model_has_no_human_validated_holdout")
            # Always recheck the artifact hash on every request, even when cached.
            digest=hashlib.sha256((Path(local_dir)/"lightgbm.txt").read_bytes()).hexdigest()
            manifest=json.loads((Path(local_dir)/"evaluation.json").read_text(encoding="utf-8"))
            if digest != manifest.get("model_sha256",{}).get("lightgbm.txt"):
                raise ValueError("Model SHA256 mismatch")
            with _LOCK:
                cache_key=(str(local_dir),digest)
                if cache_key not in _CACHE:
                    _CACHE[cache_key]=_load_local(local_dir)
                model,version,sha=_CACHE[cache_key]
            from .trainer import features
            import numpy as np
            x=np.stack([features(query,row.get("notice_text") or row["title"]) for row in notices])
            scores=model.predict(x,num_threads=1)
            ranked=sorted([dict(r,score=float(score)) for r,score in zip(notices,scores)],
                          key=lambda r:(-r["score"],str(r["notice_id"])))
            return ranked,"lightgbm-"+sha,version,"local_lightgbm",None
        except Exception as exc:
            local_failure=type(exc).__name__
    hf_dir=os.getenv("BIDCHECK_ML_HF_DIR")
    if hf_dir:
        try:
            if (os.getenv("BIDCHECK_ML_ALLOW_UNREGISTERED")!="1"
                and os.getenv("BIDCHECK_ML_ALLOW_SYNTHETIC")!="1"):
                raise ValueError("HF model needs an explicit local experimental opt-in")
            if os.getenv("BIDCHECK_ML_ALLOW_SYNTHETIC")!="1":
                meta=json.loads((Path(hf_dir)/"hf_finetune_evaluation.json").read_text(encoding="utf-8"))
                if "SYNTHETIC" in meta.get("scope",""):
                    raise ValueError("hf_model_has_no_human_validated_holdout")
            from .hf_inference import score_hf
            return score_hf(query,notices,hf_dir,os.environ["BIDCHECK_ML_HF_PRETRAINED"],
                            os.getenv("BIDCHECK_ML_HF_KIND","cross_encoder"))
        except Exception as exc:
            local_failure=(local_failure+"/" if local_failure else "")+type(exc).__name__
    if remote_url:
        try:
            import httpx
            token=os.getenv("BIDCHECK_ML_REMOTE_TOKEN")
            if not token:
                raise ValueError("remote_token_not_configured")
            parsed=urlsplit(remote_url)
            if parsed.scheme!="https" and not (parsed.scheme=="http" and parsed.hostname in {"localhost","127.0.0.1"}):
                raise ValueError("remote_inference_requires_https")
            # The local worker accepts at most 150 items per call. Score ALL
            # valid candidates in bounded chunks, with a stable model version.
            scores=[]
            remote_model=None
            remote_dataset=None
            for offset in range(0,len(notices),100):
                chunk=notices[offset:offset+100]
                response=httpx.post(remote_url,json={"query":query,"notices":chunk},
                                    headers={"Authorization":"Bearer "+token},
                                    timeout=timeout,follow_redirects=False)
                response.raise_for_status()
                payload=response.json()
                new_scores=payload["scores"]
                if len(new_scores)!=len(chunk) or any(
                    isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x)
                    for x in new_scores
                ):
                    raise ValueError("Invalid inference response")
                if os.getenv("BIDCHECK_ML_ALLOW_UNREGISTERED")!="1":
                    if not (payload.get("evaluation_scope")=="HUMAN_REVIEWED_HOLDOUT"
                            and payload.get("champion_approved") is True):
                        raise ValueError("Unapproved remote model")
                version=str(payload.get("model_version","remote"))[:100]
                dataset=str(payload.get("dataset_version","unknown"))[:100]
                if remote_model is not None and (remote_model!=version or remote_dataset!=dataset):
                    raise ValueError("Remote model changed within scoring request")
                remote_model,remote_dataset=version,dataset
                scores.extend(new_scores)
            ranked=sorted([dict(r,score=float(s)) for r,s in zip(notices,scores)],
                          key=lambda r:(-r["score"],str(r["notice_id"])))
            return ranked,remote_model,remote_dataset,"remote_inference",None
        except Exception as exc:
            local_failure=(local_failure+"/" if local_failure else "")+type(exc).__name__
    ranked=sorted([dict(r,score=float(lexical(query,r.get("notice_text") or r["title"]))) for r in notices],
                  key=lambda r:(-r["score"],str(r["notice_id"])))
    return ranked,None,None,"lexical_fallback",local_failure or "model_not_configured"
