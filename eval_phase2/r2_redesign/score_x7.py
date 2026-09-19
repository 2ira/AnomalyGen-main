#!/usr/bin/env python3
"""Compare GPT-4o X7 fills to archived DeepSeek-V3 fills.

Slots are NOT claimed to be the same 207 Drain sample. Both sides are scored
with the same type-validity rules (infer_slot_type + score_type_validity) after
aligning filled lines to the Drain template catalogue from the DeepSeek CSV.
Block-id consistency uses the R2.7 invariant (one block id per session).
"""
import collections
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.dirname(HERE)
REPO = os.path.dirname(EVAL)
sys.path.insert(0, EVAL)
sys.path.insert(0, REPO)

from common import read_jsonl, EVAL_RESULT_DIR  # noqa: E402
from build_param_set import infer_slot_type, _looks_status  # noqa: E402
from run_param_eval import score_type_validity  # noqa: E402
from utils import extract_from_content_log_seq, extract_from_content_log_sequence  # noqa: E402

LEVEL = re.compile(
    r"\[(?:DEBUG|INFO|WARN|WARNING|ERROR|TRACE|FATAL|CRITICAL)\]:\s*",
    re.IGNORECASE,
)
SPLIT_LEVEL = re.compile(
    r"(?=\[(?:DEBUG|INFO|WARN|WARNING|ERROR|TRACE|FATAL|CRITICAL)\]:)",
    re.IGNORECASE,
)
CSV = os.path.join(
    REPO, "output_v1", "ablation", "baseline", "parsed_logs",
    "hdfs_combined_parsed_logs.csv",
)
BLK = re.compile(r"\bblk_(-?\d+)", re.IGNORECASE)
BLOCK = re.compile(r"\b(?:stored)?block-?(\d+)\b", re.IGNORECASE)
BLOCK_WORD = re.compile(r"\bblock\s+(\d+)\b", re.IGNORECASE)
LIST_CTX = re.compile(r"storageIDs\s*\[[^\]]*\]|storageTypes\s*\[[^\]]*\]", re.I)


def load_templates(path):
    tmps = []
    seen = set()
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            t = (row.get("EventTemplate") or "").strip()
            if t and t not in seen:
                seen.add(t)
                tmps.append(t)
    tmps.sort(key=lambda t: (-t.count("<*>"), -len(t)))
    return tmps


def split_log_lines(text):
    text = (text or "").strip()
    if not text:
        return []
    chunks = [c.strip() for c in SPLIT_LEVEL.split(text) if c.strip()]
    if len(chunks) <= 1:
        chunks = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out = []
    for c in chunks:
        out.append(LEVEL.sub("", c).strip())
    return [x for x in out if x]


def match_template(content, templates):
    for tmpl in templates:
        parts = tmpl.split("<*>")
        if len(parts) == 1:
            if content == tmpl:
                return tmpl, []
            continue
        rx = "^" + "".join(
            re.escape(p) + ("(.*?)" if i < len(parts) - 1 else "")
            for i, p in enumerate(parts)
        ) + "$"
        m = re.match(rx, content)
        if not m:
            continue
        params = [g.strip() for g in m.groups()]
        if any(p == "" for p in params):
            continue
        return tmpl, params
    return None, None


def slots_from_lines(lines, templates, source, session_id):
    rows = []
    n_line = n_matched = 0
    for li, content in enumerate(lines):
        n_line += 1
        tmpl, params = match_template(content, templates)
        if tmpl is None or not params:
            continue
        n_matched += 1
        for i, val in enumerate(params):
            stype, ctx = infer_slot_type(tmpl, i)
            if stype == "generic" and _looks_status(val):
                stype = "status"
            item = {
                "param_id": f"{source}::{session_id}::{li}::{i}",
                "source_file": source,
                "block_id": session_id,
                "event_template": tmpl,
                "content": content,
                "slot_idx": i,
                "param_value": val,
                "slot_type": stype,
                "slot_context": ctx,
            }
            item["type_valid"] = score_type_validity(item)
            rows.append(item)
    return rows, n_line, n_matched


def gpt4o_log_text(raw):
    pairs = extract_from_content_log_seq(raw or "")
    if not pairs:
        pairs = extract_from_content_log_sequence(raw or "")
    if pairs:
        return " ".join(p.get("log") or "" for p in pairs)
    return raw or ""


def block_ids(text):
    text = LIST_CTX.sub(" ", text or "")
    ids = [m.group(1) for m in BLK.finditer(text)]
    ids += [m.group(1) for m in BLOCK.finditer(text)]
    ids += [m.group(1) for m in BLOCK_WORD.finditer(text)]
    norm = []
    for i in ids:
        try:
            norm.append(str(int(i)))
        except ValueError:
            norm.append(i)
    return norm


