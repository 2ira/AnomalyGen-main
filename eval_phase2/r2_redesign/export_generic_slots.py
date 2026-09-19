#!/usr/bin/env python3
"""Enumerate the 24 generic (undeterminable) slots for R2.7.

These are not LLM 'unknown' answers. infer_slot_type found no format convention
to the left of <*>, so type_valid is left None.
"""
import collections
import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.dirname(HERE)
sys.path.insert(0, EVAL)
from common import read_jsonl, EVAL_DATA_DIR  # noqa: E402

SCORED = os.path.join(EVAL, "eval_data", "param_scored.jsonl")


def why_generic(r):
    ctx = (r.get("slot_context") or "").lower()
    tmpl = r.get("event_template") or ""
    left = tmpl.split("<*>")[r.get("slot_idx", 0)][-40:] if "<*>" in tmpl else ""
    if ctx in {"pipeline", "nodes", "storageids", "storagetypes"} or "[" in str(r.get("param_value", "")):
        return "list_or_aggregate", "Value is a list/aggregate (nodes, pipeline, storageIDs); no single hex/int/path convention."
    if ctx in {"storage", "storagetype"}:
        return "storage_label", "Left context is a storage label, not a typed identifier (hex/path/port)."
    if ctx == "i" or tmpl.startswith("trying to do i"):
        return "parser_split_word", "Drain split a word (e.g. i/o → i<*>); leftover fragment has no type convention."
    if "exception" in tmpl.lower() or ctx in {"exception", "got"}:
        return "free_text_exception", "Exception/message slot: arbitrary text, not a typed identifier."
    if ctx in {"generic", ""} or not ctx:
        return "no_left_hint", f"No hex/ip/path/int/port/nodeid cue in the left context {left!r}."
    return "unmatched_cue", f"Left cue {ctx!r} is not in the typed catalogue (hex, path, int, port, nodeid, status)."


def main():
    rows = read_jsonl(SCORED)
    generics = [r for r in rows if r.get("type_valid") is None and r.get("slot_type") == "generic"]
    out_jsonl = os.path.join(EVAL_DATA_DIR, "generic_slots_24.jsonl")
    out_csv = os.path.join(EVAL_DATA_DIR, "generic_slots_24.csv")
    recs = []
    by_why = collections.Counter()
    for r in generics:
        kind, reason = why_generic(r)
        by_why[kind] += 1
        recs.append({
            "param_id": r.get("param_id"),
            "event_template": r.get("event_template"),
            "slot_idx": r.get("slot_idx"),
            "param_value": r.get("param_value"),
            "slot_context": r.get("slot_context"),
            "content": r.get("content"),
            "source_file": r.get("source_file"),
            "block_id": r.get("block_id"),
            "why_code": kind,
            "why": reason,
        })
    with open(out_jsonl, "w", encoding="utf-8") as f:
        for rec in recs:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(recs[0].keys()) if recs else [])
        if recs:
            w.writeheader()
            w.writerows(recs)
    md = os.path.join(HERE, "generic_slots_24.md")
    with open(md, "w", encoding="utf-8") as f:
        f.write(f"# 24 undeterminable (`generic`) slots\n\n")
        f.write(f"Source: `{os.path.relpath(SCORED, EVAL)}`. n={len(recs)}.\n\n")
        f.write("| why_code | n |\n|---|---|\n")
        for k, n in by_why.most_common():
            f.write(f"| {k} | {n} |\n")
        f.write("\n| # | left cue | value | template |\n|---|---|---|---|\n")
        for i, rec in enumerate(recs, 1):
            tmpl = (rec["event_template"] or "").replace("|", "\\|")[:80]
            val = str(rec["param_value"]).replace("|", "\\|")[:40]
            f.write(f"| {i} | `{rec['slot_context']}` | `{val}` | `{tmpl}` |\n")
        f.write("\nThese 24 are excluded from type validity because no format "
                "convention exists; they are not LLM refusals.\n")
    print(f"n_generic={len(recs)}")
    print(dict(by_why))
    print(f"wrote {out_jsonl}")
    print(f"wrote {md}")


if __name__ == "__main__":
    main()
