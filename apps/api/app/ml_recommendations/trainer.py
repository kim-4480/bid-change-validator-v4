"""Independent offline CPU/optional GPU training and synthetic-holdout evaluation."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from .dataset import audit

def load_rows(path):
    rows = [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
    report = audit(rows)
    if not report["passed"]:
        raise ValueError("Dataset leakage detected: " + str(report))
    return rows

def terms(value):
    import re
    return re.findall(r"[\uac00-\ud7a3A-Za-z0-9]+",value.lower())

def features(query, text):
    qa, ta = terms(query), terms(text)
    q, t = set(qa), set(ta)
    shared = len(q & t)
    return np.asarray([shared,shared/max(1,len(q)),shared/max(1,len(t)),
        len(q & t)/max(1,len(q|t)),
        float(query.lower() in text.lower()),len(query),len(text),abs(len(query)-len(text)),
        sum(min(ta.count(w),qa.count(w)) for w in q),
        sum(1 for a,b in zip(query,text) if a==b),
        len(set(query.lower()) & set(text.lower()))/max(1,len(set(query.lower()) | set(text.lower())))],
        dtype=np.float32)

def baseline_score(row):
    return float(features(row["query_text"],row["notice_text"])[1])

def grouped(rows, split):
    data=defaultdict(list)
    for row in rows:
        if row["split"]==split:
            data[row["query_id"]].append(row)
    return [data[k] for k in sorted(data)]

def lgb_fit(rows, output, seed):
    import lightgbm as lgb
    groups=grouped(rows,"train")
    X=np.array([features(r["query_text"],r["notice_text"]) for g in groups for r in g])
    y=np.array([r["label"] for g in groups for r in g],dtype=np.int32)
    if len(set(y))<2:
        raise ValueError("Not enough label diversity")
    ranker=lgb.LGBMRanker(n_estimators=35,learning_rate=.07,num_leaves=7,
        min_child_samples=2,max_depth=4,random_state=seed,n_jobs=2,verbosity=-1)
    validation_groups=grouped(rows,"validation")
    vx=np.array([features(r["query_text"],r["notice_text"]) for g in validation_groups for r in g])
    vy=np.array([r["label"] for g in validation_groups for r in g],dtype=np.int32)
    learning_curve={}
    ranker.fit(X,y,group=[len(g) for g in groups],
        eval_set=[(vx,vy)],eval_group=[[len(g) for g in validation_groups]],
        eval_at=[1,3],callbacks=[lgb.record_evaluation(learning_curve)])
    path=Path(output)/"lightgbm.txt"
    ranker.booster_.save_model(str(path))
    return ranker.booster_,learning_curve

def lgb_score(model,row):
    return float(model.predict(features(row["query_text"],row["notice_text"]).reshape(1,-1))[0])

def dcg(labels):
    return sum((2**v-1)/math.log2(i+2) for i,v in enumerate(labels))

def rank_metrics(groups, score_fn, k=3, min_label=1):
    keys=["Recall@K","Precision@K","MRR","nDCG@K"]
    values={key:[] for key in keys}
    elapsed=[]
    failures=[]
    for group in groups:
        clock=time.perf_counter()
        scored=sorted(((score_fn(r),r) for r in group),key=lambda x:(-x[0],x[1]["notice_id"]))
        elapsed.append((time.perf_counter()-clock)*1000)
        gold=[r for r in group if r["label"]>=min_label]
        ranked=[r for _,r in scored]
        relevant=sum(r["label"]>=min_label for r in ranked[:k])
        values["Recall@K"].append(relevant/max(1,len(gold)))
        values["Precision@K"].append(relevant/max(1,min(k,len(ranked))))
        values["MRR"].append(next((1/(i+1) for i,r in enumerate(ranked) if r["label"]>=min_label),0))
        ideal=dcg(sorted((r["label"] for r in group),reverse=True)[:k])
        values["nDCG@K"].append(dcg([r["label"] for r in ranked[:k]])/ideal if ideal else 0)
        if ranked and ranked[0]["label"]==0 and len(failures)<10:
            failures.append({"query_id":group[0]["query_id"],"query":group[0]["query_text"],
                             "top_notice":ranked[0]["notice_id"],"reason":"top-ranked candidate synthetic-negative"})
    return {**{key:float(statistics.mean(value)) if value else None for key,value in values.items()},
        "latency_p50_ms":float(np.percentile(elapsed,50)) if elapsed else None,
        "latency_p95_ms":float(np.percentile(elapsed,95)) if elapsed else None,
        "queries":len(groups),"failures":failures}

def encode(text,length=80):
    raw=text.encode("utf-8")[:length]
    return list(raw)+[0]*(length-len(raw))

def make_models():
    import torch
    from torch import nn
    import torch.nn.functional as F
    class Encoder(nn.Module):
        def __init__(self):
            super().__init__()
            self.embed=nn.Embedding(260,32,padding_idx=0)
            layer=nn.TransformerEncoderLayer(32,4,64,dropout=0,batch_first=True)
            self.transformer=nn.TransformerEncoder(layer,1,enable_nested_tensor=False)
        def forward(self,x):
            mask=x.eq(0)
            h=self.transformer(self.embed(x),src_key_padding_mask=mask)
            return F.normalize((h*(~mask).unsqueeze(-1)).sum(1)/(~mask).sum(1).clamp(min=1).unsqueeze(-1),dim=-1)
    class Bi(nn.Module):
        def __init__(self):
            super().__init__()
            self.encoder=Encoder()
        def forward(self,q,d):
            return (self.encoder(q)*self.encoder(d)).sum(-1)
    class Cross(nn.Module):
        def __init__(self):
            super().__init__()
            self.embed=nn.Embedding(260,32,padding_idx=0)
            layer=nn.TransformerEncoderLayer(32,4,64,dropout=0,batch_first=True)
            self.transformer=nn.TransformerEncoder(layer,1,enable_nested_tensor=False)
            self.out=nn.Linear(32,1)
        def forward(self,q,d):
            import torch
            x=torch.cat([q[:,:40],torch.full((len(q),1),257,dtype=torch.long,device=q.device),d[:,:40]],dim=1)
            mask=x.eq(0)
            h=self.transformer(self.embed(x),src_key_padding_mask=mask)
            return self.out((h*(~mask).unsqueeze(-1)).sum(1)/(~mask).sum(1).clamp(min=1).unsqueeze(-1)).squeeze(-1)
    return Bi(),Cross()

def deep_fit(rows,output,seed,device="cpu",epochs=2):
    import torch
    torch.set_num_threads(min(4,torch.get_num_threads()))
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if device=="cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA explicitly requested, but no GPU is available")
    use_device=torch.device(device)
    train=grouped(rows,"train")
    bi,cross=make_models()
    logs={}
    for name,model in (("bi_encoder",bi),("cross_encoder",cross)):
        model=model.to(use_device)
        optimizer=torch.optim.AdamW(model.parameters(),lr=.002)
        curve=[]
        rng=random.Random(seed)
        for epoch in range(epochs):
            rng.shuffle(train)
            losses=[]
            for group in train:
                pos=next((r for r in group if r["label"]>=min_label),None)
                neg=next((r for r in group if r["label"]==0),None)
                if pos is None or neg is None:
                    continue
                q=torch.tensor([encode(pos["query_text"])]*2,dtype=torch.long,device=use_device)
                docs=torch.tensor([encode(pos["notice_text"]),encode(neg["notice_text"])],dtype=torch.long,device=use_device)
                model.train()
                scores=model(q,docs)
                loss=torch.nn.functional.softplus(scores[1]-scores[0])
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                losses.append(float(loss.detach().cpu()))
            curve.append({"epoch":epoch+1,"pairwise_loss":float(np.mean(losses)) if losses else None,
                          "updates":len(losses)})
        path=Path(output)/(name+".pt")
        torch.save({"model":model.cpu().state_dict(),"type":name,"seed":seed,
                    "architecture":"scratch-byte-transformer-v1",
                    "training_label_origin":"synthetic_or_reviewed"},path)
        logs[name]={"curve":curve,"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
                    "bytes":path.stat().st_size}
    return logs

def load_deep(output,name):
    import torch
    bi,cross=make_models()
    model=bi if name=="bi_encoder" else cross
    chk=torch.load(Path(output)/(name+".pt"),map_location="cpu",weights_only=True)
    model.load_state_dict(chk["model"],strict=True)
    model.eval()
    return model

def deep_scorer(model,device="cpu"):
    import torch
    torch.set_num_threads(min(4,torch.get_num_threads()))
    if device=="cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA is not available")
    model=model.to(device).eval()
    @torch.inference_mode()
    def score(row):
        q=torch.tensor([encode(row["query_text"])],dtype=torch.long,device=device)
        d=torch.tensor([encode(row["notice_text"])],dtype=torch.long,device=device)
        return float(model(q,d)[0].cpu())
    return score

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--dataset",required=True)
    p.add_argument("--out",required=True)
    p.add_argument("--device",choices=("cpu","cuda"),default="cpu")
    p.add_argument("--seed",type=int,default=42)
    p.add_argument("--epochs",type=int,default=2)
    p.add_argument("--mlflow-local",action="store_true",help="Opt-in, file-backed LOCAL MLflow only")
    args=p.parse_args()
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    rows=load_rows(args.dataset)
    manifest=Path(args.dataset).parent/"manifest.json"
    if not manifest.exists():
        raise FileNotFoundError("Manifest required")
    dataset_info=json.loads(manifest.read_text(encoding="utf-8"))
    actual_hash=hashlib.sha256(Path(args.dataset).read_bytes()).hexdigest()
    if dataset_info["sha256"]["pairs.jsonl"]!=actual_hash:
        raise ValueError("Dataset integrity hash mismatch")
    seed=args.seed
    test=grouped(rows,"test")
    baseline=rank_metrics(test,baseline_score)
    ml,lightgbm_curve=lgb_fit(rows,out,seed)
    ml_result=rank_metrics(test,lambda r:lgb_score(ml,r))
    training=deep_fit(rows,out,seed,args.device,args.epochs)
    training["lightgbm"]={"validation_curve":lightgbm_curve}
    scores={"baseline_rule":baseline,"lightgbm":ml_result}
    for name in ("bi_encoder","cross_encoder"):
        scores[name]=rank_metrics(test,deep_scorer(load_deep(out,name)))
    files=["lightgbm.txt","bi_encoder.pt","cross_encoder.pt"]
    sha={name:hashlib.sha256((out/name).read_bytes()).hexdigest() for name in files}
    report={"dataset_version":dataset_info["dataset_version"],"dataset_sha256":actual_hash,
            "evaluation_scope":"SYNTHETIC ONLY - not real ranking accuracy" if not dataset_info["reviewed_labels"] else "MIXED LABEL ORIGINS - report per origin before claiming real accuracy",
            "holdout_queries":len(test),"device":args.device,"seed":seed,"epochs":args.epochs,
            "model_sha256":sha,"training":training,"metrics":scores,
            "leakage":audit(rows),"aws_requests":0,"aws_download_bytes":0,"paid_services_changed":False}
    (out/"evaluation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    if args.mlflow_local:
        import mlflow
        mlflow.set_tracking_uri("sqlite:///" + (out/"mlflow.db").resolve().as_posix())
        with mlflow.start_run(run_name="bidcheck-offline-pseudo-eval"):
            mlflow.log_params(dict(seed=seed,epochs=args.epochs,dataset_sha256=actual_hash,device=args.device))
            for model,metrics in scores.items():
                for key,value in metrics.items():
                    if isinstance(value,(int,float)):
                        mlflow.log_metric(model+"_"+key.replace("@","_"),value)
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()
