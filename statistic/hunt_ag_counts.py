#!/usr/bin/env python3
"""Hunt original AG event/coverage counts by parameter-masking and loose matching.

Hypothesis: the paper did not use Drain clustering for Table 4; it replaced
parameter slots in both source format strings and generated messages, then
counted unique skeletons and/or how many source strings were hit.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "hadoop/hadoop-hdfs-project/log_templates.txt"
TARGETS = {2874, 2889, 2886, 2890, 2989, 30, 31, 48}


def read_source(drop_test=True, unique=True, strip=False):
    line_re = re.compile(r"^([^:]*\.java):\s?(.*)$")
    stmts = []
    for line in GOLD.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        m = line_re.match(line)
        if m:
            path, text = m.group(1), m.group(2)
            if drop_test and ("src/test" in path or "/test/" in path):
                continue
        else:
            text = line
        if strip:
            text = text.strip()
        if text:
            stmts.append(text)
    return sorted(set(stmts)) if unique else stmts


LEVEL = re.compile(r"^\s*\[?(trace|debug|info|warn|warning|error|fatal)\]?\s*:?\s*", re.I)
JAVA_PH = re.compile(r"\{\}|\{[0-9]+\}|%[0-9]*[sdxfoeEgG]|\{\w+\}|\$\{[^}]*\}|<\*>")
NUM = re.compile(r"\b\d+\b")
HEX = re.compile(r"0x[0-9a-fA-F]+")
IP = re.compile(r"(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?")
PATH = re.compile(r"(?:/[A-Za-z0-9_.-]+)+")
BLK = re.compile(r"blk_-?\d+")
UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
NON_ALNUM = re.compile(r"[^a-z0-9]+")


def strip_level(s):
    return LEVEL.sub("", s)


def mask_params(s, mode="full"):
    s = strip_level(s)
    s = JAVA_PH.sub("<*>", s)
    if mode in ("full", "nums"):
        s = HEX.sub("<*>", s)
        s = BLK.sub("<*>", s)
        s = UUID.sub("<*>", s)
        s = IP.sub("<*>", s)
        s = NUM.sub("<*>", s)
    if mode == "full":
        s = PATH.sub("<*>", s)
        s = QUOTED.sub("<*>", s)
    s = re.sub(r"(<\*>\s*)+", "<*> ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def tokens(s, drop_digits=True):
    s = strip_level(s)
    s = JAVA_PH.sub(" ", s)
    s = NON_ALNUM.sub(" ", s.lower())
    toks = s.split()
    if drop_digits:
        toks = [t for t in toks if not t.isdigit()]
    return toks


def load_ag_msgs():
    data = json.loads((ROOT / "output/log_events/final_logs.json").read_text())
    return [v["log"] for v in data.values() if isinstance(v, dict) and v.get("log")]


def load_ag_content():
    with (ROOT / "output/log_events/combined_parsed_logs.csv").open() as f:
        return [r["Content"] for r in csv.DictReader(f) if r.get("Content")]


def load_ag_et():
    with (ROOT / "output/log_events/combined_parsed_logs.csv").open() as f:
        return [r["EventTemplate"] for r in csv.DictReader(f) if r.get("EventTemplate")]


def load_hdfs_et():
    with (ROOT / "output/log_events/hdfs_combined_parsed_logs.csv").open() as f:
        return [r["EventTemplate"] for r in csv.DictReader(f) if r.get("EventTemplate")]


def report(name, n):
    hit = "  << TARGET" if n in TARGETS else ""
    near = ""
    for t in TARGETS:
        if t not in (n,) and abs(n - t) <= 30:
            near = f"  ~{t} Δ{abs(n-t)}"
            break
    print(f"{n:7d}  {name}{hit}{near}")


def cover_ordered(sources, msgs, min_tok=1):
    tmpl = [tokens(s) for s in sources]
    covered = set()
    # index by rarest token
    from collections import defaultdict
    freq = defaultdict(int)
    for t in tmpl:
        for x in set(t):
            freq[x] += 1
    index = defaultdict(list)
    for i, t in enumerate(tmpl):
        if len(t) < min_tok:
            continue
        key = min(set(t), key=lambda z: freq[z]) if t else ""
        index[key].append(i)
    for msg in msgs:
        m = tokens(msg)
        mset = set(m)
        cands = set()
        for x in mset:
            cands.update(index.get(x, ()))
        for i in cands:
            if i in covered:
                continue
            t = tmpl[i]
            if not mset.issuperset(t):
                continue
            it = iter(m)
            if all(any(x == tok for x in it) for tok in t):
                covered.add(i)
    return len(covered)


def cover_unordered(sources, msgs, min_tok=1):
    tmpl = [set(tokens(s)) for s in sources]
    usable = [(i, t) for i, t in enumerate(tmpl) if len(t) >= min_tok]
    covered = set()
    msg_sets = [set(tokens(m)) for m in msgs]
    # union of all message tokens for a cheap filter then per-msg
    universe = set().union(*msg_sets) if msg_sets else set()
    for i, t in usable:
        if not t <= universe:
            continue
        for ms in msg_sets:
            if t <= ms:
                covered.add(i)
                break
    return len(covered)


def cover_longest_literal(sources, msgs):
    """Cover if the longest placeholder-free substring (>=4 chars) appears."""
    covered = set()
    low_msgs = [strip_level(m).lower() for m in msgs]
    blob = "\n".join(low_msgs)
    for i, s in enumerate(sources):
        parts = [p.strip().lower() for p in JAVA_PH.split(s) if len(p.strip()) >= 4]
        if not parts:
            continue
        lit = max(parts, key=len)
        if lit in blob:
            covered.add(i)
    return len(covered)


def cover_regex(sources, msgs, min_lit=3):
    """Treat {} as .* and search."""
    covered = set()
    blob = "\n".join(strip_level(m) for m in msgs)
    for i, s in enumerate(sources):
        parts = [re.escape(p) for p in JAVA_PH.split(s) if p]
        if not parts:
            continue
        if sum(len(p) for p in JAVA_PH.split(s) if p.strip()) < min_lit:
            continue
        pat = ".*?".join(parts)
        try:
            if re.search(pat, blob, re.I | re.S):
                covered.add(i)
        except re.error:
            continue
    return len(covered)


def cover_exact_skeleton(sources, msgs, mode="full"):
    msg_sk = {mask_params(m, mode) for m in msgs}
    n = 0
    for s in sources:
        if mask_params(s, mode) in msg_sk:
            n += 1
    return n


def main():
    src_u = read_source(True, True, False)
    src_us = read_source(True, True, True)
    src_all = read_source(False, True, False)
    src_stmt = read_source(True, False, False)
    print("universe unique prod", len(src_u), "stripped", len(src_us),
          "incl test", len(src_all), "stmts", len(src_stmt))

    ag_msg = load_ag_msgs()
    ag_content = load_ag_content()
    ag_et = load_ag_et()
    hdfs_et = load_hdfs_et()
    print("ag msgs", len(ag_msg), "content", len(ag_content), "et", len(ag_et))

    print("\n=== unique AG skeletons (event counts, not coverage) ===")
    for name, seq in [
        ("raw unique log", ag_msg),
        ("raw unique content", ag_content),
        ("unique EventTemplate all", ag_et),
        ("unique EventTemplate hdfs csv", hdfs_et),
    ]:
        report(name, len(set(seq)))
    for mode in ("ph_only", "nums", "full"):
        if mode == "ph_only":
            sk = {mask_params(m, "full") for m in ag_msg}  # placeholder later
            # ph_only: only java placeholders + level
            sk = {mask_params(m, "nums") for m in ag_msg}  # wait
        report(f"mask({mode}) unique AG logs", len({mask_params(m, mode if mode != "ph_only" else "nums") for m in ag_msg}))
    # dedicated ph-only
    def mask_ph(s):
        s = strip_level(s)
        s = JAVA_PH.sub("<*>", s)
        s = re.sub(r"(<\*>\s*)+", "<*> ", s)
        return re.sub(r"\s+", " ", s).strip().lower()
    report("mask(java placeholders only) unique AG logs", len({mask_ph(m) for m in ag_msg}))
    report("mask(java placeholders only) unique AG content", len({mask_ph(m) for m in ag_content}))
    report("mask(java placeholders only) unique EventTemplate", len({mask_ph(m) for m in ag_et}))
    report("mask(full) unique EventTemplate", len({mask_params(m, "full") for m in ag_et}))
    report("mask(full) unique AG content", len({mask_params(m, "full") for m in ag_content}))
    report("token-join unique AG logs", len({" ".join(tokens(m)) for m in ag_msg}))
    report("token-join unique source", len({" ".join(tokens(s)) for s in src_u}))
    report("mask(full) unique source", len({mask_params(s, "full") for s in src_u}))
    report("mask(nums) unique source", len({mask_params(s, "nums") for s in src_u}))

    print("\n=== coverage: how many SOURCE templates hit by AG ===")
    for min_tok in (1, 2):
        report(f"D1 ordered min_tok={min_tok}", cover_ordered(src_u, ag_msg, min_tok))
    report("unordered set min_tok=1", cover_unordered(src_u, ag_msg, 1))
    report("unordered set min_tok=2", cover_unordered(src_u, ag_msg, 2))
    report("longest literal >=4 substring", cover_longest_literal(src_u, ag_msg))
    report("exact skeleton full", cover_exact_skeleton(src_u, ag_msg, "full"))
    report("exact skeleton nums", cover_exact_skeleton(src_u, ag_msg, "nums"))
    report("exact skeleton vs EventTemplate full", cover_exact_skeleton(src_u, ag_et, "full"))
    report("regex {}->.*?  min_lit=3", cover_regex(src_u, ag_msg, 3))
    report("regex {}->.*?  min_lit=1", cover_regex(src_u, ag_msg, 1))

    # also vs content / et
    report("D1 ordered vs EventTemplate min=1", cover_ordered(src_u, ag_et, 1))
    report("D1 ordered vs content min=1", cover_ordered(src_u, ag_content, 1))
    report("unordered vs EventTemplate min=1", cover_unordered(src_u, ag_et, 1))

    # universe variants
    print("\n=== D1 on other universes (min_tok=1) ===")
    report("D1 unique incl test", cover_ordered(src_all, ag_msg, 1))
    report("D1 all statements (not unique)", cover_ordered(src_stmt, ag_msg, 1))
    report("unordered all statements", cover_unordered(src_stmt, ag_msg, 1))
    report("longest-lit all statements", cover_longest_literal(src_stmt, ag_msg))

    print("\ndone")


if __name__ == "__main__":
    main()
