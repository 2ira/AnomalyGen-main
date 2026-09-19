"""
Step 6: Aggregate metrics from Experiment A (path feasibility) and Experiment B
(parameter quality).  Outputs metrics.json and CSVs that can be directly used in
the paper and cover letter (R1.3).
"""
import os
import json
import csv

import common as C


# --------------------------------------------------------------------------
# Experiment A: binary classification metrics.  Positive class = "valid" (feasible path)
# --------------------------------------------------------------------------
def binary_metrics(pred_rows):
    tp = fp = tn = fn = 0
    parse_fail = 0
    for r in pred_rows:
        gt = r.get("gt")
        pred = r.get("pred_feasible")
        if gt is None:
            continue  # unlabelled
        if pred is None:
            parse_fail += 1
            continue
        gt_pos = (gt == "valid")
        if gt_pos and pred:
            tp += 1
        elif gt_pos and not pred:
            fn += 1
        elif (not gt_pos) and pred:
            fp += 1      # Infeasible but retained: structurally connected yet logically impossible
        else:
            tn += 1
    n = tp + fp + tn + fn
    pc = tp / (tp + fp) if (tp + fp) else 0.0
    rc = tp / (tp + fn) if (tp + fn) else 0.0
    acc = (tp + tn) / n if n else 0.0
    f1 = 2 * pc * rc / (pc + rc) if (pc + rc) else 0.0
    return {
        "N": n, "TP": tp, "FP": fp, "TN": tn, "FN": fn,
        "parse_fail": parse_fail,
        "PC": round(pc, 4), "RC": round(rc, 4),
        "ACC": round(acc, 4), "F1": round(f1, 4),
    }


def load_pred(variant):
    path = os.path.join(C.EVAL_RESULT_DIR, f"feasibility_pred_{variant}.jsonl")
    return C.read_jsonl(path) if os.path.exists(path) else []


# --------------------------------------------------------------------------
# Experiment B: parameter quality accuracy
# --------------------------------------------------------------------------
def param_metrics():
    path = os.path.join(C.EVAL_DATA_DIR, "param_scored.jsonl")
    if not os.path.exists(path):
        return None
    rows = C.read_jsonl(path)
    tv_total = tv_ok = 0
    cc_total = cc_ok = 0
    joint_total = joint_ok = 0
    slot_mismatch = 0          # Template slot count != filled param count (slot-param alignment error)
    # Type-validity breakdown by semantic slot type
    by_type = {}               # slot_type -> {"n":, "ok":}
    for r in rows:
        tv, cc = r.get("type_valid"), r.get("ctx_consistent")
        if r.get("slot_count_mismatch"):
            slot_mismatch += 1
        if tv is not None:
            tv_total += 1
            tv_ok += int(bool(tv))
            st = r.get("slot_type", "unknown")
            d = by_type.setdefault(st, {"n": 0, "ok": 0})
            d["n"] += 1
            d["ok"] += int(bool(tv))
        if cc is not None:
            cc_total += 1
            cc_ok += int(bool(cc))
        if tv is not None and cc is not None:
            joint_total += 1
            joint_ok += int(bool(tv) and bool(cc))
    by_type_out = {
        st: {"n": d["n"], "ok": d["ok"],
             "acc": round(d["ok"] / d["n"], 4) if d["n"] else None}
        for st, d in sorted(by_type.items(), key=lambda kv: -kv[1]["n"])
    }
    return {
        "type_validity_acc": round(tv_ok / tv_total, 4) if tv_total else None,
        "type_validity_n": tv_total,
        "ctx_consistency_acc": round(cc_ok / cc_total, 4) if cc_total else None,
        "ctx_consistency_n": cc_total,
        "joint_acc": round(joint_ok / joint_total, 4) if joint_total else None,
        "joint_n": joint_total,
        "slot_count_mismatch": slot_mismatch,
        "total_param_slots": len(rows),
        "type_validity_by_slot_type": by_type_out,
    }


def main():
    C.ensure_dirs()
    result = {"experiment_A_path_feasibility": {}, "experiment_B_param_quality": {}}

    for variant in ("cot", "nocot"):
        rows = load_pred(variant)
        if rows:
            result["experiment_A_path_feasibility"][variant] = binary_metrics(rows)

    pm = param_metrics()
    if pm:
        result["experiment_B_param_quality"] = pm

    out_json = os.path.join(C.EVAL_RESULT_DIR, "metrics.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # Experiment A CSV (directly usable in paper tables)
    a = result["experiment_A_path_feasibility"]
    if a:
        csv_path = os.path.join(C.EVAL_RESULT_DIR, "feasibility_metrics.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Variant", "N", "PC", "RC", "ACC", "F1", "FP", "FN", "parse_fail"])
            for variant, m in a.items():
                label = "AnomalyGen (w/ CoT)" if variant == "cot" else "Baseline (w/o CoT)"
                w.writerow([label, m["N"], m["PC"], m["RC"], m["ACC"],
                            m["F1"], m["FP"], m["FN"], m["parse_fail"]])
        print(f"wrote {csv_path}")

    # Experiment B parameter validation: breakdown by semantic slot type
    pm = result["experiment_B_param_quality"]
    if pm and pm.get("type_validity_by_slot_type"):
        csv_path = os.path.join(C.EVAL_RESULT_DIR, "param_quality_by_type.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["SlotType", "N(decidable)", "Valid", "TypeValidity"])
            for st, d in pm["type_validity_by_slot_type"].items():
                w.writerow([st, d["n"], d["ok"], d["acc"]])
            w.writerow([])
            w.writerow(["OVERALL type_validity", pm["type_validity_n"],
                        "", pm["type_validity_acc"]])
            w.writerow(["OVERALL ctx_consistency", pm["ctx_consistency_n"],
                        "", pm["ctx_consistency_acc"]])
            w.writerow(["slot_count_mismatch (param↔slot)", pm["slot_count_mismatch"],
                        "", round(pm["slot_count_mismatch"] / pm["total_param_slots"], 4)
                        if pm["total_param_slots"] else None])
        print(f"wrote {csv_path}")

    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\nmetrics -> {out_json}")


if __name__ == "__main__":
    main()
