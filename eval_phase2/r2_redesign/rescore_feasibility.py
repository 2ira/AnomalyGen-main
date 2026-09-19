#!/usr/bin/env python3
"""Rescore the 40-merge-point feasibility benchmark under two decision rules.

The published scorer reads the FIRST <eval> element of the merge response. The
production merge prompt always emits at least one accepted path, so that rule
degenerates to accept-all for both variants and cannot separate them. The
verifier's actual rejection signal is <wrong_path>, which carries the pruned
candidate together with a reason.

  first_eval    published rule: verdict = first <eval>
  wrong_path    verdict = infeasible iff <wrong_path> is non-empty

Writes eval_results/feasibility_granularity.json.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.dirname(HERE)
GT = os.path.join(EVAL, "eval_data", "feasibility_manual.jsonl")
OUT = os.path.join(EVAL, "eval_results", "feasibility_granularity.json")

RUNS = {
    "archive_truncated": ("archive_truncated_500/feasibility_pred_cot.jsonl",
                          "archive_truncated_500/feasibility_pred_nocot.jsonl"),
    "x1_untruncated": ("x1_rerun/feasibility_pred_cot.jsonl",
                       "x1_rerun/feasibility_pred_nocot.jsonl"),
}


def read_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def section(text, tag):
    m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.S)
    return m.group(1) if m else None


def verdicts(raw):
    """Return {rule: bool|None} for one raw response."""
    text = raw or ""
    evals = re.findall(r"<eval>\s*(\w+)\s*</eval>", text, re.I)
    wrong = section(text, "wrong_path")
    valid = section(text, "valid_paths")
    out = {"first_eval": evals[0].lower() == "true" if evals else None}
    if wrong is not None:
        out["wrong_path"] = not wrong.strip()
    elif valid is not None:
        out["wrong_path"] = True
    else:
        out["wrong_path"] = None
    return out


def confusion(gt, preds):
    cells = Counter()
    strata = defaultdict(Counter)
    for mp_id, g in gt.items():
        truth = g["gt"] == "valid"
        p = preds.get(mp_id)
        if p is None:
            cell = "unparsed"
        else:
            cell = ("TP" if p else "FN") if truth else ("FP" if p else "TN")
        cells[cell] += 1
        strata[g["stratum"]][cell] += 1

    def block(c):
        n = sum(c.values())
        correct = c["TP"] + c["TN"]
        rec = c["TP"] / max(1, c["TP"] + c["FN"])
        spec = c["TN"] / max(1, c["TN"] + c["FP"])
        return {
            "n": n, "TP": c["TP"], "TN": c["TN"], "FP": c["FP"], "FN": c["FN"],
            "unparsed": c["unparsed"], "accuracy": round(correct / n, 4) if n else None,
            "recall_feasible": round(rec, 4), "specificity_infeasible": round(spec, 4),
            "balanced_accuracy": round((rec + spec) / 2, 4),
        }

    res = {"overall": block(cells)}
    for s, c in strata.items():
        res[s] = block(c)
    return res


def main():
    gt = {r["mp_id"]: r for r in read_jsonl(GT)}
    report = {
        "n_merge_points": len(gt),
        "gt_distribution": dict(Counter(r["gt"] for r in gt.values())),
        "stratum_distribution": dict(Counter(r["stratum"] for r in gt.values())),
        "runs": {},
    }
    for run, (cot_path, nocot_path) in RUNS.items():
        entry = {}
        for variant, rel in (("cot", cot_path), ("nocot", nocot_path)):
            rows = read_jsonl(os.path.join(EVAL, "eval_results", rel))
            lengths = [len(r.get("raw_response") or "") for r in rows]
            per_rule = defaultdict(dict)
            for r in rows:
                for rule, v in verdicts(r.get("raw_response")).items():
                    per_rule[rule][r["mp_id"]] = v
            entry[variant] = {
                "n_responses": len(rows),
                "max_response_chars": max(lengths),
                "n_at_500_char_limit": sum(1 for x in lengths if x == 500),
                "scores": {rule: confusion(gt, preds) for rule, preds in per_rule.items()},
            }
        report["runs"][run] = entry

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    for run, entry in report["runs"].items():
        print(f"\n===== {run} =====")
        for variant, d in entry.items():
            print(f"  {variant}: n={d['n_responses']} max_chars={d['max_response_chars']} "
                  f"at_limit={d['n_at_500_char_limit']}")
            for rule, sc in d["scores"].items():
                o = sc["overall"]
                print(f"     {rule:<12} acc={o['accuracy']:.4f} "
                      f"TP={o['TP']} TN={o['TN']} FP={o['FP']} FN={o['FN']} "
                      f"unparsed={o['unparsed']} balacc={o['balanced_accuracy']:.3f}")
                for s in ("simple", "complex"):
                    b = sc[s]
                    print(f"        {s:<8} {b['accuracy']:.4f}  TN={b['TN']}/{b['TN']+b['FP']}")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
