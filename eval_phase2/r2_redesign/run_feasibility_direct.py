#!/usr/bin/env python3
"""X1b: CoT vs no-CoT on path feasibility, asked as a feasibility question.

The archived X1 harness prompted with the production *merge* templates
(get_merge_nodes_by_llm_v7 / _without_cot) and then read the first <eval> as a
feasibility verdict. Those templates are asked to produce a merged path set, so
they always emit at least one accepted path and the verdict degenerates to
accept-all for both arms. That measures the prompt, not the verifier.

Here both arms are asked the actual question -- can this caller path reach this
callee? -- and differ only in whether reasoning is requested before the verdict.
Inputs, sanitisation and ground truth are identical to run_feasibility_eval.py.

    export OPENAI_API_KEY=...
    python3 run_feasibility_direct.py run --variant cot
    python3 run_feasibility_direct.py run --variant nocot
    python3 run_feasibility_direct.py score
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
sys.path.insert(0, EVAL)
sys.path.insert(0, HERE)

from llm_client import openai_client, chat  # noqa: E402

DATASET = os.path.join(EVAL, "eval_data", "feasibility_manual.jsonl")
OUTDIR = os.path.join(EVAL, "eval_results", "x1b_direct")

# Ground-truth markers written into the infeasible twins; identical to X1.
_LEAK = re.compile(r"\[INFEASIBLE\]|//\s*INFEASIBLE:[^\n]*|_conflict:[^\n]*", re.IGNORECASE)

_SHARED = """You are analysing a Java call site to decide whether one specific
execution path through the caller can actually reach the callee.

[CALLER] {caller}
[CALLER LOG STATEMENTS]
{caller_log}
[CALLER SOURCE]
{caller_code}

[CALLEE] {callee}
[CALLEE LOG STATEMENTS]
{callee_log}
[CALLEE SOURCE]
{callee_code}

Decide whether the caller can reach the callee on some concrete execution.
Treat the merge as INFEASIBLE only when the caller's guarding conditions and
the callee's entry conditions are in definite conflict, when a required value
cannot be produced on that path, or when the call is unreachable. If no
definite conflict can be established, the merge is FEASIBLE."""

# Neutral framing. The two variants above inherit the generation pipeline's
# own conservative rule ("possible conflicts are considered as non-conflicts"),
# which defaults to feasible, and they present the caller path trace under a
# "LOG STATEMENTS" heading. This variant names the trace as the path under
# test, asks explicitly whether the call site is reached on it, and states no
# default verdict, so a persistent accept-all cannot be blamed on framing.
_NEUTRAL = """You are analysing one specific execution path through a Java caller
to decide whether that path actually reaches a call to the callee.

[CALLER] {caller}
[CALLER EXECUTION PATH UNDER TEST -- ordered trace of this one path]
{caller_log}
[CALLER SOURCE]
{caller_code}

[CALLEE] {callee}
[CALLEE EXECUTION TRACE]
{callee_log}
[CALLEE SOURCE]
{callee_code}

The question is about the traced path only, not about whether the callee is
reachable in general. The path is INFEASIBLE if, on this trace, control never
arrives at the call (for example it throws, returns or exits first), if the
callee's entry guard sends it straight back out given the state the trace
establishes, or if the trace's conditions contradict the callee's. It is
FEASIBLE if control reaches the call and the callee executes its body.

Both verdicts are equally likely a priori; roughly a third of the cases in this
set are infeasible. Do not prefer one verdict when the evidence is unclear."""

PROMPT = {
    "cot_neutral": _NEUTRAL + """

Work through it step by step before answering:
1. Walk the caller trace in order and say where control goes.
2. State whether the call to the callee is reached on that trace, and why.
3. If it is reached, check the callee's entry guard against the state the trace
   establishes, and check for contradicting conditions.
4. Conclude.

Write your reasoning, then end with exactly one line:
<verdict>feasible</verdict> or <verdict>infeasible</verdict>""",
    "nocot_neutral": _NEUTRAL + """

Answer immediately with no explanation and no reasoning. Output exactly one
line and nothing else:
<verdict>feasible</verdict> or <verdict>infeasible</verdict>""",
    "cot": _SHARED + """

Work through it step by step before answering:
1. State the control-flow conditions guarding the call site in the caller.
2. State the entry conditions and early returns of the callee.
3. Check those two sets for a definite conflict, and check that any value the
   callee requires can be produced on the caller's path.
4. Conclude.

Write your reasoning, then end with exactly one line:
<verdict>feasible</verdict> or <verdict>infeasible</verdict>""",
    "nocot": _SHARED + """

