#!/usr/bin/env python3
"""Sweep Drain (st, depth, rex) to hunt the unpublished paper template counts.

Paper targets: HDFS observed 48; AG events 2874; ZK observed 80;
Table 4 denominator 2889. Production Drain in this repo is
main/label_anomaly.py (st=0.5, depth=2) and statistic/log_parser.py (st=0.4, depth=1).
"""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = (48, 80, 2874, 2889, 30, 31, 77)


class Node:
    __slots__ = ("child", "clusters")

    def __init__(self):
        self.child = {}
        self.clusters = []


def seq_sim(tmpl, seq):
    if not seq:
        return 0.0, 0
    same = 0
    stars = 0
    for a, b in zip(tmpl, seq):
        if a == b:
            same += 1
        if a == "<*>":
            stars += 1
    return same / len(seq), stars


class Drain:
    """logparser.Drain-compatible: internal depth = depth - 2."""

    def __init__(self, st=0.5, depth=4, max_child=100, rex=None):
        self.st = st
        self.depth = max(depth - 2, 0)
        self.max_child = max_child
        self.rex = [re.compile(p) for p in (rex or [])]
        self.root = Node()
        self.templates = []

    def _preprocess(self, msg: str) -> list[str]:
        text = msg
        for rgx in self.rex:
            text = rgx.sub("<*>", text)
        return [t for t in text.split() if t]

    def add(self, msg: str) -> int:
        seq = self._preprocess(msg)
        if not seq:
            seq = ["<*>"]
        node = self._search(seq)
        if node is None:
            cid = self._insert(seq)
        else:
            cid = self._merge(node, seq)
        return cid

    def _search(self, seq):
        n = self.root.child.get(len(seq))
        if n is None:
            return None
        depth = 1
        parent = n
        for tok in seq:
            if depth >= self.depth or depth > len(seq):
                break
            if tok in parent.child:
                parent = parent.child[tok]
            elif "<*>" in parent.child:
                parent = parent.child["<*>"]
            else:
                return None
            depth += 1
        return self._fast_match(parent.clusters, seq)

    def _fast_match(self, clusters, seq):
        best = None
        best_sim = -1.0
        best_stars = 10**9
        for cid in clusters:
            sim, stars = seq_sim(self.templates[cid], seq)
            if sim > best_sim or (sim == best_sim and stars < best_stars):
                best_sim, best_stars, best = sim, stars, cid
        if best is not None and best_sim >= self.st:
            return best
        return None

    def _insert(self, seq):
        cid = len(self.templates)
        self.templates.append(list(seq))
        length = len(seq)
        if length not in self.root.child:
            self.root.child[length] = Node()
        parent = self.root.child[length]
        depth = 1
        for tok in seq:
            if depth >= self.depth or depth > length:
                break
            token = tok if (tok != "<*>" and len(parent.child) < self.max_child) else "<*>"
            if tok == "<*>":
                token = "<*>"
            if token not in parent.child:
                parent.child[token] = Node()
            parent = parent.child[token]
            depth += 1
        parent.clusters.append(cid)
        return cid

    def _merge(self, cid, seq):
        tmpl = self.templates[cid]
        self.templates[cid] = [
            a if a == b else "<*>" for a, b in zip(tmpl, seq)
        ]
        return cid


REX = {
    "none": [],
    "log_parser": [  # statistic/log_parser.py
        r"(/|)([0-9]+\.){3}[0-9]+(:[0-9]+|)(:|)",
        r"\{.*?\}",
    ],
    "label_anomaly": [  # main/label_anomaly.py
        r"\d+",
        r"\[.*?\]",
        r"'[^']+'",
        r'"[^"]+"',
        r"(?:/|)(?:[0-9]+\.){3}[0-9]+(?::[0-9]+|)(?::|)",
        r"<\*>",
        r"%\%",
        r"\b(?:\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2})\b",
        r"\b(?:[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12})\b",
        r"/[\w./-]+",
    ],
    "zk": [  # parse_zookeeper.py
        r"(/|)(\d+\.){3}\d+(:\d+)?",
    ],
    "digits": [r"\d+"],
    "ip_digits": [
        r"(/|)([0-9]+\.){3}[0-9]+(:[0-9]+|)",
        r"\b\d+\b",
    ],
    "hdfs_common": [
        r"blk_-?\d+",
        r"(/|)([0-9]+\.){3}[0-9]+(:[0-9]+|)",
        r"\b\d+\b",
    ],
}


def load_ag_contents():
    path = ROOT / "output/log_events/combined_parsed_logs.csv"
    with path.open(encoding="utf-8", errors="replace") as fh:
        return [row["Content"] for row in csv.DictReader(fh) if row.get("Content")]


