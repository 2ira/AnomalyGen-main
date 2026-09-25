#!/usr/bin/env python3
"""Reproduce Table 1 source-universe sizes under the same D1 convention as HDFS/ZK."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "statistic"))
from coverage_stats import covered_templates, load_public, read_source_templates, skeleton  # noqa: E402

OUT = ROOT / "statistic/x5_out/table1_reproduce.json"

ROWS = {
    "HDFS": ROOT / "hadoop/hadoop-hdfs-project/log_templates.txt",
    "ZK_3.4.5": ROOT / "statistic/x5_out/zk_3.4.5_main_log_templates.txt",
    "Hadoop_Common": ROOT / "statistic/x5_out/hadoop_common_log_templates.txt",
    "MapReduce": ROOT / "statistic/x5_out/mapreduce_log_templates.txt",
}
PUBLIC = {
    "HDFS": ROOT / "dataset/HDFS/HDFS_templates.csv",
    "ZK_3.4.5": ROOT / "dataset/Zookeeper/Zookeeper.log_templates.csv",
}
PAPER = {
    "HDFS": {"source": 2886, "observed": 13, "coverage": "0.45%"},
    "Hadoop_Common": {"source": 15223, "observed": 248, "coverage": "1.62%"},
    "OpenStack_Nova": {"source": 2060, "observed": 59, "coverage": "2.86%"},
    "ZK_3.4.5": {"source": 534, "observed": 55, "coverage": "10.30%"},
    "Spark": {"source": 1749, "observed": 200, "coverage": "11.44%"},
    "MapReduce": {"source": 1564, "observed": 200, "coverage": "12.79%"},
}


def unique_long(templates):
    return [t for t in templates if len(skeleton(t)) >= 2]


def main():
    report = {"rows": {}, "recommendation": None}
    for name, path in ROWS.items():
        row = {"path": str(path), "exists": path.exists()}
        if path.exists():
            stmts, templates = read_source_templates(str(path))
            long_t = unique_long(templates)
            row.update(
                {
                    "logging_stmts": len(stmts),
                    "unique_formats": len(templates),
                    "unique_long_min_tokens_2": len(long_t),
                }
            )
            pub = PUBLIC.get(name)
            if pub and pub.exists():
                msgs = load_public(str(pub))
                cov, usable = covered_templates(msgs, templates)
                row["public_templates"] = len(msgs)
                row["d1_hits"] = len(cov)
                row["d1_universe"] = len(templates)
                row["d1_coverage"] = f"{100.0 * len(cov) / len(templates):.2f}%"
                cov_l, _ = covered_templates(msgs, long_t)
                row["d1_long"] = f"{len(cov_l)}/{len(long_t)}"
        row["paper"] = PAPER.get(name)
        report["rows"][name] = row
    report["missing"] = {
        "OpenStack_Nova": "no Nova tree; no LogHub Drain CSV in artifact; Java extractor does not apply",
        "Spark": "no Spark tree; Scala Logger extractor missing; no Drain CSV",
        "Hadoop_Common_observed_248": "no LogHub Hadoop Drain CSV on disk (third-party list was 349, not 248)",
        "MapReduce_observed_200": "no LogHub MapReduce Drain CSV on disk",
    }
    report["recommendation"] = (
        "Unify Java rows (HDFS, ZK, Hadoop Common, MapReduce) to unique production "
        "format strings + D1. Keep OpenStack/Spark as captioned original lexical "
        "counts, or drop them: they cannot be D1-reproduced from this artifact. "
        "Do not mix 15,223 lexical-whole-Hadoop with HDFS 2,886 unique formats."
    )
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
