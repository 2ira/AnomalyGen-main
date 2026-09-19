#!/usr/bin/env python3
"""Score the R2.12 same-input GPT-4o refill against the archived DeepSeek slots."""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.dirname(HERE)
REPO = os.path.dirname(EVAL)
sys.path.insert(0, EVAL)
sys.path.insert(0, HERE)

from common import read_jsonl  # noqa: E402
from score_x7 import (  # noqa: E402
    CSV, load_templates, split_log_lines, slots_from_lines,
    gpt4o_log_text, session_consistency, summarise_slots, summarise_ctx,
)

SCORED = os.path.join(EVAL, "eval_data", "param_scored.jsonl")
SESSIONS = os.path.join(EVAL, "eval_data", "x12_sessions.jsonl")
FILLED = os.path.join(EVAL, "eval_results", "x12_same_slots", "filled.jsonl")
OUT = os.path.join(EVAL, "eval_results", "x12_same_slots", "compare.json")


def main():
    sessions = {r["session_id"]: r for r in read_jsonl(SESSIONS)}
    prefixes = set(sessions)
    scored = [r for r in read_jsonl(SCORED) if r["block_id"].split("_")[0] in prefixes]
    filled = read_jsonl(FILLED)
    templates = load_templates(CSV)

    gpt_slots, gpt_ctx = [], []
    line_stats = {"n_line": 0, "n_matched": 0, "n_ok_calls": 0}
    for r in filled:
        if r.get("finish_reason") == "stop" and r.get("raw_response"):
            line_stats["n_ok_calls"] += 1
        lines = split_log_lines(gpt4o_log_text(r.get("raw_response") or ""))
        slots, n_line, n_matched = slots_from_lines(
            lines, templates, "x12_gpt4o", r.get("session_id"),
        )
        gpt_slots.extend(slots)
        line_stats["n_line"] += n_line
        line_stats["n_matched"] += n_matched
        ok, _, _ = session_consistency(lines)
        gpt_ctx.append(ok)

    ds_tv = Counter(str(r.get("type_valid")) for r in scored)
    ds_dec = ds_tv["True"] + ds_tv["False"]
    gpt = summarise_slots(gpt_slots)
    report = {
        "protocol": {
            "same_input": True,
            "n_methods": len(sessions),
            "n_gpt4o_ok": line_stats["n_ok_calls"],
            "deepseek_slots_on_these_methods": len(scored),
            "source": "output_v1/hadoop/merge_hdfs.json",
        },
        "deepseek_archived_162": {
            "n_slots": len(scored),
            "type_valid_true": ds_tv["True"],
            "type_valid_false": ds_tv["False"],
            "type_valid_none": ds_tv["None"],
            "n_decidable": ds_dec,
            "type_validity": round(ds_tv["True"] / ds_dec, 4) if ds_dec else None,
            "by_type": dict(Counter(r["slot_type"] for r in scored)),
        },
        "gpt4o_same_input": {
            **gpt,
            "lines": line_stats,
            "block_consistency": summarise_ctx(gpt_ctx),
        },
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print(json.dumps(report, indent=2))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
