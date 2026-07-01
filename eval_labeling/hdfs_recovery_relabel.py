#!/usr/bin/env python3
"""
HDFS label-accuracy experiment: baseline vs recovery-aware relabelling.

Compares two labelling rules on 106 HDFS synthesised sessions against an
independent semantic ground truth (M.2 / R1.2).

Usage:
    cd AnomalyGen-main
    python eval_labeling/hdfs_recovery_relabel.py [--csv <path>]
"""
import os
import re
import argparse

from utils import (
    load_sessions, session_text, has_error_level, any_match,
    run_comparison, save_results, print_summary,
)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
DEFAULT_CSV = os.path.join(
    REPO_ROOT, "output_v1", "ablation", "baseline", "parsed_logs",
    "hdfs_combined_parsed_logs.csv")

# ── HDFS recovery / fatal signals ────────────────────────────────────────
_RECOVERY_SIGNALS = [
    r"successfully converted to complete",
    r"operation completed successfully",
    r"completed successfully",
    r"resetting internal error state",
    r"proceeding without wait(ing)?",
    r"restart completed successfully",
    r"error recovery for block",
    r"\bignor(e|ing|ed)\b",
    r"\bhandled\b",
    r"no operation performed",
    r"cannot be marked as corrupt",
    r"addtoinvalidates",
    r"invalidateblock",
]

_FATAL_SIGNALS = [
    r"already retried \d+ times",
    r"pipeline setup failed",
    r"did not restart within",
    r"illegal state exception",
    r"failed to transfer block",
    r"aborting",
    r"access denied",
    r"cannot find fsvolumespi",
]

_EXPLICIT = re.compile(r"Exception|\b(ERROR|FATAL)\b")
_IMPLICIT = re.compile(
    r"\b(fail|cannot|invalid|failed)\b|error_code\s*=\s*\d+", re.IGNORECASE)


# ── Recovery-aware labelling rule ────────────────────────────────────────
def is_benign_recovery(lines):
    text = session_text(lines)
    return any_match(_RECOVERY_SIGNALS, text) and not any_match(_FATAL_SIGNALS, text)


def recovery_aware_label(lines):
    text = session_text(lines)
    suspect = (has_error_level(lines) or bool(_EXPLICIT.search(text))
               or bool(_IMPLICIT.search(text)))
    if not suspect:
        return "normal"
    if any_match(_FATAL_SIGNALS, text):
        return "anomaly"
    if is_benign_recovery(lines):
        return "normal"
    return "anomaly"


# ── Semantic ground truth (independent of evaluated rules) ───────────────
GT_RATIONALE = {
    "d51b1764_1": ("normal",
        "Two ERROR 'Cannot complete block' followed by 'Block successfully "
        "converted to complete' -- error recovered, benign recovery"),
    "ceb06c8d_1": ("anomaly",
        "'Already retried 5 times' + 'Pipeline setup failed due to missing "
        "nodes' -- retries exhausted, true anomaly (baseline misses it: no ERROR level)"),
    "83761ad5_1": ("anomaly",
        "'Datanode did not restart within 30000 ms' + ERROR 'Illegal state "
        "exception' -- restart timeout, fatal"),
    "b9f75a67_1": ("anomaly",
        "WARN 'Failed to transfer block, IOException' + 'Cannot find "
        "FsVolumeSpi' -- transfer failed without recovery (baseline misses: no ERROR level)"),
    "3a4fb26e_1": ("anomaly",
        "WARN 'Could not get block locations ... Aborting' -- explicit abort, true failure"),
    "44a0857e_1": ("anomaly",
        "WARN 'Cannot find FsVolumeSpi to report bad block' -- bad block unreportable"),
    "dcde8ff6_1": ("anomaly",
        "'Can't send invalid block' + 'Error report sent' + WARN 'Cannot find "
        "FsVolumeSpi' -- bad block not recovered"),
    "33220b2e_1": ("anomaly",
        "'Thread interrupted, InterruptedException' -- no subsequent recovery, true anomaly"),
    "e262ffb3_1": ("normal",
        "Block does not belong to any file so cannot be marked corrupt; "
        "followed by normal addToInvalidates/invalidateBlock -- routine block invalidation"),
    "cb32ad64_1": ("normal",
        "Corrupt replica reported + addToInvalidates routine -- no unrecovered failure, normal"),
}


def semantic_gt(bid, lines):
    if bid in GT_RATIONALE:
        return GT_RATIONALE[bid][0]
    text = session_text(lines)
    if re.search(r"access denied", text, re.IGNORECASE):
        return "anomaly"
    return "normal"


# ── Main ─────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=DEFAULT_CSV)
    args = ap.parse_args()

    sessions = load_sessions(args.csv)
    print(f"Loaded {len(sessions)} sessions from {args.csv}")

    rows, result = run_comparison(
        sessions, semantic_gt, recovery_aware_label, GT_RATIONALE,
        recovery_check=is_benign_recovery, system_name="HDFS")

    result["csv"] = os.path.relpath(args.csv, REPO_ROOT)
    out_json, out_csv = save_results(
        rows, result, "hdfs_recovery_relabel", gt_rationale=GT_RATIONALE)
    print_summary(result)
    print(f"\nSaved: {out_json}\n       {out_csv}")


if __name__ == "__main__":
    main()
