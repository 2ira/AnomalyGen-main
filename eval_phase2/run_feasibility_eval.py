#!/usr/bin/env python3
"""
Path-feasibility evaluation: CoT vs no-CoT on the 40-merge-point benchmark.

Reads feasibility_manual.jsonl, calls the AnomalyGen merge prompt (CoT or
no-CoT variant), and computes ACC / F1 / per-stratum breakdown.

Usage:
    cd AnomalyGen-main
    python eval_phase2/run_feasibility_eval.py --variant cot   [--sleep 0.3]
    python eval_phase2/run_feasibility_eval.py --variant nocot [--sleep 0.3]
    python eval_phase2/run_feasibility_eval.py --report
"""
import os
import sys
import re
import json
import argparse
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from models.prompts.merge_node_info import (
    get_merge_nodes_by_llm_v7,
    get_merge_nodes_by_llm_without_cot,
)
from models.get_resp import get_response
from common import read_jsonl, write_jsonl, parse_merge_xml, EVAL_DATA_DIR, EVAL_RESULT_DIR

os.makedirs(EVAL_RESULT_DIR, exist_ok=True)
DATASET = os.path.join(EVAL_DATA_DIR, "feasibility_manual.jsonl")


# Leakage markers that were written into infeasible twins and concatenated
# into the prompt by run_one().  Strip them so the model cannot read the GT.
_LEAK = re.compile(
    r"\[INFEASIBLE\]|//\s*INFEASIBLE:[^\n]*|_conflict:[^\n]*",
    re.IGNORECASE,
)


def _sanitize(text: str) -> str:
    if not text:
        return text
    return _LEAK.sub("", text)


# ── Feasibility decision ────────────────────────────────────────────────
def is_feasible(message):
    """Per-merge-point verdict.  Truncation-robust.

    Rule: the *first* <eval>true|false</eval> in the response is the
    decision for the path being asked about.  This does not short-circuit
    on any later true (the old `if has_true: return True` accepted a merge
    point as soon as any sibling path was marked valid).

    Fallback if no <eval> tag survives: empty valid_paths + nonempty
    pruned/wrong_path → infeasible; nonempty valid_paths → feasible.
    """
    if not message:
        return None
    m = re.search(r"<eval>\s*(true|false)\s*</eval>", message, re.IGNORECASE)
    if m:
        return m.group(1).lower() == "true"
    valid, pruned = parse_merge_xml(message)
    if pruned and not valid:
        return False
    if valid:
        return True
    return None


# Eval-only prompt edits (do not change generation templates):
# CoT few-shot <eval>true</eval> -> [true/false]; strip no-CoT <pruned_paths>.
def _eval_prompts(parent_info, child_info, variant):
    gen = (get_merge_nodes_by_llm_v7 if variant == "cot"
           else get_merge_nodes_by_llm_without_cot)
    prompt = list(gen(parent_info, child_info))[0]
    if variant == "cot":
        prompt = prompt.replace("<eval>true</eval>", "<eval>[true/false]</eval>", 1)
    else:
        prompt = re.sub(
            r"\n\s*<pruned_paths>.*?</pruned_paths>",
            "",
            prompt,
            count=1,
            flags=re.DOTALL,
        )
    return [prompt]


def _openai_client():
    from openai import OpenAI
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("OPENAI_API_KEY is not set")
    base = os.environ.get("OPENAI_BASE_URL", "https://api.chatanywhere.tech/v1")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o")
    timeout = float(os.environ.get("OPENAI_TIMEOUT", "180"))
    client = OpenAI(api_key=key, base_url=base, max_retries=0, timeout=timeout)
    return client, model


def _call_llm(prompts, client, model, max_tokens=8192):
    """Single-shot chat completion. Caller handles retries."""
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompts[0]}],
        temperature=0,
        max_tokens=max_tokens,
    )
    text = (resp.choices[0].message.content or "") if resp.choices else ""
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    if resp.usage:
        usage = {
            "prompt_tokens": resp.usage.prompt_tokens or 0,
            "completion_tokens": resp.usage.completion_tokens or 0,
            "total_tokens": resp.usage.total_tokens or 0,
        }
    return text, usage


def _is_success(row):
    raw = row.get("raw_response") or ""
    if row.get("error"):
        return False
    if not raw or raw.startswith("Error:"):
        return False
    # Truncated archive copies are exactly 500 chars and lack a closing tag.
    if len(raw) == 500 and "</merge_result>" not in raw and "</valid_paths>" not in raw:
        return False
    return True


