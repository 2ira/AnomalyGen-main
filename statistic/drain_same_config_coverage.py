#!/usr/bin/env python3
"""Same-config Drain on source templates AND AG logs, then coverage.

Universe = unique Drain clusters of production source format strings.
A source cluster is covered when an AG message is assigned to it
(joint Drain: fit on AG, lookup source; also independent template overlap).
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from drain_sweep import Drain, REX  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "hadoop/hadoop-hdfs-project/log_templates.txt"
JAVA_PH = [
    r"\{\}",
    r"\{[0-9]+\}",
    r"%[0-9]*[sdxfoeEgG]",
    r"\$\{[^}]*\}",
    r"\{\w+\}",
]
LEVEL = re.compile(r"^\s*\[?(trace|debug|info|warn|warning|error|fatal)\]?\s*:?\s*", re.I)


def strip_level(s: str) -> str:
    return LEVEL.sub("", s)


def read_source():
    line_re = re.compile(r"^([^:]*\.java):\s?(.*)$")
    out = []
    for line in GOLD.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        m = line_re.match(line)
        if m:
            path, text = m.group(1), m.group(2)
            if "src/test" in path or "/test/" in path:
                continue
        else:
            text = line
        if text.strip():
            out.append(text)
    # unique
    return sorted(set(out))


def load_ag():
    data = json.loads((ROOT / "output/log_events/final_logs.json").read_text())
    msgs = []
    for v in data.values():
        if isinstance(v, dict) and v.get("log"):
            msgs.append(strip_level(v["log"]))
    return msgs


def load_loghub():
    path = ROOT / "dataset/HDFS/HDFS_templates.csv"
    with path.open() as f:
        return [r["EventTemplate"] for r in csv.DictReader(f) if r.get("EventTemplate")]


def make_drain(st, depth, rex_name, extra_java=True):
    rex = list(REX[rex_name])
    if extra_java:
        rex = JAVA_PH + rex
    return Drain(st=st, depth=depth, rex=rex)


def tmpl_key(seq):
    return tuple(seq)


def run_cfg(name, st, depth, rex_name, src, ag, pub, extra_java=True):
    print(f"\n=== {name}  st={st} depth={depth} rex={rex_name} java_ph={extra_java} ===", flush=True)

    # independent: Drain source only, Drain AG only
    d_src = make_drain(st, depth, rex_name, extra_java)
    for s in src:
        d_src.add(s)
    d_ag = make_drain(st, depth, rex_name, extra_java)
    for m in ag:
        d_ag.add(m)
    S = {tmpl_key(t) for t in d_src.templates}
    A = {tmpl_key(t) for t in d_ag.templates}
    inter = S & A
    print(f"  independent unique  source={len(S)}  AG={len(A)}  exact_overlap={len(inter)}  "
          f"cov={len(inter)/len(S):.4f} ({len(inter)}/{len(S)})", flush=True)

    # joint: fit on AG, lookup source without inserting
    d_j = make_drain(st, depth, rex_name, extra_java)
    for m in ag:
        d_j.add(m)
    hit = 0
    for s in src:
        seq = d_j._preprocess(s)
        if not seq:
            seq = ["<*>"]
        if d_j._search(seq) is not None:
            hit += 1
    print(f"  joint lookup (fit AG, match source stmts)  {hit}/{len(src)} = {hit/len(src):.4f}", flush=True)

    # joint on unique source Drain templates: cover if lookup hits
    hit_u = 0
    for t in S:
        seq = list(t)
        if d_j._search(seq) is not None:
            hit_u += 1
    print(f"  joint lookup (source Drain clusters vs AG tree)  {hit_u}/{len(S)} = {hit_u/len(S):.4f}", flush=True)

    # public LogHub through the same Drain, lookup on AG tree
    d_pub = make_drain(st, depth, rex_name, extra_java)
    for p in pub:
        d_pub.add(p)
    P = {tmpl_key(t) for t in d_pub.templates}
    pub_hit = 0
    for p in pub:
        seq = d_j._preprocess(p)
        if not seq:
            seq = ["<*>"]
        if d_j._search(seq) is not None:
            pub_hit += 1
    pub_exact = len(P & A)
    print(f"  LogHub independent unique={len(P)} exact_vs_AG={pub_exact}  "
          f"joint lookup {pub_hit}/{len(pub)}", flush=True)

    # improvement: source-covered / loghub-covered using joint lookup
    if pub_hit:
        print(f"  improvement joint  {hit}/{pub_hit} = {hit/pub_hit:.1f}x", flush=True)
    return {
        "src_drain": len(S),
        "ag_drain": len(A),
        "exact": len(inter),
        "exact_cov": len(inter) / len(S),
        "joint_stmt": hit,
        "joint_stmt_cov": hit / len(src),
        "joint_cluster": hit_u,
        "joint_cluster_cov": hit_u / len(S),
        "pub_drain": len(P),
        "pub_joint": pub_hit,
    }


def main():
    src = read_source()
    ag = load_ag()
    pub = load_loghub()
    print(f"raw unique source={len(src)} AG msgs={len(ag)} LogHub templates={len(pub)}", flush=True)

    cfgs = [
        ("production label_anomaly", 0.5, 2, "label_anomaly", True),
        ("production label_anomaly no extra java_ph", 0.5, 2, "label_anomaly", False),
        ("log_parser.py", 0.4, 1, "log_parser", True),
        ("log_parser + label rex", 0.5, 2, "log_parser", True),
        ("zk-style st0.5 d4", 0.5, 4, "zk", True),
        ("digits only st0.5 d2", 0.5, 2, "digits", True),
        ("ip_digits st0.5 d2", 0.5, 2, "ip_digits", True),
        ("hdfs_common st0.5 d2", 0.5, 2, "hdfs_common", True),
        ("label_anomaly st0.4 d2", 0.4, 2, "label_anomaly", True),
        ("label_anomaly st0.6 d2", 0.6, 2, "label_anomaly", True),
        ("label_anomaly st0.5 d4", 0.5, 4, "label_anomaly", True),
        ("none+java_ph st0.5 d2", 0.5, 2, "none", True),
    ]
    best = None
    for name, st, depth, rex, java in cfgs:
        r = run_cfg(name, st, depth, rex, src, ag, pub, java)
        score = (r["joint_stmt_cov"], r["exact_cov"])
        if best is None or score > best[0]:
            best = (score, name, r)
    print("\n=== highest joint-stmt coverage ===")
    print(best[1], {k: (round(v, 4) if isinstance(v, float) else v) for k, v in best[2].items()})


if __name__ == "__main__":
    main()
