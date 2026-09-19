#!/usr/bin/env python3
"""GPT-4o Phase III fill of archived unfilled merge templates (X7).

Does not overwrite DeepSeek artifacts (baseline_compressed_log.json, parsed CSVs).
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.dirname(HERE)
REPO = os.path.dirname(EVAL)
sys.path.insert(0, HERE)
sys.path.insert(0, EVAL)
sys.path.insert(0, REPO)

from common import read_jsonl, write_jsonl, EVAL_DATA_DIR, EVAL_RESULT_DIR  # noqa: E402
from models.prompts.standard_log import get_log_simulate_v2  # noqa: E402
from llm_client import openai_client, chat  # noqa: E402


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rows = read_jsonl(os.path.join(EVAL_DATA_DIR, "x7_sessions.jsonl"))
    if args.limit:
        rows = rows[: args.limit]
    out_dir = os.path.join(EVAL_RESULT_DIR, "x7_gpt4o")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "filled.jsonl")

    done = {}
    if os.path.exists(out):
        for r in read_jsonl(out):
            if r.get("session_id") and r.get("raw_response") and r.get("finish_reason") == "stop":
                done[r["session_id"]] = r

    client, model, base = openai_client()
    print(f"x7 n={len(rows)} done={len(done)} model={model} base={base}")
    ordered = []
    for i, sess in enumerate(rows):
        sid = sess["session_id"]
        if sid in done:
            ordered.append(done[sid])
            continue
        prompt = list(get_log_simulate_v2(sess["phase3_input"]))[0]
        print(f"  [{i+1}/{len(rows)}] {sid} {sess['method'][:72]}")
        raw, usage, finish, err = "", {}, None, None
        delay = 2.0
        for attempt in range(1, 6):
            try:
                raw, usage, finish = chat(client, model, prompt, max_tokens=4096)
                if raw:
                    break
            except Exception as e:
                err = str(e)
                print(f"    retry {attempt}: {err[:180]}")
                time.sleep(delay)
                delay = min(delay * 2, 60)
        row = {
            "session_id": sid,
            "method": sess["method"],
            "corpus": sess.get("corpus"),
            "merge_file": sess.get("merge_file"),
            "deepseek_keys": sess.get("deepseek_keys") or [],
            "deepseek_logs": sess.get("deepseek_logs") or [],
            "prompt_fn": "get_log_simulate_v2",
            "model": model,
            "raw_response": raw,
            "usage": usage,
            "finish_reason": finish,
            "http_error": err,
        }
        ordered.append(row)
        write_jsonl(out, ordered)
        print(f"    len={len(raw)} finish={finish}")
        time.sleep(args.sleep)
    write_jsonl(out, ordered)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
