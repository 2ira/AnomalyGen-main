#!/usr/bin/env python3
"""R2.12 same-slot (n=144) GPT-4o refill.

Lock the 144 type-decidable DeepSeek slots on the 15 paired HDFS methods.
Convert each Drain template's <*> to {} (the Phase III placeholder the official
prompt actually fills), call get_log_simulate_v2, then extract values with the
*locked* template + slot_idx + slot_type. Missing slots score False so both
sides share denominator 144.

  build   write x12_same_slot_sessions.jsonl
  run     GPT-4o fill (OPENAI_API_KEY)
  score   write eval_results/x12_same_slot/compare.json
  score-old  locked-template extract from the previous same-prompt filled.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.dirname(HERE)
REPO = os.path.dirname(EVAL)
sys.path.insert(0, EVAL)
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)

from common import read_jsonl, write_jsonl  # noqa: E402
from run_blockid_consistency import (  # noqa: E402
    block_ids_in,
    build_sessions_from_source,
    normalise,
)
from run_param_eval import (  # noqa: E402
    build_block_index,
    score_ctx_consistency,
    score_type_validity,
)
from score_x7 import gpt4o_log_text, split_log_lines  # noqa: E402

BLOCK_LEFT = re.compile(r"(blk_|Block|block-|storedBlock|block\s+)$")

SCORED = os.path.join(EVAL, "eval_data", "param_scored.jsonl")
SESSIONS = os.path.join(EVAL, "eval_data", "x12_sessions.jsonl")
SLOT_SESS = os.path.join(EVAL, "eval_data", "x12_same_slot_sessions.jsonl")
OUTDIR = os.path.join(EVAL, "eval_results", "x12_same_slot")
OLD_FILLED = os.path.join(EVAL, "eval_results", "x12_same_slots", "filled.jsonl")


def match_one_template(content, tmpl):
    parts = tmpl.split("<*>")
    if len(parts) == 1:
        return [] if content == tmpl else None
    rx = "^" + "".join(
        re.escape(p) + ("(.*?)" if i < len(parts) - 1 else "")
        for i, p in enumerate(parts)
    ) + "$"
    m = re.match(rx, content)
    if not m:
        return None
    params = [g.strip() for g in m.groups()]
    if any(p == "" for p in params):
        return None
    return params


def locked_slots():
    sessions = {r["session_id"]: r for r in read_jsonl(SESSIONS)}
    prefixes = set(sessions)
    rows = []
    for r in read_jsonl(SCORED):
        prefix = r["block_id"].split("_")[0]
        if prefix not in prefixes:
            continue
        if r.get("type_valid") not in (True, False):
            continue
        item = dict(r)
        item["method_prefix"] = prefix
        item["method"] = sessions[prefix]["method"]
        rows.append(item)
    return sessions, rows


def tmpl_to_phase3(tmpl):
    return tmpl.replace("<*>", "{}")


def build():
    sessions, slots = locked_slots()
    by_prefix = defaultdict(list)
    for s in slots:
        by_prefix[s["method_prefix"]].append(s)

    rows = []
    for prefix, group in sorted(by_prefix.items()):
        tmpls = []
        seen = set()
        for s in group:
            t = s["event_template"]
            if t not in seen:
                seen.add(t)
                tmpls.append(t)
        payload = "\n".join(f"[INFO]:{tmpl_to_phase3(t)}" for t in tmpls)
        rows.append({
            "session_id": prefix,
            "method": sessions[prefix]["method"],
            "n_locked_slots": len(group),
            "n_unique_templates": len(tmpls),
            "templates": tmpls,
            "phase3_input": payload,
            "locked_param_ids": [s["param_id"] for s in group],
        })
    write_jsonl(SLOT_SESS, rows)
    print(f"[build] methods={len(rows)} locked_slots={sum(r['n_locked_slots'] for r in rows)} "
          f"unique_templates={sum(r['n_unique_templates'] for r in rows)}")
    print(f"[build] wrote {SLOT_SESS}")


def run(model=None, sleep=1.0):
    from llm_client import openai_client, chat  # noqa: E402
    from models.prompts.standard_log import get_log_simulate_v2  # noqa: E402

    rows = read_jsonl(SLOT_SESS)
    os.makedirs(OUTDIR, exist_ok=True)
    filled_path = os.path.join(OUTDIR, "filled.jsonl")
    done = {}
    if os.path.exists(filled_path):
        for rec in read_jsonl(filled_path):
            if rec.get("raw_response") and rec.get("finish_reason") == "stop":
                done[rec["session_id"]] = rec
    client, default_model, base = openai_client()
    model = model or default_model
    print(f"[run] n={len(rows)} done={len(done)} model={model} base={base}")
    out = []
    for i, r in enumerate(rows, 1):
        if r["session_id"] in done:
            out.append(done[r["session_id"]])
            print(f"  [{i}/{len(rows)}] skip {r['session_id']}")
            continue
        prompt = list(get_log_simulate_v2(r["phase3_input"]))[0]
        raw, usage, finish, err = "", {}, None, None
        delay = 2.0
        for attempt in range(1, 6):
            try:
                raw, usage, finish = chat(client, model, prompt, max_tokens=2048)
                if raw:
                    break
            except Exception as e:
                err = str(e)
                print(f"    retry {attempt}: {err[:180]}")
                time.sleep(delay)
                delay = min(delay * 2, 60)
        rec = dict(r)
        rec.update({
            "model": model,
            "prompt_fn": "get_log_simulate_v2",
            "raw_response": raw,
            "usage": usage,
            "finish_reason": finish,
            "http_error": err,
        })
        out.append(rec)
        write_jsonl(filled_path, out)
        print(f"  [{i}/{len(rows)}] {r['session_id']} "
              f"tmpl={r['n_unique_templates']} slots={r['n_locked_slots']} "
              f"len={len(raw)} finish={finish}")
        time.sleep(sleep)
    write_jsonl(filled_path, out)
    print(f"[run] wrote {filled_path}")


def extract_locked(slots, filled_by_prefix):
    """Pair each locked slot to GPT-4o via the original Drain template."""
    paired = []
    for s in slots:
        rec = filled_by_prefix.get(s["method_prefix"]) or {}
        text = gpt4o_log_text(rec.get("raw_response") or "")
        lines = split_log_lines(text)
        hit = None
        for line in lines:
            params = match_one_template(line, s["event_template"])
            if params is None:
                continue
            if s["slot_idx"] >= len(params):
                continue
            hit = {
                "line": line,
                "param_value": params[s["slot_idx"]],
                "all_params": params,
            }
            break
        item = {
            "param_id": s["param_id"],
            "method_prefix": s["method_prefix"],
            "event_template": s["event_template"],
            "slot_idx": s["slot_idx"],
            "slot_type": s["slot_type"],
            "deepseek_value": s["param_value"],
            "deepseek_type_valid": s["type_valid"],
            "gpt4o_value": None if hit is None else hit["param_value"],
            "gpt4o_line": None if hit is None else hit["line"],
            "recovered": hit is not None,
        }
        scored_fields = {
            "slot_type": s["slot_type"],
            "event_template": s["event_template"],
            "slot_idx": s["slot_idx"],
        }
        item["deepseek_type_valid"] = score_type_validity({
            **scored_fields, "param_value": s["param_value"],
        })
        if hit is None:
            item["gpt4o_type_valid"] = False
            item["missing"] = True
        else:
            item["gpt4o_type_valid"] = bool(score_type_validity({
                **scored_fields, "param_value": hit["param_value"],
            }))
            item["missing"] = False
        paired.append(item)
    return paired


def classify_missing(paired, filled_by_prefix):
    """Break down the 14 locked slots GPT-4o did not reproduce."""
    from collections import Counter

    buckets = Counter()
    rows = []
    for p in paired:
        if not p.get("missing"):
            continue
        rec = filled_by_prefix.get(p["method_prefix"]) or {}
        text = gpt4o_log_text(rec.get("raw_response") or "")
        tmpl = p["event_template"]
        if "invalidateCorruptReplicas" in tmpl or "processExtraRedundancyBlock" in tmpl:
            reason = "camelcase_wording"
        elif re.search(r"(node-|datanode<\*>)", tmpl) or tmpl.startswith("Datanode "):
            if re.search(r"namenode01", text, re.I):
                reason = "role_prefix_dropped_namenode01"
            else:
                reason = "role_prefix_mismatch"
        else:
            reason = "other_template_drift"
        buckets[reason] += 1
        rows.append({
            "param_id": p["param_id"],
            "method_prefix": p["method_prefix"],
            "event_template": tmpl,
            "slot_idx": p["slot_idx"],
            "slot_type": p["slot_type"],
            "deepseek_value": p["deepseek_value"],
            "reason": reason,
        })
    recovered_hostname = [
        {
            "param_id": p["param_id"],
            "event_template": p["event_template"],
            "slot_idx": p["slot_idx"],
            "gpt4o_value": p["gpt4o_value"],
            "gpt4o_type_valid": p["gpt4o_type_valid"],
        }
        for p in paired
        if p.get("recovered") and p.get("gpt4o_value")
        and re.search(r"(?i)(namenode|datanode)", str(p["gpt4o_value"]))
    ]
    return {
        "n_missing": sum(buckets.values()),
        "by_reason": dict(buckets),
        "missing_rows": rows,
        "recovered_hostname_in_role_slot": recovered_hostname,
        "note": (
            "Missing slots never reach the format checker; they score False so "
            "both models share denominator 144. Role-prefixed nodeid slots "
            "(namenode/datanode/node-/node) now require a numeric suffix; "
            "a recovered 'node-namenode01' is type-invalid."
        ),
    }


def is_block_typed(tmpl, slot_idx):
    parts = tmpl.split("<*>")
    left = parts[slot_idx] if slot_idx < len(parts) else ""
    return bool(BLOCK_LEFT.search(left))


def verdict_from_lines(lines):
    mentions = [normalise(x) for ln in lines for x in block_ids_in(ln)]
    distinct = sorted(set(mentions))
    if len(mentions) < 2:
        return None, mentions, distinct
    return (len(distinct) == 1), mentions, distinct


def summarise_ctx_counts(values):
    n_true = sum(1 for v in values if v is True)
    n_false = sum(1 for v in values if v is False)
    n_none = sum(1 for v in values if v is None)
    dec = n_true + n_false
    return {
        "true": n_true,
        "false": n_false,
        "none": n_none,
        "n_decidable": dec,
        "rate_among_decidable": round(n_true / dec, 4) if dec else None,
        "note": (
            "Deprecated diagnostic. The rule conflates datanode/node ids; "
            "a legal replication pipeline with several datanodes scores False."
        ),
    }


def score_blockid(slots, paired, filled_by):
    """R2.7 block-identifier invariant on the same 15 X12 methods.

    Session-level: ≥2 block mentions, all one id (datanode/node/pool ignored).
    Strict same-slot: the 27 locked slots whose left context is a block prefix;
    GPT-4o missing or no unique session block counts False so the denominator
    stays 27 on both sides.
    """
    keys = [(s["source_file"], s["block_id"]) for s in slots]
    full = build_sessions_from_source(keys)
    sampled = defaultdict(list)
    for s in slots:
        c = (s.get("content") or "").strip()
        if c and c not in sampled[(s["source_file"], s["block_id"])]:
            sampled[(s["source_file"], s["block_id"])].append(c)
    for k, lines in sampled.items():
        full.setdefault(k, lines)

    ds_sess = {}
    for key, lines in full.items():
        v, mentions, distinct = verdict_from_lines(lines)
        ds_sess[key] = {
            "verdict": v,
            "n_mentions": len(mentions),
            "distinct": distinct,
            "n_lines": len(lines),
        }

    gpt_sess = {}
    gpt_lines = {}
    for prefix, rec in filled_by.items():
        lines = split_log_lines(gpt4o_log_text(rec.get("raw_response") or ""))
        v, mentions, distinct = verdict_from_lines(lines)
        gpt_lines[prefix] = lines
        gpt_sess[prefix] = {
            "verdict": v,
            "n_mentions": len(mentions),
            "distinct": distinct,
            "n_lines": len(lines),
        }

    def sess_summary(table):
        dec = [v for v in table.values() if v["verdict"] is not None]
        ok = [v for v in dec if v["verdict"]]
        return {
            "n_sessions": len(table),
            "n_decidable": len(dec),
            "n_pass": len(ok),
            "n_fail": len(dec) - len(ok),
            "n_undecidable": len(table) - len(dec),
            "rate": round(len(ok) / len(dec), 4) if dec else None,
        }

    ds_slot_dec = ds_slot_ok = 0
    for s in slots:
        v = ds_sess[(s["source_file"], s["block_id"])]["verdict"]
        if v is None:
            continue
        ds_slot_dec += 1
        ds_slot_ok += int(v)

    gpt_slot_dec = gpt_slot_ok = 0
    for p in paired:
        v = (gpt_sess.get(p["method_prefix"]) or {}).get("verdict")
        if v is None:
            continue
        gpt_slot_dec += 1
        gpt_slot_ok += int(v)

    ds_strict = gpt_strict = 0
    gpt_miss = gpt_no_block = 0
    strict_rows = []
    n_block = 0
    for p in paired:
        if not is_block_typed(p["event_template"], p["slot_idx"]):
            continue
        n_block += 1
        ds_key = next(
            (s["source_file"], s["block_id"])
            for s in slots
            if s["param_id"] == p["param_id"]
            and s["slot_idx"] == p["slot_idx"]
            and s["event_template"] == p["event_template"]
        )
        ds_dist = ds_sess[ds_key]["distinct"]
        ds_ok = len(ds_dist) == 1 and normalise(str(p["deepseek_value"]).strip()) == ds_dist[0]
        ds_strict += int(ds_ok)

        gpt_dist = (gpt_sess.get(p["method_prefix"]) or {}).get("distinct") or []
        if p.get("missing"):
            gpt_ok = False
            gpt_miss += 1
            reason = "missing_template"
        elif len(gpt_dist) != 1:
            gpt_ok = False
            gpt_no_block += 1
            reason = "no_unique_session_block"
        else:
            gpt_ok = normalise(str(p["gpt4o_value"]).strip()) == gpt_dist[0]
            reason = "ok" if gpt_ok else "value_mismatch"
        gpt_strict += int(gpt_ok)
        if not gpt_ok:
            strict_rows.append({
                "param_id": p["param_id"],
                "event_template": p["event_template"],
                "deepseek_value": p["deepseek_value"],
                "gpt4o_value": p["gpt4o_value"],
                "gpt4o_session_block": gpt_dist,
                "reason": reason,
            })

    gpt_rows = []
    extra = []
    for p in paired:
        rec = filled_by.get(p["method_prefix"]) or {}
        lines = gpt_lines.get(p["method_prefix"]) or []
        gpt_rows.append({
            "source_file": "gpt4o_x12",
            "block_id": p["method_prefix"],
            "content": p.get("gpt4o_line") or (lines[0] if lines else ""),
            "slot_type": p["slot_type"],
            "param_value": p.get("gpt4o_value") or "",
            "event_template": p["event_template"],
            "slot_idx": p["slot_idx"],
        })
    for prefix, lines in gpt_lines.items():
        for ln in lines:
            extra.append({
                "source_file": "gpt4o_x12",
                "block_id": prefix,
                "content": ln,
                "slot_type": "generic",
                "param_value": "",
                "event_template": "",
                "slot_idx": 0,
            })
    gpt_idx = build_block_index(gpt_rows + extra)
    gpt_ctx = [score_ctx_consistency(r, gpt_idx) for r in gpt_rows]
    ds_ctx = [s.get("ctx_consistent") for s in slots]

    return {
        "protocol": (
            "R2.7 invariant: one block id per session. Strict same-slot uses "
            "the 27 locked slots whose left context is blk_/Block/block-/"
            "storedBlock/block; GPT-4o missing or no unique session block = False."
        ),
        "session_level": {
            "deepseek_full_csv": sess_summary(ds_sess),
            "gpt4o_method_fill": sess_summary(gpt_sess),
            "note": (
                "DeepSeek sessions are (source_file, block_id) reconstructed "
                "from the parsed CSVs. GPT-4o sessions are the 15 locked-"
                "template fills, so many have <2 block mentions."
            ),
        },
        "slot_level_inherit": {
            "deepseek": {
                "n_decidable": ds_slot_dec,
                "n_pass": ds_slot_ok,
                "rate": round(ds_slot_ok / ds_slot_dec, 4) if ds_slot_dec else None,
            },
            "gpt4o": {
                "n_decidable": gpt_slot_dec,
                "n_pass": gpt_slot_ok,
                "rate": round(gpt_slot_ok / gpt_slot_dec, 4) if gpt_slot_dec else None,
            },
        },
        "strict_block_typed": {
            "n": n_block,
            "denominator": (
                f"{n_block} locked block-prefix slots; missing / no unique "
                "session block counted False"
            ),
            "deepseek_true": ds_strict,
            "deepseek_rate": round(ds_strict / n_block, 4) if n_block else None,
            "gpt4o_true": gpt_strict,
            "gpt4o_rate": round(gpt_strict / n_block, 4) if n_block else None,
            "n_gpt4o_missing": gpt_miss,
            "n_gpt4o_no_unique_session_block": gpt_no_block,
            "gpt4o_fail_rows": strict_rows,
        },
        "old_ctx_consistent_diagnostic": {
            "deepseek": summarise_ctx_counts(ds_ctx),
            "gpt4o": summarise_ctx_counts(gpt_ctx),
        },
    }


def summarise_paired(paired, label):
    n = len(paired)
    rec = [p for p in paired if p["recovered"]]
    gpt_true = sum(1 for p in paired if p["gpt4o_type_valid"] is True)
    gpt_true_rec = sum(1 for p in rec if p["gpt4o_type_valid"] is True)
    ds_true = sum(1 for p in paired if p["deepseek_type_valid"] is True)
    by_type = defaultdict(lambda: Counter())
    for p in paired:
        by_type[p["slot_type"]]["n"] += 1
        by_type[p["slot_type"]]["ds_true"] += int(p["deepseek_type_valid"] is True)
        by_type[p["slot_type"]]["gpt_true"] += int(p["gpt4o_type_valid"] is True)
        by_type[p["slot_type"]]["recovered"] += int(p["recovered"])
        by_type[p["slot_type"]]["missing"] += int(p["missing"])
    return {
        "label": label,
        "n": n,
        "deepseek_true": ds_true,
        "deepseek_type_validity": round(ds_true / n, 4) if n else None,
        "gpt4o_true_over_144": gpt_true,
        "gpt4o_type_validity": round(gpt_true / n, 4) if n else None,
        "n_recovered": len(rec),
        "n_missing": n - len(rec),
        "gpt4o_true_among_recovered": gpt_true_rec,
        "gpt4o_recovered_validity": round(gpt_true_rec / len(rec), 4) if rec else None,
        "by_type": {
            st: {
                "n": c["n"],
                "deepseek_true": c["ds_true"],
                "gpt4o_true": c["gpt_true"],
                "recovered": c["recovered"],
                "missing": c["missing"],
                "gpt4o_rate": round(c["gpt_true"] / c["n"], 4) if c["n"] else None,
                "deepseek_rate": round(c["ds_true"] / c["n"], 4) if c["n"] else None,
            }
            for st, c in sorted(by_type.items())
        },
    }


def score(filled_path, out_name="compare.json", label="same_slot_locked_templates"):
    sessions, slots = locked_slots()
    filled = read_jsonl(filled_path) if os.path.exists(filled_path) else []
    filled_by = {r["session_id"]: r for r in filled}
    paired = extract_locked(slots, filled_by)
    report = {
        "protocol": {
            "same_slot": True,
            "n_locked": 144,
            "n_methods": len(sessions),
            "denominator": "144 DeepSeek type-decidable slots; GPT-4o missing = False",
            "nodeid_rule": (
                "role prefix namenode/datanode/node-/node already in the template: "
                "slot value must be digits, not a hostname"
            ),
            "n_gpt4o_ok": sum(
                1 for r in filled
                if r.get("finish_reason") == "stop" and r.get("raw_response")
            ),
            "filled_path": os.path.relpath(filled_path, REPO),
        },
        "matched_n_144": summarise_paired(paired, label),
        "missing_audit": classify_missing(paired, filled_by),
        "blockid_consistency": score_blockid(slots, paired, filled_by),
    }
    os.makedirs(OUTDIR, exist_ok=True)
    out = os.path.join(OUTDIR, out_name)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    paired_path = os.path.join(OUTDIR, out_name.replace(".json", "_paired.jsonl"))
    write_jsonl(paired_path, paired)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"wrote {out}")
    print(f"wrote {paired_path}")
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["build", "run", "score", "score-old", "all"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--sleep", type=float, default=1.0)
    args = ap.parse_args()
    if args.step in ("build", "all"):
        build()
    if args.step in ("run", "all"):
        if not os.path.exists(SLOT_SESS):
            build()
        run(args.model, args.sleep)
    if args.step in ("score", "all"):
        score(os.path.join(OUTDIR, "filled.jsonl"), "compare.json",
              "same_slot_gpt4o_locked_templates")
    if args.step == "score-old":
        score(OLD_FILLED, "compare_old_same_prompt.json",
              "locked_extract_from_previous_same_prompt_fill")


if __name__ == "__main__":
    main()