def session_consistency(lines):
    text = " ".join(lines)
    ids = block_ids(text)
    distinct = sorted(set(ids))
    if len(ids) < 2:
        return None, ids, distinct
    return len(distinct) == 1, ids, distinct


def summarise_slots(rows):
    by = collections.Counter()
    tv = collections.Counter()
    by_type = collections.defaultdict(lambda: collections.Counter())
    for r in rows:
        by[r["slot_type"]] += 1
        key = {True: "true", False: "false", None: "none"}[r["type_valid"]]
        tv[key] += 1
        by_type[r["slot_type"]][key] += 1
    decidable = tv["true"] + tv["false"]
    return {
        "n_slots": len(rows),
        "type_valid_true": tv["true"],
        "type_valid_false": tv["false"],
        "type_valid_none": tv["none"],
        "type_validity": round(tv["true"] / decidable, 4) if decidable else None,
        "n_decidable": decidable,
        "by_type": {
            st: {
                "n": sum(c.values()),
                "true": c["true"],
                "false": c["false"],
                "none": c["none"],
                "rate": round(c["true"] / (c["true"] + c["false"]), 4)
                if (c["true"] + c["false"]) else None,
            }
            for st, c in sorted(by_type.items())
        },
    }


def summarise_ctx(verdicts):
    dec = [v for v in verdicts if v is not None]
    ok = [v for v in dec if v]
    return {
        "n_sessions": len(verdicts),
        "n_decidable": len(dec),
        "n_pass": len(ok),
        "n_fail": len(dec) - len(ok),
        "rate": round(len(ok) / len(dec), 4) if dec else None,
    }


def drain_csv_slots(path):
    from build_param_set import extract_params_from_csv
    rows = extract_params_from_csv(path)
    for r in rows:
        r["type_valid"] = score_type_validity(r)
    return rows


def main():
    templates = load_templates(CSV)
    filled = os.path.join(EVAL_RESULT_DIR, "x7_gpt4o", "filled.jsonl")
    gpt_rows = read_jsonl(filled) if os.path.exists(filled) else []

    gpt_slots = []
    gpt_ctx = []
    gpt_line_stats = {"n_line": 0, "n_matched": 0, "n_ok_calls": 0}
    for r in gpt_rows:
        if r.get("finish_reason") == "stop" and r.get("raw_response"):
            gpt_line_stats["n_ok_calls"] += 1
        lines = split_log_lines(gpt4o_log_text(r.get("raw_response") or ""))
        slots, n_line, n_matched = slots_from_lines(
            lines, templates, "x7_gpt4o", r.get("session_id"),
        )
        gpt_slots.extend(slots)
        gpt_line_stats["n_line"] += n_line
        gpt_line_stats["n_matched"] += n_matched
        ok, _, _ = session_consistency(lines)
        gpt_ctx.append(ok)

    ds_slots = []
    ds_ctx = []
    ds_line_stats = {"n_line": 0, "n_matched": 0, "n_methods": 0}
    seen_ds = set()
    for r in gpt_rows:
        for log in r.get("deepseek_logs") or []:
            key = (r.get("session_id"), log)
            if key in seen_ds:
                continue
            seen_ds.add(key)
            ds_line_stats["n_methods"] += 1
            lines = split_log_lines(log)
            slots, n_line, n_matched = slots_from_lines(
                lines, templates, "deepseek_v3", r.get("session_id"),
            )
            ds_slots.extend(slots)
            ds_line_stats["n_line"] += n_line
            ds_line_stats["n_matched"] += n_matched
            ok, _, _ = session_consistency(lines)
            ds_ctx.append(ok)

    drain_slots = drain_csv_slots(CSV)

    report = {
        "protocol": {
            "archived_fill": "DeepSeek-V3",
            "new_fill": "GPT-4o get_log_simulate_v2",
            "same_207_slots": False,
            "unfilled_source": "output_v1/hadoop/merge_hdfs.json",
            "n_gpt4o_methods": len(gpt_rows),
            "n_gpt4o_ok": gpt_line_stats["n_ok_calls"],
        },
        "deepseek_drain_baseline_csv": summarise_slots(drain_slots),
        "deepseek_paired_template_match": {
            **summarise_slots(ds_slots),
            "lines": ds_line_stats,
            "block_consistency": summarise_ctx(ds_ctx),
        },
        "gpt4o_template_match": {
            **summarise_slots(gpt_slots),
            "lines": gpt_line_stats,
            "block_consistency": summarise_ctx(gpt_ctx),
        },
    }
    out_dir = os.path.join(EVAL_RESULT_DIR, "x7_gpt4o")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "compare.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
