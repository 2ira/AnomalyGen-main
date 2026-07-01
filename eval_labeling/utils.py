"""
Shared utilities for label-accuracy evaluation (eval_labeling).

Provides: session loading, confusion-matrix computation, Wilson CI,
error classification, and result serialization — used by both
hdfs_recovery_relabel.py and zk_recovery_relabel.py.
"""
import os
import re
import csv
import json
import math
from collections import OrderedDict, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
RESULT_DIR = os.path.join(HERE, "eval_results")


# ── Data loading ─────────────────────────────────────────────────────────
def load_sessions(csv_path):
    """Read a parsed-logs CSV and group rows by BlockId into sessions."""
    sessions = OrderedDict()
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            bid = row["BlockId"]
            sessions.setdefault(bid, []).append({
                "level": (row.get("Level") or "").strip().strip("[]").upper(),
                "content": row.get("Content") or "",
            })
    return sessions


def session_text(lines):
    """Concatenate all content lines in a session."""
    return " || ".join(l["content"] for l in lines)


def has_error_level(lines):
    return any(l["level"] == "ERROR" for l in lines)


def any_match(patterns, text):
    """Return True if any regex pattern matches *text*."""
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


# ── Metrics ──────────────────────────────────────────────────────────────
def wilson_ci(k, n, z=1.96):
    """Wilson score 95 % confidence interval for accuracy k/n."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z ** 2 / n
    center = (p + z ** 2 / (2 * n)) / d
    margin = (z * math.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2))) / d
    return round(center - margin, 4), round(center + margin, 4)


def confusion_matrix(rows, pred_key):
    """Compute TP/FP/FN/TN/ACC/PC/RC/F1 from a list of dicts."""
    tp = sum(1 for r in rows if r["gt"] == "anomaly" and r[pred_key] == "anomaly")
    fp = sum(1 for r in rows if r["gt"] == "normal" and r[pred_key] == "anomaly")
    fn = sum(1 for r in rows if r["gt"] == "anomaly" and r[pred_key] == "normal")
    tn = sum(1 for r in rows if r["gt"] == "normal" and r[pred_key] == "normal")
    n = len(rows)
    acc = (tp + tn) / n if n else 0.0
    pc = tp / (tp + fp) if (tp + fp) else 0.0
    rc = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * pc * rc / (pc + rc) if (pc + rc) else 0.0
    ci = wilson_ci(tp + tn, n)
    return {
        "n": n, "TP": tp, "FP": fp, "FN": fn, "TN": tn,
        "accuracy": round(acc, 4),
        "PC": round(pc, 4), "RC": round(rc, 4), "F1": round(f1, 4),
        "ci_95": ci,
    }


# ── Error classification ────────────────────────────────────────────────
def classify_error(pred, gt, lines, *, recovery_check=None):
    """
    Classify a mislabelled session into one of:
      kw_miss      — anomaly missed because no ERROR/keyword
      structural   — anomaly missed despite keyword presence (structural)
      recovery_fp  — normal misclassified as anomaly (benign recovery)
      other_fp     — normal misclassified as anomaly (other)
    Returns None when pred == gt.
    """
    if pred == gt:
        return None
    text = session_text(lines)
    _EXPLICIT = re.compile(r"Exception|\b(ERROR|FATAL)\b")
    _IMPLICIT = re.compile(
        r"\b(fail|cannot|invalid|failed)\b|error_code\s*=\s*\d+", re.IGNORECASE)
    if gt == "normal" and pred == "anomaly":
        if recovery_check and recovery_check(lines):
            return "recovery_fp"
        return "other_fp"
    if gt == "anomaly" and pred == "normal":
        if not (_EXPLICIT.search(text) or _IMPLICIT.search(text)
                or has_error_level(lines)):
            return "kw_miss"
        return "structural"
    return "other"


# ── Result serialization ────────────────────────────────────────────────
def run_comparison(sessions, gt_fn, recovery_fn, gt_rationale, *,
                   recovery_check=None, system_name=""):
    """
    Core evaluation loop shared by all per-system scripts.

    Parameters
    ----------
    sessions : OrderedDict[str, list]
    gt_fn : callable(bid, lines) -> "normal"|"anomaly"
    recovery_fn : callable(lines) -> "normal"|"anomaly"
    gt_rationale : dict
    recovery_check : optional callable(lines) -> bool
    system_name : str  (for display only)

    Returns (rows, result_dict)
    """
    from collections import defaultdict

    def level_heuristic(lines):
        return "anomaly" if has_error_level(lines) else "normal"

    rows = []
    for bid, lines in sessions.items():
        rows.append({
            "block_id": bid,
            "n_lines": len(lines),
            "baseline": level_heuristic(lines),
            "recovery_aware": recovery_fn(lines),
            "gt": gt_fn(bid, lines),
            "rationale": gt_rationale.get(bid, ("", ""))[1],
        })

    base_cm = confusion_matrix(rows, "baseline")
    rec_cm = confusion_matrix(rows, "recovery_aware")

    miscls = {"baseline": defaultdict(list), "recovery_aware": defaultdict(list)}
    for r in rows:
        for key in ("baseline", "recovery_aware"):
            cat = classify_error(r[key], r["gt"], sessions[r["block_id"]],
                                 recovery_check=recovery_check)
            if cat:
                miscls[key][cat].append(r["block_id"])

    cnt = lambda d: {k: len(v) for k, v in d.items()}
    flipped = [r["block_id"] for r in rows
               if r["baseline"] != r["recovery_aware"]]
    fixed = [r["block_id"] for r in rows
             if r["baseline"] != r["gt"] and r["recovery_aware"] == r["gt"]]
    broke = [r["block_id"] for r in rows
             if r["baseline"] == r["gt"] and r["recovery_aware"] != r["gt"]]

    gt_dist = {
        "anomaly": sum(1 for r in rows if r["gt"] == "anomaly"),
        "normal": sum(1 for r in rows if r["gt"] == "normal"),
    }

    result = {
        "system": system_name,
        "n_sessions": len(rows),
        "gt_distribution": gt_dist,
        "baseline_level_heuristic": base_cm,
        "recovery_aware": rec_cm,
        "accuracy_gain": round(rec_cm["accuracy"] - base_cm["accuracy"], 4),
        "miscls_baseline": cnt(miscls["baseline"]),
        "miscls_recovery_aware": cnt(miscls["recovery_aware"]),
        "newly_correct": fixed,
        "newly_wrong": broke,
    }
    return rows, result


def save_results(rows, result, prefix, *, gt_rationale=None):
    """Write JSON + CSV to RESULT_DIR."""
    os.makedirs(RESULT_DIR, exist_ok=True)

    if gt_rationale:
        result["rationale_cases"] = {
            bid: gt_rationale[bid] for bid in gt_rationale
        }

    out_json = os.path.join(RESULT_DIR, f"{prefix}.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    out_csv = os.path.join(RESULT_DIR, f"{prefix}.csv")
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["block_id", "n_lines", "baseline",
                    "recovery_aware", "gt", "rationale"])
        for r in rows:
            w.writerow([r["block_id"], r["n_lines"],
                        r["baseline"], r["recovery_aware"],
                        r["gt"], r["rationale"]])
    return out_json, out_csv


def print_summary(result):
    """Print a human-readable comparison to stdout."""
    base = result["baseline_level_heuristic"]
    rec = result["recovery_aware"]
    gt = result["gt_distribution"]
    sys = result.get("system", "")

    print(f"\n{'=' * 50}")
    print(f"  {sys} Label Accuracy Comparison")
    print(f"{'=' * 50}")
    print(f"  GT: anomaly={gt['anomaly']}  normal={gt['normal']}")
    print(f"\n  baseline  ACC={base['accuracy']}  PC={base['PC']}  "
          f"RC={base['RC']}  F1={base['F1']}  95%CI={base['ci_95']}")
    print(f"  recovery  ACC={rec['accuracy']}  PC={rec['PC']}  "
          f"RC={rec['RC']}  F1={rec['F1']}  95%CI={rec['ci_95']}")
    gain = result['accuracy_gain']
    print(f"\n  Gain: {'+' if gain >= 0 else ''}{gain}")
    print(f"  Fixed: {result['newly_correct']}")
    print(f"  Broke: {result['newly_wrong']}")