Answer immediately with no explanation and no reasoning. Output exactly one
line and nothing else:
<verdict>feasible</verdict> or <verdict>infeasible</verdict>""",
}


def read_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def sanitize(text):
    return _LEAK.sub("", str(text or ""))


def build_prompt(mp, variant):
    return PROMPT[variant].format(
        caller=mp["caller"], callee=mp["callee"],
        caller_log=sanitize(mp.get("caller_log")),
        caller_code=sanitize(mp.get("caller_code")),
        callee_log=sanitize(mp.get("callee_log")),
        callee_code=sanitize(mp.get("callee_code")),
    )


def parse_verdict(text):
    """Last <verdict> wins: CoT may quote the options while reasoning."""
    hits = re.findall(r"<verdict>\s*(feasible|infeasible)\s*</verdict>", text or "", re.I)
    if hits:
        return hits[-1].lower() == "feasible"
    bare = re.findall(r"\b(infeasible|feasible)\b", text or "", re.I)
    return bare[-1].lower() == "feasible" if bare else None


def run(variant, sleep):
    rows = read_jsonl(DATASET)
    client, model, base = openai_client()
    out_path = os.path.join(OUTDIR, f"pred_{variant}.jsonl")
    print(f"[{variant}] {len(rows)} merge points -> {model} @ {base}")

    results = []
    for i, mp in enumerate(rows, 1):
        raw, usage, finish = chat(client, model, build_prompt(mp, variant), max_tokens=2048)
        rec = {
            "mp_id": mp["mp_id"], "variant": variant, "model": model,
            "gt": mp["gt"], "stratum": mp.get("stratum", "simple"),
            "pred_feasible": parse_verdict(raw), "raw_response": raw,
            "usage": usage, "finish_reason": finish,
        }
        results.append(rec)
        write_jsonl(out_path, results)
        print(f"  [{i}/{len(rows)}] {mp['mp_id'][:58]:<58} "
              f"gt={mp['gt']:<10} pred={rec['pred_feasible']} len={len(raw)}")
        time.sleep(sleep)
    print(f"[{variant}] wrote {out_path}")


def block(c):
    n = sum(c.values())
    correct = c["TP"] + c["TN"]
    rec = c["TP"] / max(1, c["TP"] + c["FN"])
    spec = c["TN"] / max(1, c["TN"] + c["FP"])
    return {"n": n, "TP": c["TP"], "TN": c["TN"], "FP": c["FP"], "FN": c["FN"],
            "unparsed": c["unparsed"],
            "accuracy": round(correct / n, 4) if n else None,
            "recall_feasible": round(rec, 4),
            "specificity_infeasible": round(spec, 4),
            "balanced_accuracy": round((rec + spec) / 2, 4)}


def score():
    report = {}
    for variant in PROMPT:
        path = os.path.join(OUTDIR, f"pred_{variant}.jsonl")
        if not os.path.exists(path):
            print(f"missing {path}")
            continue
        rows = read_jsonl(path)
        cells, strata = Counter(), defaultdict(Counter)
        for r in rows:
            truth = r["gt"] == "valid"
            p = r["pred_feasible"]
            cell = "unparsed" if p is None else (("TP" if p else "FN") if truth else ("FP" if p else "TN"))
            cells[cell] += 1
            strata[r["stratum"]][cell] += 1
        lens = [len(r.get("raw_response") or "") for r in rows]
        report[variant] = {
            "model": rows[0].get("model"), "n": len(rows),
            "mean_response_chars": round(sum(lens) / len(lens)),
            "overall": block(cells),
            **{s: block(c) for s, c in strata.items()},
        }
    out = os.path.join(OUTDIR, "scores.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    print("\n===== X1b: feasibility asked as a feasibility question =====")
    for variant, d in report.items():
        o = d["overall"]
        print(f"\n{variant}  (model {d['model']}, mean {d['mean_response_chars']} chars)")
        print(f"  overall  acc={o['accuracy']:.4f}  TP={o['TP']} TN={o['TN']} "
              f"FP={o['FP']} FN={o['FN']} unparsed={o['unparsed']}")
        print(f"           specificity={o['specificity_infeasible']:.4f}  "
              f"balanced_acc={o['balanced_accuracy']:.4f}")
        for s in ("simple", "complex"):
            if s in d:
                b = d[s]
                print(f"  {s:<8} acc={b['accuracy']:.4f}  n={b['n']}  "
                      f"TN={b['TN']}/{b['TN']+b['FP']}")
    print(f"\nwrote {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["run", "score"])
    ap.add_argument("--variant", choices=list(PROMPT))
    ap.add_argument("--sleep", type=float, default=0.4)
    a = ap.parse_args()
    if a.step == "score":
        score()
    else:
        if not a.variant:
            ap.error("run needs --variant " + "|".join(PROMPT))
        run(a.variant, a.sleep)


if __name__ == "__main__":
    main()
