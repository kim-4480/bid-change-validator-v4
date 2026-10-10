"""Offline Hugging Face Transformers fine-tuning (explicit LOCAL checkpoint).

Unlike the tiny PyTorch smoke models, this path loads existing encoder weights
from a local pretrained checkpoint. It never pulls from Hugging Face at runtime.
Fine-tuned artifacts are saved under --out, never added to Git.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import random
import time
from pathlib import Path

from .trainer import load_rows,grouped,rank_metrics

def fine_tune(dataset,pretrained,out,device="cpu",epochs=1,seed=42,max_len=64):
    import torch
    from torch import nn
    from transformers import AutoModel,AutoTokenizer
    torch.manual_seed(seed)
    random.seed(seed)
    torch.set_num_threads(min(4,torch.get_num_threads()))
    target=torch.device(device)
    if device=="cuda" and not torch.cuda.is_available():
        raise ValueError("Requested CUDA is not available")
    src=Path(pretrained)
    if not src.exists():
        raise FileNotFoundError("Pretrained model must exist in local isolated cache: "+str(src))
    tokenizer=AutoTokenizer.from_pretrained(str(src),local_files_only=True)
    train=grouped(load_rows(dataset),"train")
    test=grouped(load_rows(dataset),"test")
    out=Path(out)
    out.mkdir(parents=True,exist_ok=True)
    report={}
    class HFModel(nn.Module):
        def __init__(self,model_type):
            super().__init__()
            self.base=AutoModel.from_pretrained(str(src),local_files_only=True)
            self.model_type=model_type
            self.head=nn.Linear(self.base.config.hidden_size,1) if model_type=="cross_encoder" else None
        def embed(self,encoded):
            result=self.base(**encoded).last_hidden_state
            mask=encoded["attention_mask"].unsqueeze(-1)
            vec=(result*mask).sum(1)/mask.sum(1).clamp(min=1)
            return torch.nn.functional.normalize(vec,dim=-1)
        def forward(self,q,text):
            if self.model_type=="cross_encoder":
                batch=tokenizer(q,text,return_tensors="pt",padding=True,truncation=True,
                                max_length=max_len).to(target)
                result=self.base(**batch).last_hidden_state
                pooled=result[:,0]
                return self.head(pooled).squeeze(-1)
            qbatch=tokenizer(q,return_tensors="pt",padding=True,truncation=True,
                             max_length=max_len).to(target)
            dbatch=tokenizer(text,return_tensors="pt",padding=True,truncation=True,
                             max_length=max_len).to(target)
            return (self.embed(qbatch)*self.embed(dbatch)).sum(-1)
    for model_type in ("bi_encoder","cross_encoder"):
        model=HFModel(model_type).to(target)
        optimizer=torch.optim.AdamW(model.parameters(),lr=2e-4,weight_decay=.01)
        curve=[]
        for epoch in range(epochs):
            rng=random.Random(seed+epoch)
            rng.shuffle(train)
            losses=[]
            for group in train:
                pos=next((r for r in group if r["label"]>0),None)
                neg=next((r for r in group if r["label"]==0),None)
                if pos is None or neg is None:
                    continue
                model.train()
                score=model([pos["query_text"]]*2,[pos["notice_text"],neg["notice_text"]])
                loss=torch.nn.functional.softplus(score[1]-score[0])
                optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(model.parameters(),1.0)
                optimizer.step()
                losses.append(float(loss.detach().cpu()))
            curve.append({"epoch":epoch+1,"pairwise_loss":sum(losses)/max(1,len(losses)),
                          "updates":len(losses)})
        model.eval()
        @torch.inference_mode()
        def score_one(row):
            return float(model([row["query_text"]],[row["notice_text"]])[0].cpu())
        metrics=rank_metrics(test,score_one)
        path=out/("hf_"+model_type+".pt")
        torch.save({"state":{k:v.cpu() for k,v in model.state_dict().items()},
                    "architecture":"transformers.AutoModel.finetune",
                    "pretrained_source_local":str(src),"kind":model_type,"seed":seed},path)
        report[model_type]={"training_curve":curve,"metrics":metrics,
            "model_file":path.name,"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
            "bytes":path.stat().st_size}
        del model
    meta={"scope":"SYNTHETIC title labels, pipeline check only, NOT real relevance",
          "pretrained_local":str(src),"epochs":epochs,"seed":seed,
          "dataset_sha256":hashlib.sha256(Path(dataset).read_bytes()).hexdigest(),
          "models":report,"aws_api_calls":0,"s3_download_bytes":0}
    (out/"hf_finetune_evaluation.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
    return meta

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--dataset",required=True)
    p.add_argument("--pretrained-local",required=True,help="Must be a local pretrained model checkpoint directory")
    p.add_argument("--out",required=True)
    p.add_argument("--device",choices=("cpu","cuda"),default="cpu")
    p.add_argument("--epochs",type=int,default=1)
    p.add_argument("--seed",type=int,default=42)
    args=p.parse_args()
    print(json.dumps(fine_tune(args.dataset,args.pretrained_local,args.out,args.device,args.epochs,args.seed),
                     ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()
