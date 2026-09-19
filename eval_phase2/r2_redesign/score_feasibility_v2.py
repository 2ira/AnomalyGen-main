#!/usr/bin/env python3
"""Score CoT feasibility v2: every <eval>, not just the first.

pred_feasible := at least one <eval>true</eval> inside <valid_paths>.
GT infeasible is correct only if pred_feasible is False.
"""
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.dirname(HERE)
sys.path.insert(0, EVAL)
from common import read_jsonl  # noqa: E402


EVAL_RE = re.compile(
    r"<eval>\s*(true|false)\s*</eval>", re.IGNORECASE
)
VALID_BLOCK = re.compile(
    r"<valid_paths>(.*?)</valid_paths>", re.IGNORECASE | re.DOTALL
)
WRONG_BLOCK = re.compile(
    r"<wrong_path>(.*?)</wrong_path>|<pruned_paths>(.*?)</pruned_paths>",
    re.IGNORECASE | re.DOTALL,
)


def parse_evals(raw):
    raw = raw or ""
    vm = VALID_BLOCK.search(raw)
    valid_xml = vm.group(1) if vm else raw
    evals = [m.group(1).lower() for m in EVAL_RE.finditer(valid_xml)]
    n_true = sum(1 for e in evals if e == "true")
    n_false = sum(1 for e in evals if e == "false")
    wm = WRONG_BLOCK.search(raw)
    wrong_xml = ""
    if wm:
        wrong_xml = wm.group(1) or wm.group(2) or ""
    n_wrong = len(re.findall(r"<path", wrong_xml, re.IGNORECASE)) if wrong_xml else 0
    if n_wrong == 0 and wrong_xml.strip() and "reason" in wrong_xml.lower():
        n_wrong = 1
    return {
        "n_eval": len(evals),
        "n_eval_true": n_true,
        "n_eval_false": n_false,
        "n_wrong_path": n_wrong,
        "pred_feasible": bool(n_true),
        "accept_all": bool(evals) and n_false == 0 and n_true == len(evals),
    }


def confusion(rows):
    tp = fp = tn = fn = err = 0
    for r in rows:
        if r.get("pred_feasible") is None:
            err += 1
            continue
        gt_pos = r["gt"] == "valid"
        if gt_pos and r["pred_feasible"]:
            tp += 1
        elif gt_pos and not r["pred_feasible"]:
            fn += 1
        elif (not gt_pos) and r["pred_feasible"]:
            fp += 1
        else:
            tn += 1
    n = tp + fp + tn + fn
    tpr = tp / (tp + fn) if (tp + fn) else 0.0
    tnr = tn / (tn + fp) if (tn + fp) else 0.0
    acc = (tp + tn) / n if n else 0.0
    bacc = 0.5 * (tpr + tnr)
    return {
        "N": n, "TP": tp, "FP": fp, "TN": tn, "FN": fn, "parse_errors": err,
        "ACC": round(acc, 4), "TPR": round(tpr, 4), "TNR": round(tnr, 4),
        "balanced_ACC": round(bacc, 4),
        "accept_all_rate": round(
            sum(1 for r in rows if r.get("accept_all")) / len(rows), 4
        ) if rows else 0,
    }


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", required=True)
    args = ap.parse_args()
    rows = read_jsonl(args.pred)
    scored = []
    for r in rows:
        p = parse_evals(r.get("raw_response") or "")
        item = dict(r)
        item.update(p)
        scored.append(item)
    overall = confusion(scored)
    by = {"overall": overall}
    for s in ("simple", "complex"):
        sub = [r for r in scored if r.get("stratum") == s]
        if sub:
            by[s] = confusion(sub)
    out = args.pred.replace(".jsonl", "_scored.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"metrics": by, "rows": [
            {k: v for k, v in r.items() if k != "raw_response"}
            for r in scored
        ]}, f, indent=2, ensure_ascii=False)
    print(json.dumps(by, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
