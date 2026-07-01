#!/usr/bin/env python3
"""
Path-feasibility evaluation: CoT vs no-CoT on the 40-merge-point benchmark.

Reads feasibility_manual.jsonl, calls the AnomalyGen merge prompt (CoT or
no-CoT variant), and computes ACC / F1 / per-stratum breakdown.

Usage:
    cd AnomalyGen-main
    python eval_phase2/run_feasibility_eval.py --variant cot   [--sleep 0.3]
    python eval_phase2/run_feasibility_eval.py --variant nocot [--sleep 0.3]
    python eval_phase2/run_feasibility_eval.py --report
"""
import os
import sys
import re
import json
import argparse
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from models.prompts.merge_node_info import (
    get_merge_nodes_by_llm_v7,
    get_merge_nodes_by_llm_without_cot,
)
from models.get_resp import get_response
from common import read_jsonl, write_jsonl, parse_merge_xml, EVAL_DATA_DIR, EVAL_RESULT_DIR

os.makedirs(EVAL_RESULT_DIR, exist_ok=True)
DATASET = os.path.join(EVAL_DATA_DIR, "feasibility_manual.jsonl")


# ── Feasibility decision ────────────────────────────────────────────────
def is_feasible(message):
    """Unified CoT + no-CoT scoring.

    Hard prune:  pruned_paths present + empty valid_paths → infeasible
    Soft reject: all <eval> tags are false → infeasible
    """
    valid, pruned = parse_merge_xml(message)
    all_evals = re.findall(r"<eval>(.*?)</eval>", message, re.IGNORECASE)
    has_true = any(e.strip().lower() == 'true' for e in all_evals)
    has_false = any(e.strip().lower() == 'false' for e in all_evals)
    has_valid = len(valid) > 0 or bool(
        re.search(r"<valid_paths>[^<\s]", message))
    empty_valid = bool(re.search(
        r"<valid_paths\s*/>|(?<=<valid_paths>)\s*(?=</valid_paths>)", message))
    has_pruned = len(pruned) > 0

    if has_pruned and (empty_valid or not has_valid):
        return False
    if has_valid and has_false and not has_true:
        return False
    if has_true:
        return True
    if has_valid:
        return True
    return None


# ── LLM invocation ──────────────────────────────────────────────────────
def run_one(mp, variant):
    parent_info = ("node name is " + mp["caller"]
                   + " node log is " + str(mp["caller_log"])
                   + " source code: " + str(mp["caller_code"]))
    child_info = ("node name is " + mp["callee"]
                  + " node log is " + str(mp["callee_log"])
                  + " source code: " + str(mp["callee_code"]))

    gen = (get_merge_nodes_by_llm_v7 if variant == "cot"
           else get_merge_nodes_by_llm_without_cot)
    prompts = list(gen(parent_info, child_info))
    raw = get_response(prompts)
    pred = is_feasible(raw)

    return {
        "mp_id": mp["mp_id"],
        "variant": variant,
        "gt": mp["gt"],
        "pred_feasible": pred,
        "stratum": mp.get("stratum", "simple"),
        "raw_response": raw,
    }


# ── Metrics ──────────────────────────────────────────────────────────────
def binary_metrics(rows):
    tp = fp = tn = fn = err = 0
    for r in rows:
        if r["pred_feasible"] is None:
            err += 1
            continue
        gt_pos = (r["gt"] == "valid")
        if gt_pos and r["pred_feasible"]:
            tp += 1
        elif gt_pos and not r["pred_feasible"]:
            fn += 1
        elif not gt_pos and r["pred_feasible"]:
            fp += 1
        else:
            tn += 1
    n = tp + fp + tn + fn
    return {
        "N": n, "TP": tp, "FP": fp, "TN": tn, "FN": fn,
        "parse_errors": err,
        "PC": round(tp / (tp + fp), 4) if (tp + fp) else 0,
        "RC": round(tp / (tp + fn), 4) if (tp + fn) else 0,
        "ACC": round((tp + tn) / n, 4) if n else 0,
        "F1": round(2 * tp / (2 * tp + fp + fn), 4) if (2 * tp + fp + fn) else 0,
    }


# ── Report generation ───────────────────────────────────────────────────
def generate_report():
    report = {}
    for v in ["cot", "nocot"]:
        p = os.path.join(EVAL_RESULT_DIR, f"feasibility_pred_{v}.jsonl")
        if not os.path.exists(p):
            continue
        rows = read_jsonl(p)
        report[v] = binary_metrics(rows)
        for s in ["simple", "complex"]:
            srows = [r for r in rows if r.get("stratum") == s]
            if srows:
                report[f"{v}_{s}"] = binary_metrics(srows)

    if not report:
        print("No prediction files found. Run --variant cot/nocot first.")
        return

    header = f"{'Variant':<15} {'N':>4} {'PC':>8} {'RC':>8} {'ACC':>8} {'F1':>8} {'FP':>4}"
    sep = "-" * 55
    print(f"\n===== Path Feasibility Comparison =====")
    print(header)
    print(sep)
    for v in ["cot", "nocot"]:
        m = report.get(v, {})
        print(f"{v:<15} {m.get('N',0):>4} {m.get('PC',0):>8.4f} "
              f"{m.get('RC',0):>8.4f} {m.get('ACC',0):>8.4f} "
              f"{m.get('F1',0):>8.4f} {m.get('FP',0):>4}")

    for stratum in ["simple", "complex"]:
        print(f"\n  {stratum.capitalize()} cases:")
        for v in ["cot", "nocot"]:
            m = report.get(f"{v}_{stratum}", {})
            if m:
                print(f"    {v:<12} ACC={m.get('ACC',0):.4f}  "
                      f"F1={m.get('F1',0):.4f}")

    out = os.path.join(EVAL_RESULT_DIR, "feasibility_comparison.json")
    with open(out, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved: {out}")


# ── Main ─────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=["cot", "nocot"])
    ap.add_argument("--report", action="store_true",
                    help="Generate comparison report from existing results")
    ap.add_argument("--sleep", type=float, default=0.3,
                    help="Delay between LLM calls (seconds)")
    args = ap.parse_args()

    if args.report:
        generate_report()
        return

    if not args.variant:
        ap.error("Specify --variant cot|nocot or --report")

    if not os.path.exists(DATASET):
        sys.exit(f"Dataset not found: {DATASET}\n"
                 f"Run build_feasibility_dataset.py first.")

    rows = read_jsonl(DATASET)
    print(f"Running {args.variant}: {len(rows)} merge points")

    results = []
    for i, mp in enumerate(rows):
        print(f"  [{i+1}/{len(rows)}] {mp['mp_id'][:70]}")
        try:
            results.append(run_one(mp, args.variant))
        except Exception as e:
            print(f"    ERROR: {e}")
            results.append({
                "mp_id": mp["mp_id"], "variant": args.variant,
                "gt": mp["gt"], "pred_feasible": None, "error": str(e),
            })
        time.sleep(args.sleep)

    out = os.path.join(EVAL_RESULT_DIR, f"feasibility_pred_{args.variant}.jsonl")
    write_jsonl(out, results)

    m = binary_metrics(results)
    print(f"\nDone. {len(results)} predictions -> {out}")
    print(f"  ACC={m['ACC']}, F1={m['F1']}, parse_errors={m['parse_errors']}")
    print(f"  Run '--report' for full comparison after both variants.")


if __name__ == "__main__":
    main()
