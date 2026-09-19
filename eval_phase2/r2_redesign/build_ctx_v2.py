#!/usr/bin/env python3
"""Sample Phase-III inputs that are decidable for block-id consistency.

A path is kept if its unfilled log_sequence contains ≥2 block placeholders.
This is a new sample, not the 207-slot type-validity draw.
"""
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.dirname(HERE)
REPO = os.path.dirname(EVAL)
sys.path.insert(0, EVAL)
from common import write_jsonl, EVAL_DATA_DIR  # noqa: E402

MERGE = os.path.join(REPO, "output_v1", "hadoop", "merge_hdfs.json")
# Count unfilled block *placeholders*, not every occurrence of the word "block".
BRACE = re.compile(r"\{[^}]*\}")
BLK_LIT = re.compile(r"\bblk_")
PATH_RE = re.compile(r"<path>(.*?)</path>", re.DOTALL | re.IGNORECASE)
LOG_RE = re.compile(r"<log_sequence>(.*?)</log_sequence>", re.DOTALL | re.IGNORECASE)
FLOW_RE = re.compile(r"<exec_flow>(.*?)</exec_flow>", re.DOTALL | re.IGNORECASE)


def n_block_placeholders(log):
    n = len(BLK_LIT.findall(log or ""))
    for m in BRACE.finditer(log or ""):
        token = m.group(0)[1:-1].lower()
        left = (log or "")[max(0, m.start() - 48):m.start()].lower()
        if (
            "block" in token
            or token in {"b", "bid", "blockid", "storedblock"}
            or "block" in left
        ):
            n += 1
    return n


def extract_paths(xml):
    if not isinstance(xml, str) or "<path>" not in xml:
        return []
    out = []
    for i, body in enumerate(PATH_RE.findall(xml)):
        lm = LOG_RE.search(body)
        fm = FLOW_RE.search(body)
        log = (lm.group(1) if lm else "").strip()
        flow = (fm.group(1) if fm else "").strip()
        n_ph = n_block_placeholders(log)
        n_lines = len([ln for ln in log.splitlines() if ln.strip()])
        out.append({
            "path_idx": i,
            "log_sequence": log,
            "exec_flow": flow,
            "n_block_placeholders": n_ph,
            "n_log_lines": n_lines,
        })
    return out


def phase3_prompt_body(p):
    return (
        f"<path>\n  <exec_flow>{p['exec_flow']}</exec_flow>\n"
        f"  <log_seq>\n{p['log_sequence']}\n  </log_seq>\n</path>"
    )


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    with open(MERGE, encoding="utf-8") as f:
        data = json.load(f)

    cand = []
    for method, xml in data.items():
        for p in extract_paths(xml):
            if p["n_block_placeholders"] < 2:
                continue
            cand.append({
                "method": method,
                **p,
                "phase3_input": phase3_prompt_body(p),
            })

    rng = random.Random(args.seed)
    rng.shuffle(cand)
    # Prefer more mentions, then sample n unique methods where possible
    cand.sort(key=lambda x: (-x["n_block_placeholders"], -x["n_log_lines"]))
    seen = set()
    picked = []
    rest = []
    for c in cand:
        key = (c["method"], c["path_idx"])
        if key in seen:
            continue
        seen.add(key)
        if c["method"] not in {p["method"] for p in picked}:
            picked.append(c)
        else:
            rest.append(c)
        if len(picked) >= args.n:
            break
    if len(picked) < args.n:
        picked.extend(rest[: args.n - len(picked)])
    picked = picked[: args.n]
    for i, p in enumerate(picked):
        p["session_id"] = f"ctxv2_{i:03d}"

    os.makedirs(EVAL_DATA_DIR, exist_ok=True)
    path = os.path.join(EVAL_DATA_DIR, "ctx_v2_sessions.jsonl")
    write_jsonl(path, picked)
    print(f"candidates_with_ge2_block_ph={len(cand)} sampled={len(picked)} -> {path}")
    print(f"placeholder_counts={sorted({c['n_block_placeholders'] for c in picked})}")


if __name__ == "__main__":
    main()
