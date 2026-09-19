#!/usr/bin/env python3
"""Build X7 Phase-III inputs from archived unfilled merge templates.

One row per method signature, same payload compress_log() sent to
get_log_simulate_v2. Paired to DeepSeek fills in baseline_compressed_log.json
via sha256(sig)[:8].
"""
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.dirname(HERE)
REPO = os.path.dirname(EVAL)
sys.path.insert(0, EVAL)
from common import write_jsonl, EVAL_DATA_DIR  # noqa: E402

MERGE = os.path.join(REPO, "output_v1", "hadoop", "merge_hdfs.json")
DEEPSEEK = os.path.join(REPO, "baseline_compressed_log.json")


def sig_key(sig):
    return hashlib.sha256(sig.encode("utf-8")).hexdigest()[:8]


def main():
    with open(MERGE, encoding="utf-8") as f:
        merge = json.load(f)
    ds = {}
    if os.path.exists(DEEPSEEK):
        with open(DEEPSEEK, encoding="utf-8") as f:
            ds = json.load(f)

    rows = []
    skipped_empty = 0
    for sig, origin in merge.items():
        origin = origin if isinstance(origin, str) else json.dumps(origin)
        if not origin.strip():
            skipped_empty += 1
            continue
        key = sig_key(sig)
        ds_hits = sorted(k for k in ds if k.startswith(key + "_"))
        rows.append({
            "session_id": key,
            "method": sig,
            "phase3_input": origin,
            "input_chars": len(origin),
            "deepseek_keys": ds_hits,
            "deepseek_logs": [ds[k].get("log", "") for k in ds_hits],
            "corpus": "hdfs_cot_analysis",
            "merge_file": "output_v1/hadoop/merge_hdfs.json",
        })

    os.makedirs(EVAL_DATA_DIR, exist_ok=True)
    path = os.path.join(EVAL_DATA_DIR, "x7_sessions.jsonl")
    write_jsonl(path, rows)
    n_paired = sum(1 for r in rows if r["deepseek_keys"])
    print(f"x7_sessions n={len(rows)} paired_deepseek={n_paired} "
          f"skipped_empty={skipped_empty} -> {path}")


if __name__ == "__main__":
    main()
