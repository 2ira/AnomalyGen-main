#!/usr/bin/env python3
"""Reproduce Table 1 and Table 4 (R2.4) under one D1 convention.

Convention
  * Universe = unique production format strings with >= 2 literal tokens
    (short templates never score, so they leave both numerator and denominator).
  * A source format is covered when some corpus message contains all of its
    literal tokens in order (``coverage_stats.covered_templates``).
  * Table 1 # Observed = D1 hits of the public Drain list on that universe.
  * Table 4 AG-HDFS = D1 hits of ``output/log_events/final_logs.json``.

From the AnomalyGen-main root:

    python3 statistic/d1_long_all.py --check

Inputs live in ``statistic/x5_out/`` (source extracts + LogHub CSVs). Hadoop /
Nova / Spark trees are not required unless you re-extract (see statistic/README.md).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "statistic"))
from coverage_stats import covered_templates, load_generated, load_public, read_source_templates, skeleton  # noqa: E402

OUT = ROOT / "statistic/x5_out/d1_long_all.json"
X5 = ROOT / "statistic/x5_out"

# Frozen paper cells (long-template D1). ``d1_long_all.py --check`` asserts these.
PAPER = {
    "HDFS": {"unique_long": 2739, "d1_hits": 13, "coverage_pct": 0.47, "ag_hits": 2646, "ag_pct": 96.6, "improvement": 203.5},
    "Hadoop_Common": {"unique_long": 1344, "d1_hits": 17, "coverage_pct": 1.26},
    "OpenStack_Nova": {"unique_long": 1812, "d1_hits": 31, "coverage_pct": 1.71},
    "ZK_3.4.5": {"unique_long": 499, "d1_hits": 55, "coverage_pct": 11.02},
    "Spark": {"unique_long": 2391, "d1_hits": 16, "coverage_pct": 0.67},
    "MapReduce": {"unique_long": 874, "d1_hits": 57, "coverage_pct": 6.52},
}
POOLED = {"source_long": 9659, "observed_hits": 189, "coverage_pct": 1.96}


def long_only(templates):
    return [t for t in templates if len(skeleton(t)) >= 2]


def first_existing(*paths: Path) -> Path | None:
    for p in paths:
        if p and p.exists():
            return p
    return None


def row(name, source_path: Path | None, public_path: Path | None, generated_path: Path | None = None):
    if source_path is None:
        return {"name": name, "missing": "source"}
    _, templates = read_source_templates(str(source_path))
    long_t = long_only(templates)
    rec = {
        "name": name,
        "source_file": str(source_path),
        "unique_all": len(templates),
        "unique_long": len(long_t),
        "dropped_short": len(templates) - len(long_t),
    }
    if public_path and public_path.exists():
        msgs = load_public(str(public_path))
        cov, _ = covered_templates(msgs, long_t)
        rec["public_file"] = str(public_path)
        rec["public_list"] = len(msgs)
        rec["d1_hits"] = len(cov)
        rec["d1"] = f"{len(cov)}/{len(long_t)}"
        rec["coverage_pct"] = round(100.0 * len(cov) / len(long_t), 2) if long_t else 0.0
    if generated_path and generated_path.exists():
        gen = load_generated(str(generated_path))
        gcov, _ = covered_templates(gen, long_t)
        rec["generated_file"] = str(generated_path)
        rec["ag_hits"] = len(gcov)
        rec["ag_d1"] = f"{len(gcov)}/{len(long_t)}"
        rec["ag_pct"] = round(100.0 * len(gcov) / len(long_t), 2) if long_t else 0.0
        if rec.get("d1_hits"):
            rec["improvement"] = round(len(gcov) / rec["d1_hits"], 1)
    return rec


def check_paper(report) -> int:
    by = {r["name"]: r for r in report["rows"]}
    errors = []
    for name, exp in PAPER.items():
        got = by.get(name)
        if not got:
            errors.append(f"missing row {name}")
            continue
        for k, v in exp.items():
            if k not in got:
                errors.append(f"{name}.{k} missing (need {v})")
            elif got[k] != v:
                errors.append(f"{name}.{k}: got {got[k]} want {v}")
    pooled = report.get("pooled") or {}
    for k, v in POOLED.items():
        if pooled.get(k) != v:
            errors.append(f"pooled.{k}: got {pooled.get(k)} want {v}")
    if errors:
        print("CHECK FAIL", file=sys.stderr)
        for e in errors:
            print(" ", e, file=sys.stderr)
        return 1
    print("CHECK OK: Table 1 / Table 4 long-template D1 matches the manuscript.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="exit 1 unless numbers match the paper freeze")
    args = ap.parse_args()

    hdfs_src = first_existing(
        X5 / "hdfs_3.3.6_log_templates.txt",
        ROOT / "hadoop/hadoop-hdfs-project/log_templates.txt",
    )
    hdfs_pub = first_existing(
        X5 / "loghub/HDFS_templates.csv",
        ROOT / "dataset/HDFS/HDFS_templates.csv",
    )
    zk_pub = first_existing(
        X5 / "loghub/Zookeeper.log_templates.csv",
        ROOT / "dataset/Zookeeper/Zookeeper.log_templates.csv",
    )
    ag = first_existing(ROOT / "output/log_events/final_logs.json")

    rows = [
        row("HDFS", hdfs_src, hdfs_pub, ag),
        row("Hadoop_Common", X5 / "hadoop_common_log_templates.txt", X5 / "loghub/Hadoop_2k.log_templates.csv"),
        row("OpenStack_Nova", X5 / "nova_13.1.4_log_templates.txt", X5 / "loghub/OpenStack_2k.log_templates.csv"),
        row("ZK_3.4.5", X5 / "zk_3.4.5_main_log_templates.txt", zk_pub),
        row("Spark", X5 / "spark_2.4.8_log_templates.txt", X5 / "loghub/Spark_2k.log_templates.csv"),
        row("MapReduce", X5 / "mapreduce_log_templates.txt", X5 / "loghub/Hadoop_2k.log_templates.csv"),
    ]
    report = {
        "convention": "D1 min_tokens=2 on both numerator (hits among long templates) and denominator",
        "rows": rows,
    }
    with_d1 = [r for r in rows if "d1_hits" in r]
    if with_d1:
        src = sum(r["unique_long"] for r in with_d1)
        obs = sum(r["d1_hits"] for r in with_d1)
        report["pooled"] = {
            "source_long": src,
            "observed_hits": obs,
            "coverage_pct": round(100.0 * obs / src, 2) if src else 0.0,
            "mean_source": round(src / len(with_d1)),
            "mean_observed": round(obs / len(with_d1)),
        }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if args.check:
        sys.exit(check_paper(report))


if __name__ == "__main__":
    main()
