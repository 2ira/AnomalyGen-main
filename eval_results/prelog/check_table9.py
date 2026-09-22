#!/usr/bin/env python3
"""Re-derive Appendix Table 9 PreLog cells from deposited stdout.

Usage (from this directory or repo root):
    python3 eval_results/prelog/check_table9.py

Reads the five hdfs_1.0_tar*.log files, takes sklearn `weighted avg`
(precision, recall, f1-score), maps them to Table 9 order
(F1=f1-score, RC=recall, PC=precision), and checks metrics.json.
No GPU. Exit 0 iff Table 9 cells match.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEIGHTED = re.compile(
    r"weighted avg\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)"
)

LOGS = {
    "R=0.0": "hdfs_1.0_tar_baseline.log",
    "R=0.001": "hdfs_1.0_tar_plus_new_aug_0.001.log",
    "R=0.01": "hdfs_1.0_tar_plus_new_aug_0.01.log",
    "R=0.1": "hdfs_1.0_tar_plus_new_aug_0.1.log",
    "R=1.0": "hdfs_1.0_tar_plus_new_aug_1.0.log",
}


def weighted_from_log(path: Path) -> tuple[float, float, float]:
    text = path.read_text()
    matches = WEIGHTED.findall(text)
    if not matches:
        raise SystemExit(f"no weighted avg line in {path.name}")
    pc, rc, f1 = (float(x) for x in matches[-1])
    return f1, rc, pc


def main() -> int:
    metrics = json.loads((HERE / "metrics.json").read_text())
    expected = metrics["derived"]["table9_F1_RC_PC"]
    print("Table 9 PreLog  (F1, RC, PC) from deposited stdout")
    print(f"{'R':<8} {'log F1/RC/PC':<28} {'metrics.json':<28} match")
    ok = True
    for key, fname in LOGS.items():
        got = list(weighted_from_log(HERE / fname))
        exp = expected[key]
        match = got == exp
        ok = ok and match
        mark = "OK" if match else "FAIL"
        print(
            f"{key:<8} {got[0]:.3f}/{got[1]:.3f}/{got[2]:.3f}"
            f"            {exp[0]:.3f}/{exp[1]:.3f}/{exp[2]:.3f}            {mark}"
        )
    base_f1 = expected["R=0.0"][0]
    print("\nFigure 7(a) ΔF1 (pp) vs R=0.0 weighted F1")
    for key, d_exp in metrics["derived"]["heatmap_delta_f1_pp"].items():
        f1 = expected[key][0]
        d = round(100 * (f1 - base_f1), 1)
        mark = "OK" if d == d_exp else "FAIL"
        ok = ok and d == d_exp
        print(f"  {key}: {d:+.1f} (metrics.json {d_exp:+.1f}) {mark}")
    if not ok:
        print("\nMISMATCH: do not copy Table 9 from metrics.json until logs agree.")
        return 1
    print("\nOK: Table 9 PreLog and heatmap deltas match eval_results/prelog/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
