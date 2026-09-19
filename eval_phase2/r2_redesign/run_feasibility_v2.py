#!/usr/bin/env python3
"""Run CoT feasibility v2 with the generation prompt (get_merge_nodes_by_llm_v7).

    cd AnomalyGen-main
    OPENAI_API_KEY=... OPENAI_BASE_URL=https://api.chatanywhere.tech/v1 \\
      python3 eval_phase2/r2_redesign/run_feasibility_v2.py --variant cot
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
from models.prompts.merge_node_info import (  # noqa: E402
    get_merge_nodes_by_llm_v7,
    get_merge_nodes_by_llm_without_cot,
)
from llm_client import openai_client, chat  # noqa: E402
from score_feasibility_v2 import parse_evals  # noqa: E402


def make_prompt(mp, variant):
    parent, child = mp["parent_info"], mp["child_info"]
    if variant == "cot":
        return list(get_merge_nodes_by_llm_v7(parent, child))[0]
    return list(get_merge_nodes_by_llm_without_cot(parent, child))[0]


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=["cot", "nocot"], default="cot")
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    data = os.path.join(EVAL_DATA_DIR, "feasibility_v2.jsonl")
    rows = read_jsonl(data)
    if args.limit:
        rows = rows[: args.limit]
    out_dir = os.path.join(EVAL_RESULT_DIR, "feasibility_v2")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"pred_{args.variant}.jsonl")

    done = {}
    if os.path.exists(out):
        for r in read_jsonl(out):
            if r.get("mp_id") and r.get("raw_response") and r.get("finish_reason") == "stop":
                done[r["mp_id"]] = r

    client, model, base = openai_client()
    print(f"{args.variant} n={len(rows)} done={len(done)} model={model} base={base}")
    print("prompt=get_merge_nodes_by_llm_v7 (unmodified)" if args.variant == "cot"
          else "prompt=get_merge_nodes_by_llm_without_cot (unmodified)")

    ordered = []
    for i, mp in enumerate(rows):
        if mp["mp_id"] in done:
            ordered.append(done[mp["mp_id"]])
            continue
        prompt = make_prompt(mp, args.variant)
        # Generation-identical: do not rewrite <eval>true</eval> or strip tags.
        print(f"  [{i+1}/{len(rows)}] {mp['mp_id'][:72]}")
        raw, usage, finish = "", {}, None
        err = None
        delay = 2.0
        for attempt in range(1, 6):
            try:
                raw, usage, finish = chat(client, model, prompt, max_tokens=8192)
                if raw:
                    break
            except Exception as e:
                err = str(e)
                print(f"    retry {attempt}: {err[:180]}")
                time.sleep(delay)
                delay = min(delay * 2, 60)
        parsed = parse_evals(raw)
        row = {
            "mp_id": mp["mp_id"],
            "variant": args.variant,
            "gt": mp["gt"],
            "stratum": mp.get("stratum", "simple"),
            "raw_response": raw,
            "usage": usage,
            "finish_reason": finish,
            "http_error": err,
            "prompt_fn": "get_merge_nodes_by_llm_v7" if args.variant == "cot"
            else "get_merge_nodes_by_llm_without_cot",
            "prompt_chars": len(prompt),
            **parsed,
        }
        ordered.append(row)
        write_jsonl(out, ordered)
        print(f"    pred_feasible={parsed['pred_feasible']} "
              f"evals={parsed['n_eval_true']}t/{parsed['n_eval_false']}f "
              f"len={len(raw)} finish={finish}")
        time.sleep(args.sleep)

    write_jsonl(out, ordered)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
