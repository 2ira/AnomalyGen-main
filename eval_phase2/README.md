# eval_phase2 — Phase II Direct Evaluation (M.3 / R1.3)

Directly evaluates AnomalyGen's Phase II on **path feasibility** (CoT vs no-CoT)
and **parameter-generation quality**. Complements `eval_labeling/` (label accuracy).

R2 numbers below supersede the original `metrics.json` / truncated jsonl.
Do not cite CoT 85% or type validity 162/163.

## Current results (R2)

| Check | Number | Where |
|---|---|---|
| Feasibility X1 (untruncated gpt-4o, first `<eval>`) | CoT = no-CoT = **26/40 = 65%**, TN=0 | `eval_results/x1_rerun/` |
| Feasibility CoT v2 (generation prompt v7, every `<eval>`) | still accept-all, balanced accuracy **0.5** | `eval_results/feasibility_v2/` |
| Archived truncated jsonl (every `raw_response` length 500) | evidence only | `eval_results/archive_truncated_500/` and the two live `feasibility_pred_*.jsonl` |
| Type validity | **172/183 = 0.940** (24 generic excluded; 10 Drain splits count as failures) | `eval_data/param_scored.jsonl` |
| 24 generic slots | listed, not “44 undeterminable” | `r2_redesign/generic_slots_24.md` |
| Block-id consistency (archived corpus, same 207-slot sample) | **4/4** sessions; appendix 59/73 = 80.8% | `run_blockid_consistency.py` |
| Ctx v2 (GPT-4o Phase III refill) | **3/10 = 30%** | `eval_results/ctx_v2/` |
| X7 GPT-4o vs archived DeepSeek-V3 fill | 0.971 vs 0.985 type validity; not the same 207 Drain ids | `eval_results/x7_gpt4o/` |
| **X12 same-slot** (R2.12 headline) | type-valid **141/144 vs 127/144**; block-id strict **26/27 vs 19/27**. DeepSeek is the stronger fill model. | `eval_results/x12_same_slot/compare.json` |
| X2 Deep-Loglizer Table 5 reruns | lstm-sequentials w/o analysis **0.958/0.996/0.923**; lstm-next_log **0.916/0.942/0.891**; lstm-semantic-next_log **0.766/0.632/0.974** (the copied cell); transformer-semantic **0.697** kept as genuine | `eval_results/x2_deeploglizer/` (repo root) |

`simple`/`complex` in `feasibility_manual.jsonl` is an **author-assigned** stratum, not `common.py::stratum_of`.

## Layout

```
eval_phase2/
├── run_feasibility_eval.py       # X1 protocol (first <eval>)
├── run_param_eval.py             # type-validity regexes
├── run_blockid_consistency.py    # session-level block-id invariant (replaces old ctx_consistent)
├── r2_redesign/                  # CoT v2, ctx v2, X7, X12 same-slot, generic-slot export
├── eval_data/
└── eval_results/
```

Rebuild protocol: `r2_redesign/PROTOCOL.md`. Key from `OPENAI_API_KEY` only; never write it to `config.json`.

Same-slot refill: `python3 r2_redesign/run_x12_same_slot.py {build,run,score}`. Scoring does not call the API; `score` reads `eval_results/x12_same_slot/filled.jsonl`.
