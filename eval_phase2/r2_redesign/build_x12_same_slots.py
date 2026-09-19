#!/usr/bin/env python3
"""R2.12: strict same-input GPT-4o vs DeepSeek-V3 head-to-head on the 207-slot sample.

X7 refilled all 96 archived merge templates, so its slots are not the ones that
were scored. Here we walk back from the scored slots instead:

    param_scored.jsonl  ->  block_id  ->  sha256(method_signature)[:8]
    merge_hdfs.json     ->  the exact Phase III input DeepSeek received

Only the HDFS methods behind the scored sample are refilled, so GPT-4o sees the
same inputs that produced the DeepSeek slots.

  build   pair scored slots to Phase III inputs, write x12_sessions.jsonl
  run     call GPT-4o on those inputs (needs OPENAI_API_KEY)

Zookeeper slots are excluded: their merge inputs live in
output/zookeeper/*/merge_single_log.json under a different key scheme.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.dirname(HERE)
REPO = os.path.dirname(EVAL)
sys.path.insert(0, EVAL)
sys.path.insert(0, HERE)

SCORED = os.path.join(EVAL, "eval_data", "param_scored.jsonl")
MERGE = os.path.join(REPO, "output_v1", "hadoop", "merge_hdfs.json")
SESSIONS = os.path.join(EVAL, "eval_data", "x12_sessions.jsonl")
OUTDIR = os.path.join(EVAL, "eval_results", "x12_same_slots")


def read_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def build():
    scored = read_jsonl(SCORED)
    with open(MERGE, encoding="utf-8") as fh:
        merge = json.load(fh)
    sig_by_prefix = {hashlib.sha256(s.encode("utf-8")).hexdigest()[:8]: s for s in merge}

    slots_by_prefix = defaultdict(list)
    for row in scored:
        slots_by_prefix[row["block_id"].split("_")[0]].append(row)

    rows, unmatched = [], []
    for prefix, slots in sorted(slots_by_prefix.items()):
        sig = sig_by_prefix.get(prefix)
        if sig is None:
            unmatched.append((prefix, len(slots)))
            continue
        origin = merge[sig]
        origin = origin if isinstance(origin, str) else json.dumps(origin)
        rows.append({
            "session_id": prefix,
            "method": sig,
            "phase3_input": origin,
            "input_chars": len(origin),
            "n_scored_slots": len(slots),
            "scored_param_ids": [s["param_id"] for s in slots],
            "scored_block_ids": sorted({s["block_id"] for s in slots}),
            "deepseek_type_valid": Counter(str(s["type_valid"]) for s in slots),
            "merge_file": "output_v1/hadoop/merge_hdfs.json",
        })

    write_jsonl(SESSIONS, rows)
    matched_slots = sum(r["n_scored_slots"] for r in rows)
    print(f"[build] methods paired        : {len(rows)}")
    print(f"[build] scored slots covered  : {matched_slots}/{len(scored)}")
    print(f"[build] unmatched (Zookeeper) : {sum(n for _, n in unmatched)} slots "
          f"across {len(unmatched)} block prefixes")
    print(f"[build] wrote {SESSIONS}")


def run(model):
    from llm_client import openai_client, chat  # noqa: E402
    sys.path.insert(0, REPO)
    from models.prompts.standard_log import get_log_simulate_v2  # noqa: E402

    rows = read_jsonl(SESSIONS)
    client, default_model, base = openai_client()
    model = model or default_model
    os.makedirs(OUTDIR, exist_ok=True)
    filled_path = os.path.join(OUTDIR, "filled.jsonl")
    done = {}
    if os.path.exists(filled_path):
        for rec in read_jsonl(filled_path):
            if rec.get("raw_response") and not rec.get("http_error"):
                done[rec["session_id"]] = rec
    print(f"[run] {len(rows)} calls -> {model} @ {base} ({len(done)} already done)")

    out = []
    for i, r in enumerate(rows, 1):
        if r["session_id"] in done:
            out.append(done[r["session_id"]])
            print(f"  [{i}/{len(rows)}] skip {r['method'][:70]}")
            continue
        prompt = list(get_log_simulate_v2(r["phase3_input"]))[0]
        raw, usage, finish = chat(client, model, prompt)
        rec = dict(r)
        rec.update({"model": model, "prompt_fn": "get_log_simulate_v2",
                    "raw_response": raw, "usage": usage, "finish_reason": finish})
        out.append(rec)
        write_jsonl(os.path.join(OUTDIR, "filled.jsonl"), out)
        print(f"  [{i}/{len(rows)}] {r['method'][:70]}")

    os.makedirs(OUTDIR, exist_ok=True)
    write_jsonl(os.path.join(OUTDIR, "filled.jsonl"), out)
    print(f"[run] wrote {OUTDIR}/filled.jsonl")
    print("[run] next: score with score_x7.py pointed at this directory")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["build", "run"])
    ap.add_argument("--model", default=None)
    args = ap.parse_args()
    build() if args.step == "build" else run(args.model)


if __name__ == "__main__":
    main()
