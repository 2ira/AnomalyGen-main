#!/usr/bin/env python3
"""Phase III API fill for ctx v2 sessions (get_log_simulate_v2, generation prompt)."""
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

    rows = read_jsonl(os.path.join(EVAL_DATA_DIR, "ctx_v2_sessions.jsonl"))
    if args.limit:
        rows = rows[: args.limit]
    out_dir = os.path.join(EVAL_RESULT_DIR, "ctx_v2")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "filled.jsonl")

    done = {}
    if os.path.exists(out):
        for r in read_jsonl(out):
            if r.get("session_id") and r.get("raw_response") and r.get("finish_reason") == "stop":
                done[r["session_id"]] = r

    client, model, base = openai_client()
    print(f"ctx_v2 n={len(rows)} done={len(done)} model={model} base={base}")
    ordered = []
    for i, sess in enumerate(rows):
        sid = sess["session_id"]
        if sid in done:
            ordered.append(done[sid])
            continue
        prompt = list(get_log_simulate_v2(sess["phase3_input"]))[0]
        print(f"  [{i+1}/{len(rows)}] {sid} ph={sess['n_block_placeholders']}")
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
            **{k: v for k, v in sess.items() if k != "phase3_input"},
            "prompt_fn": "get_log_simulate_v2",
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
