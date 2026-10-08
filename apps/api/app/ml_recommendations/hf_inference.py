"""Reload locally trained Transformers checkpoints and score queries offline.

Uses local_files_only, validates SHA256 and requires explicit pretrained path.
No network request occurs during loading or inference.
"""
from __future__ import annotations
import hashlib
import json
from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=2)
def load_finetuned(directory,pretrained,kind="cross_encoder",device="cpu"):
    import torch
    from torch import nn
    from transformers import AutoModel, AutoTokenizer, AutoConfig
    if kind not in ("bi_encoder","cross_encoder"):
        raise ValueError("Invalid HF encoder")
    folder=Path(directory)
    meta=json.loads((folder/"hf_finetune_evaluation.json").read_text(encoding="utf-8"))
    path=folder/("hf_"+kind+".pt")
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    if sha!=meta["models"][kind]["sha256"]:
        raise ValueError("HF checkpoint SHA256 mismatch")
    local=Path(pretrained)
    if not local.is_dir():raise FileNotFoundError("Local pretrained checkpoint required")
    if device=="cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable")
    config=AutoConfig.from_pretrained(str(local),local_files_only=True)
    tokenizer=AutoTokenizer.from_pretrained(str(local),local_files_only=True)
    class Reloaded(nn.Module):
        def __init__(self):
            super().__init__()
            self.base=AutoModel.from_config(config)
            self.head=nn.Linear(config.hidden_size,1) if kind=="cross_encoder" else None
        def encode(self,encoded):
            h=self.base(**encoded).last_hidden_state
            mask=encoded["attention_mask"].unsqueeze(-1)
            return torch.nn.functional.normalize((h*mask).sum(1)/mask.sum(1).clamp(min=1),dim=-1)
        def forward(self,q,t):
            if kind=="cross_encoder":
                x=tokenizer(q,t,return_tensors="pt",truncation=True,padding=True,max_length=64).to(device)
                return self.head(self.base(**x).last_hidden_state[:,0]).squeeze(-1)
            qa=tokenizer(q,return_tensors="pt",truncation=True,padding=True,max_length=64).to(device)
            ta=tokenizer(t,return_tensors="pt",truncation=True,padding=True,max_length=64).to(device)
            return (self.encode(qa)*self.encode(ta)).sum(-1)
    model=Reloaded().to(device)
    state=torch.load(path,map_location="cpu",weights_only=True)
    if state["kind"]!=kind or state["architecture"]!="transformers.AutoModel.finetune":
        raise ValueError("Incompatible checkpoint architecture")
    model.load_state_dict(state["state"],strict=True)
    model.eval()
    @torch.inference_mode()
    def scorer(query,text):
        return float(model([query],[text])[0].cpu())
    return scorer,sha,meta

def score_hf(query,notices,dir,pretrained,kind="cross_encoder",device="cpu"):
    scorer,sha,meta=load_finetuned(str(dir),str(pretrained),kind,device)
    values=[scorer(query,n["title"]) for n in notices]
    ranked=sorted((dict(row,score=float(v)) for row,v in zip(notices,values)),
                  key=lambda x:(-x["score"],str(x["notice_id"])))
    return ranked,"hf-"+kind+"-"+sha[:12],meta.get("dataset_sha256","unknown"),"local_hf",None