def _atomic_write_jsonl(path, rows):
    tmp = path + ".tmp"
    write_jsonl(tmp, rows)
    os.replace(tmp, path)


# ── LLM invocation ──────────────────────────────────────────────────────
def run_one(mp, variant, client=None, model=None, retries=6):
    parent_info = ("node name is " + mp["caller"]
                   + " node log is " + _sanitize(str(mp.get("caller_log", "")))
                   + " source code: " + _sanitize(str(mp.get("caller_code", ""))))
    child_info = ("node name is " + mp["callee"]
                  + " node log is " + _sanitize(str(mp.get("callee_log", "")))
                  + " source code: " + _sanitize(str(mp.get("callee_code", ""))))

    prompts = _eval_prompts(parent_info, child_info, variant)
    last_err = None
    raw, usage = "", {}
    if client is None:
        # Legacy path through get_response (no per-call retry / usage).
        raw = get_response(prompts)
        usage = {}
    else:
        delay = 2.0
        for attempt in range(1, retries + 1):
            try:
                raw, usage = _call_llm(prompts, client, model)
                if raw and not raw.startswith("Error:"):
                    break
                last_err = raw or "empty response"
            except Exception as e:
                last_err = str(e)
                print(f"    retry {attempt}/{retries}: {last_err[:200]}")
                if attempt == retries:
                    raw = ""
                    break
                time.sleep(delay)
                delay = min(delay * 2, 60)
            else:
                if attempt < retries and (not raw or raw.startswith("Error:")):
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                break

    pred = is_feasible(raw) if raw else None
    row = {
        "mp_id": mp["mp_id"],
        "variant": variant,
        "gt": mp["gt"],
        "pred_feasible": pred,
        "stratum": mp.get("stratum", "simple"),
        "raw_response": raw,
        "usage": usage,
    }
    if last_err and not raw:
        row["error"] = last_err
    return row


# ── Metrics ──────────────────────────────────────────────────────────────
def binary_metrics(rows):
    tp = fp = tn = fn = err = 0
    for r in rows:
        if r["pred_feasible"] is None:
            err += 1
            continue
        gt_pos = (r["gt"] == "valid")
        if gt_pos and r["pred_feasible"]:
            tp += 1
        elif gt_pos and not r["pred_feasible"]:
            fn += 1
        elif not gt_pos and r["pred_feasible"]:
            fp += 1
        else:
            tn += 1
    n = tp + fp + tn + fn
    return {
        "N": n, "TP": tp, "FP": fp, "TN": tn, "FN": fn,
        "parse_errors": err,
        "PC": round(tp / (tp + fp), 4) if (tp + fp) else 0,
        "RC": round(tp / (tp + fn), 4) if (tp + fn) else 0,
        "ACC": round((tp + tn) / n, 4) if n else 0,
        "F1": round(2 * tp / (2 * tp + fp + fn), 4) if (2 * tp + fp + fn) else 0,
    }