def load_ag_final():
    data = json.loads((ROOT / "output/log_events/final_logs.json").read_text())
    msgs = []
    for v in data.values():
        log = v.get("log") if isinstance(v, dict) else None
        if not log:
            continue
        # strip [LEVEL]:
        if "]:" in log[:12]:
            log = log.split("]:", 1)[1]
        msgs.append(log)
    return msgs


def load_zk_contents():
    path = ROOT / "dataset/Zookeeper/Zookeeper.log_structured.csv"
    with path.open(encoding="utf-8", errors="replace") as fh:
        return [row["Content"] for row in csv.DictReader(fh) if row.get("Content")]


def load_hdfs_source_formats():
    path = ROOT / "hadoop/hadoop-hdfs-project/log_templates.txt"
    line_re = re.compile(r"^([^:]*\.java):\s?(.*)$")
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        m = line_re.match(line)
        text = m.group(2) if m else line
        if "src/test" in (m.group(1) if m else ""):
            continue
        if text.strip():
            out.append(text)
    return out


def load_hdfs_parsed_contents():
    path = ROOT / "output/log_events/hdfs_combined_parsed_logs.csv"
    with path.open(encoding="utf-8", errors="replace") as fh:
        return [row["Content"] for row in csv.DictReader(fh) if row.get("Content")]


def run_drain(msgs, st, depth, rex_name):
    d = Drain(st=st, depth=depth, rex=REX[rex_name])
    for m in msgs:
        d.add(m)
    return len(d.templates)


def nearest(n):
    return min(TARGETS, key=lambda t: abs(t - n)), abs(min(TARGETS, key=lambda t: abs(t - n)) - n)


def main():
    corpora = {
        "ag_content": load_ag_contents(),
        "ag_final": load_ag_final(),
        "zk_content": load_zk_contents(),
        "hdfs_source_fmt": load_hdfs_source_formats(),
        "hdfs_parsed": load_hdfs_parsed_contents(),
    }
    print("corpus sizes:")
    for k, v in corpora.items():
        print(f"  {k:16s} {len(v):6d} unique_raw={len(set(v))}")

    # production presets from the repo
    presets = [
        ("label_anomaly", 0.5, 2),
        ("log_parser", 0.4, 1),
        ("zk", 0.5, 4),
        ("none", 0.5, 4),
        ("none", 0.4, 4),
        ("digits", 0.5, 4),
        ("ip_digits", 0.5, 4),
        ("hdfs_common", 0.5, 4),
        ("label_anomaly", 0.4, 1),
        ("label_anomaly", 0.4, 2),
        ("label_anomaly", 0.5, 1),
        ("label_anomaly", 0.5, 3),
        ("label_anomaly", 0.5, 4),
        ("log_parser", 0.5, 2),
        ("log_parser", 0.5, 4),
    ]
    grid_st = (0.3, 0.4, 0.5, 0.6)
    grid_depth = (1, 2, 3, 4, 5)
    grid_rex = ("label_anomaly", "log_parser", "none", "ip_digits")

    rows = []
    seen = set()

    def one(corpus, rex_name, st, depth):
        key = (corpus, rex_name, st, depth)
        if key in seen:
            return
        seen.add(key)
        n = run_drain(corpora[corpus], st, depth, rex_name)
        tgt, dist = nearest(n)
        mark = " HIT" if dist == 0 else (" ~" if dist <= 20 else "")
        print(f"{corpus:16s} rex={rex_name:14s} st={st:.1f} depth={depth} -> {n:6d}  nearest {tgt} Δ{dist}{mark}")
        rows.append((corpus, rex_name, st, depth, n, tgt, dist))

    print("\n=== presets ===")
    for corpus in corpora:
        for rex_name, st, depth in presets:
            one(corpus, rex_name, st, depth)

    print("\n=== grid (ag_content + zk + hdfs_source) ===")
    for corpus in ("ag_content", "zk_content", "hdfs_source_fmt"):
        for rex_name in grid_rex:
            for st in grid_st:
                for depth in grid_depth:
                    one(corpus, rex_name, st, depth)

    print("\n=== closest to each target ===")
    for tgt in TARGETS:
        cand = sorted(rows, key=lambda r: (abs(r[4] - tgt), r[6]))
        print(f"\ntarget {tgt}:")
        for r in cand[:8]:
            print(f"  {r[4]:6d}  {r[0]:16s} rex={r[1]:14s} st={r[2]} depth={r[3]}  Δ{abs(r[4]-tgt)}")

    out = ROOT / "statistic/x5_out/drain_sweep.csv"
    with out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["corpus", "rex", "st", "depth", "n_templates", "nearest_target", "delta"])
        w.writerows(rows)
    print(f"\nwrote {out} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
