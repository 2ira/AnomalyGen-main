#!/usr/bin/env python3
"""R2.13: split baseline false alarms by whether the session contains a
template absent from the training vocabulary.

Inputs (all local, no GPU):
  --train-pkl   session_train.pkl  (templates + labels)
  --test-pkl    session_test.pkl
  --pred-csv    session_preds.csv from DEEPLOGLIZER_PRED_DUMP
  --topk        window_pred_anomaly_{k} column to use (default 10)
  --n-cases     how many example FPs to print (default 8)

session_idx in the CSV is enumerate() order over session_test.values(),
which matches OrderedDict insertion order of the pickle.
"""
from __future__ import annotations

import argparse
import csv
import json
import pickle
from collections import Counter, OrderedDict
from pathlib import Path


def load_sessions(pkl_path: Path) -> OrderedDict:
    with open(pkl_path, "rb") as f:
        return pickle.load(f)


def vocab(sessions) -> set:
    v = set()
    for s in sessions.values():
        v.update(s["templates"])
    return v


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--train-pkl", required=True)
    p.add_argument("--test-pkl", required=True)
    p.add_argument("--pred-csv", required=True)
    p.add_argument("--topk", type=int, default=10)
    p.add_argument("--n-cases", type=int, default=8)
    p.add_argument("--out", default=None)
    args = p.parse_args()

    train = load_sessions(Path(args.train_pkl))
    test = load_sessions(Path(args.test_pkl))
    train_vocab = vocab(train)
    keys = list(test.keys())

    pred_col = f"window_pred_anomaly_{args.topk}"
    rows = []
    with open(args.pred_csv) as f:
        for r in csv.DictReader(f):
            idx = int(r["session_idx"])
            y_true = int(int(float(r["window_anomalies"])) > 0)
            y_pred = int(int(float(r[pred_col])) > 0)
            sid = keys[idx]
            templates = list(test[sid]["templates"])
            unseen = sorted({t for t in templates if t not in train_vocab})
            rows.append(
                {
                    "session_idx": idx,
                    "block_id": sid,
                    "y_true": y_true,
                    "y_pred": y_pred,
                    "n_unseen_templates": len(unseen),
                    "has_unseen": int(len(unseen) > 0),
                    "unseen_templates": unseen,
                    "n_events": len(templates),
                }
            )

    n = len(rows)
    fp = [r for r in rows if r["y_true"] == 0 and r["y_pred"] == 1]
    tn = [r for r in rows if r["y_true"] == 0 and r["y_pred"] == 0]
    tp = [r for r in rows if r["y_true"] == 1 and r["y_pred"] == 1]
    fn = [r for r in rows if r["y_true"] == 1 and r["y_pred"] == 0]
    normals = [r for r in rows if r["y_true"] == 0]
    normals_unseen = [r for r in normals if r["has_unseen"]]
    normals_seen = [r for r in normals if not r["has_unseen"]]

    def rate(group, pred=1):
        if not group:
            return None
        return sum(r["y_pred"] == pred for r in group) / len(group)

    summary = {
        "n_test": n,
        "train_vocab": len(train_vocab),
        "confusion": {
            "tp": len(tp),
            "fp": len(fp),
            "tn": len(tn),
            "fn": len(fn),
        },
        "normals_with_unseen_template": len(normals_unseen),
        "normals_all_seen": len(normals_seen),
        "fp_with_unseen": sum(r["has_unseen"] for r in fp),
        "fp_all_seen": sum(1 - r["has_unseen"] for r in fp),
        "false_alarm_rate_unseen_normals": rate(normals_unseen, 1),
        "false_alarm_rate_seen_normals": rate(normals_seen, 1),
        "share_of_fps_that_have_unseen": (sum(r["has_unseen"] for r in fp) / len(fp))
        if fp
        else None,
    }

    # example cases: FPs that contain an unseen template, shortest first
    cases = sorted(
        [r for r in fp if r["has_unseen"]],
        key=lambda r: (r["n_events"], r["n_unseen_templates"]),
    )[: args.n_cases]
    for c in cases:
        c["unseen_templates"] = c["unseen_templates"][:6]

    out = {
        "summary": summary,
        "example_fp_unseen": [
            {
                "block_id": c["block_id"],
                "n_events": c["n_events"],
                "n_unseen_templates": c["n_unseen_templates"],
                "unseen_templates": c["unseen_templates"],
            }
            for c in cases
        ],
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    dest = Path(args.out) if args.out else Path(args.pred_csv).with_name("unseen_fp_summary.json")
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print("wrote", dest)


if __name__ == "__main__":
    main()