# ── Report generation ───────────────────────────────────────────────────
def generate_report():
    report = {}
    for v in ["cot", "nocot"]:
        p = os.path.join(EVAL_RESULT_DIR, f"feasibility_pred_{v}.jsonl")
        if not os.path.exists(p):
            continue
        rows = read_jsonl(p)
        report[v] = binary_metrics(rows)
        for s in ["simple", "complex"]:
            srows = [r for r in rows if r.get("stratum") == s]
            if srows:
                report[f"{v}_{s}"] = binary_metrics(srows)

    if not report:
        print("No prediction files found. Run --variant cot/nocot first.")
        return

    header = f"{'Variant':<15} {'N':>4} {'PC':>8} {'RC':>8} {'ACC':>8} {'F1':>8} {'FP':>4}"
    sep = "-" * 55
    print(f"\n===== Path Feasibility Comparison =====")
    print(header)
    print(sep)
    for v in ["cot", "nocot"]:
        m = report.get(v, {})
        print(f"{v:<15} {m.get('N',0):>4} {m.get('PC',0):>8.4f} "
              f"{m.get('RC',0):>8.4f} {m.get('ACC',0):>8.4f} "
              f"{m.get('F1',0):>8.4f} {m.get('FP',0):>4}")

    for stratum in ["simple", "complex"]:
        print(f"\n  {stratum.capitalize()} cases:")
        for v in ["cot", "nocot"]:
            m = report.get(f"{v}_{stratum}", {})
            if m:
                print(f"    {v:<12} ACC={m.get('ACC',0):.4f}  "
                      f"F1={m.get('F1',0):.4f}")

    out = os.path.join(EVAL_RESULT_DIR, "feasibility_comparison.json")
    with open(out, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved: {out}")


def _load_resume(out_path):
    """Keep successful rows; retry truncated archives, errors, and empty replies."""
    done = {}
    if not os.path.exists(out_path):
        return done
    for row in read_jsonl(out_path):
        mp_id = row.get("mp_id")
        if mp_id and _is_success(row):
            done[mp_id] = row
    return done


# ── Main ─────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=["cot", "nocot"])
    ap.add_argument("--report", action="store_true",
                    help="Generate comparison report from existing results")
    ap.add_argument("--sleep", type=float, default=1.5,
                    help="Delay between LLM calls (seconds)")
    ap.add_argument("--no-resume", action="store_true",
                    help="Ignore existing prediction file and rerun all ids")
    args = ap.parse_args()

    if args.report:
        generate_report()
        return

    if not args.variant:
        ap.error("Specify --variant cot|nocot or --report")

    if not os.path.exists(DATASET):
        sys.exit(f"Dataset not found: {DATASET}\n"
                 f"Run build_feasibility_dataset.py first.")

    rows = read_jsonl(DATASET)
    out = os.path.join(EVAL_RESULT_DIR, f"feasibility_pred_{args.variant}.jsonl")
    done = {} if args.no_resume else _load_resume(out)
    pending = [mp for mp in rows if mp["mp_id"] not in done]
    print(f"Running {args.variant}: {len(rows)} merge points "
          f"({len(done)} done, {len(pending)} pending)")

    client, model = _openai_client()
    results_by_id = dict(done)
    usage_tot = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def _flush():
        ordered = []
        for mp in rows:
            if mp["mp_id"] in results_by_id:
                ordered.append(results_by_id[mp["mp_id"]])
        _atomic_write_jsonl(out, ordered)
        return ordered

    for i, mp in enumerate(pending):
        print(f"  [{i+1}/{len(pending)}] {mp['mp_id'][:70]}")
        try:
            row = run_one(mp, args.variant, client=client, model=model)
        except Exception as e:
            print(f"    ERROR (continuing): {e}")
            row = {
                "mp_id": mp["mp_id"], "variant": args.variant,
                "gt": mp["gt"], "pred_feasible": None,
                "stratum": mp.get("stratum", "simple"),
                "error": str(e), "raw_response": "",
            }
        u = row.get("usage") or {}
        for k in usage_tot:
            usage_tot[k] += u.get(k, 0)
        results_by_id[mp["mp_id"]] = row
        _flush()
        pred = row.get("pred_feasible")
        print(f"    pred={pred} raw_len={len(row.get('raw_response') or '')}")
        time.sleep(args.sleep)

    # Second pass: retry remaining failures without aborting the job.
    failed = [mp for mp in rows if not _is_success(results_by_id.get(mp["mp_id"], {}))]
    if failed:
        print(f"Retrying {len(failed)} failed ids...")
        for i, mp in enumerate(failed):
            print(f"  retry [{i+1}/{len(failed)}] {mp['mp_id'][:70]}")
            try:
                row = run_one(mp, args.variant, client=client, model=model, retries=8)
            except Exception as e:
                print(f"    ERROR (continuing): {e}")
                row = results_by_id.get(mp["mp_id"], {
                    "mp_id": mp["mp_id"], "variant": args.variant,
                    "gt": mp["gt"], "pred_feasible": None, "error": str(e),
                })
                row["error"] = str(e)
            u = row.get("usage") or {}
            for k in usage_tot:
                usage_tot[k] += u.get(k, 0)
            results_by_id[mp["mp_id"]] = row
            _flush()
            time.sleep(args.sleep)

    results = _flush()
    still_failed = [r["mp_id"] for r in results if not _is_success(r)]
    m = binary_metrics(results)
    usage_path = os.path.join(EVAL_RESULT_DIR, f"x1_usage_{args.variant}.json")
    with open(usage_path, "w") as f:
        json.dump({"variant": args.variant, "model": model, **usage_tot,
                   "n_success": sum(1 for r in results if _is_success(r)),
                   "failed_ids": still_failed}, f, indent=2)
    print(f"\nDone. {len(results)} predictions -> {out}")
    print(f"  ACC={m['ACC']}, F1={m['F1']}, parse_errors={m['parse_errors']}")
    print(f"  tokens={usage_tot} failed={still_failed}")
    print(f"  Run '--report' for full comparison after both variants.")


if __name__ == "__main__":
    main()
