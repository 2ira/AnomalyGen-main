#!/usr/bin/env python3
"""Coverage after dropping short templates, with the same Drain on both sides.

Protocol (fixed, reproducible):
  Denominator
    1. Unique production format strings from
       hadoop/hadoop-hdfs-project/log_templates.txt (src/main, tests dropped).
    2. Drop short templates: D1 skeleton has <2 non-numeric tokens
       (same rule as coverage_stats.min_tokens=2).
    3. Drain-cluster the remaining strings. |T| = number of unique Drain
       token-sequences. That is the denominator.

  Numerator (existing, fully reproducible logs only)
    * AG: output/log_events/final_logs.json  (archived paper dump)
    * LogHub: dataset/HDFS/HDFS_templates.csv EventTemplate
    Drain uses the identical (st, depth, rex) as the denominator.
    A source cluster is covered iff its Drain token-sequence equals one
    obtained from the corpus (independent overlap), or iff joint lookup
    of the source string against a Drain tree fitted on the corpus hits.

  Drain presets (both from this repo, not a sweep):
    * pipeline: main/label_anomaly.py  st=0.5 depth=2
    * paper:    statistic/log_parser.py st=0.4 depth=1
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "statistic"))
from coverage_stats import covered_templates, load_generated, load_public, skeleton  # noqa: E402
from drain_same_config_coverage import read_source, strip_level  # noqa: E402
from drain_sweep import Drain, REX  # noqa: E402

OUT = ROOT / "statistic/x5_out/drain_long_coverage.json"
GOLD = ROOT / "hadoop/hadoop-hdfs-project/log_templates.txt"
AG = ROOT / "output/log_events/final_logs.json"
LOGHUB = ROOT / "dataset/HDFS/HDFS_templates.csv"

PH = re.compile(
    r"\{\}|\{[0-9]+\}|\{[A-Za-z_][\w.]*\}|<\*>|%[0-9]*[sdxfoeEgG]|\$\{[^}]*\}"
)


def unify(s: str) -> str:
    s = strip_level(s)
    return PH.sub("<*>", s)


def long_source():
    raw = read_source()
    long, short = [], []
    for t in raw:
        if len(skeleton(t)) >= 2:
            long.append(t)
        else:
            short.append(t)
    return raw, long, short


def drain_of(msgs, st, depth, rex_name):
    d = Drain(st=st, depth=depth, rex=list(REX[rex_name]))
    for m in msgs:
        d.add(unify(m))
    return d


def keys(d: Drain):
    return {tuple(t) for t in d.templates}


def joint_hit(d_fit: Drain, strings) -> int:
    hit = 0
    for s in strings:
        seq = d_fit._preprocess(unify(s))
        if not seq:
            seq = ["<*>"]
        if d_fit._search(seq) is not None:
            hit += 1
    return hit


def run_preset(name, st, depth, rex_name, long_src, ag, pub):
    d_src = drain_of(long_src, st, depth, rex_name)
    d_ag = drain_of(ag, st, depth, rex_name)
    d_pub = drain_of(pub, st, depth, rex_name)
    S, A, P = keys(d_src), keys(d_ag), keys(d_pub)
    inter_ag = S & A
    inter_pub = S & P
    j_ag = joint_hit(d_ag, long_src)
    j_pub = joint_hit(d_pub, long_src)
    return {
        "preset": name,
        "st": st,
        "depth": depth,
        "rex": rex_name,
        "denom_drain_clusters": len(S),
        "ag_drain_clusters": len(A),
        "loghub_drain_clusters": len(P),
        "overlap_ag": len(inter_ag),
        "overlap_ag_cov": round(len(inter_ag) / len(S), 4) if S else None,
        "overlap_loghub": len(inter_pub),
        "overlap_loghub_cov": round(len(inter_pub) / len(S), 4) if S else None,
        "joint_ag": j_ag,
        "joint_ag_cov": round(j_ag / len(long_src), 4),
        "joint_loghub": j_pub,
        "joint_loghub_cov": round(j_pub / len(long_src), 4),
        "improvement_overlap": round(len(inter_ag) / len(inter_pub), 1) if inter_pub else None,
        "improvement_joint": round(j_ag / j_pub, 1) if j_pub else None,
    }


def main():
    raw, long_src, short = long_source()
    ag = load_generated(str(AG))
    pub = load_public(str(LOGHUB)) if LOGHUB.exists() else []
    d1_ag, usable = covered_templates(ag, long_src, min_tokens=2)
    d1_pub, _ = covered_templates(pub, long_src, min_tokens=2)

    presets = [
        ("pipeline label_anomaly.py", 0.5, 2, "label_anomaly"),
        ("paper log_parser.py", 0.4, 1, "log_parser"),
    ]
    drain_rows = [run_preset(n, st, d, rex, long_src, ag, pub) for n, st, d, rex in presets]

    summary = {
        "protocol": {
            "denominator": (
                "unique production format strings in log_templates.txt "
                "(src/main, tests dropped), then drop D1-short (<2 literal tokens), "
                "then unique Drain clusters under the named preset"
            ),
            "numerator_logs": (
                "AG = output/log_events/final_logs.json (archived, reproducible); "
                "LogHub = dataset/HDFS/HDFS_templates.csv EventTemplate. "
                "No remaining_source instantiate, no unreached merge sidecar."
            ),
            "short_filter": "same skeleton() as coverage_stats.min_tokens=2",
            "placeholder_unify": "{} / {n} / <*> / %s → <*> on both sides before Drain",
        },
        "raw_unique_source": len(raw),
        "short_dropped": len(short),
        "long_source": len(long_src),
        "ag_messages": len(ag),
        "loghub_templates": len(pub),
        "d1_on_long_only": {
            "note": "same matcher both sides; denominator = long source strings, not Drain clusters",
            "universe": len(usable),
            "ag_hit": len(d1_ag),
            "ag_cov": f"{len(d1_ag)}/{len(usable)} = {100.0*len(d1_ag)/len(usable):.2f}%",
            "loghub_hit": len(d1_pub),
            "loghub_cov": f"{len(d1_pub)}/{len(usable)} = {100.0*len(d1_pub)/len(usable):.2f}%",
            "improvement": round(len(d1_ag) / len(d1_pub), 1) if d1_pub else None,
        },
        "drain": drain_rows,
    }
    OUT.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
