# R2 redesigned experiments (traceable)

This directory **does not modify** generation prompts or the archived X1 run.
Old artifacts stay at `eval_results/archive_truncated_500/` and `eval_results/x1_rerun/`.

Paper generation CoT = `models.prompts.merge_node_info.get_merge_nodes_by_llm_v7`
(called from `main/merge_node.py`). Phase III fill = `get_log_simulate_v2`.

## CoT feasibility v2 (fixes the five eval bugs)

| # | Old eval bug | v2 |
|---|---|---|
| 1 | Infeasible twins leaked `[INFEASIBLE]`, `_conflict:`, `// INFEASIBLE:` | Same 40 CFG conflicts, leak tokens stripped; logs wrapped as generation-style XML. Reasons stay in `infeasible_reason` (never sent). |
| 2 | Eval harness replaced few-shot `<eval>true</eval>` | **No edit.** v7 is used byte-identical to generation. The output-spec example still shows `true` because that is the paper prompt. |
| 3 | Verdict = first `<eval>` only | Score **every** `<eval>` under `<valid_paths>` plus `<wrong_path>` entries. Merge-point feasible iff ≥1 `eval=true` in `valid_paths`. Primary metrics: TPR/TNR/balanced accuracy (accept-all is TNR=0, not “65% reasoning”). |
| 4 | Complex n=12 treated as a test | Keep N=40 for comparability; complex stratum is **descriptive only**. Lead with balanced accuracy. |
| 5 | Eval prompt ≠ generation prompt | CoT calls `get_merge_nodes_by_llm_v7` with the same `parent_info` / `child_info` concatenation as `merge_node.py` (including the `souce code` typo). |

Scripts: `build_feasibility_v2.py` → `run_feasibility_v2.py` → `score_feasibility_v2.py`.

## 24 generic slots (R2.7)

`export_generic_slots.py` lists each of the 24 `type_valid is None` rows: template, filled value, left-context word, why no format convention.

## Contextual consistency v2 (new design, Phase III API)

Not a re-score of the 207-slot sample and not `run_blockid_consistency.py` on old CSV.

1. Sample merged paths whose **unfilled** `log_sequence` mentions a block placeholder ≥2 times (decidable by construction).
2. Re-run `get_log_simulate_v2` on that whole path (same Phase III prompt as generation).
3. Score: all block identifiers in the filled `log_seq` must denote one block. Datanode/node/pool ids unconstrained.

Scripts: `build_ctx_v2.py` → `run_ctx_v2.py` → `score_ctx_v2.py`.
The old 80.8% (59/73 on 4,792 short sessions) remains an **appendix diagnostic** of the archived corpus, not the v2 headline.

## X7 GPT-4o vs archived DeepSeek-V3 parameter fill (R2.12)

Archived Phase III fill = **DeepSeek-V3** (`baseline_compressed_log.json`). Do not attribute the 207 Drain slots to GPT-4o.

1. Unfilled templates: `output_v1/hadoop/merge_hdfs.json` (same payload `compress_log` sent to `get_log_simulate_v2`).
2. Fill once with GPT-4o; write `eval_results/x7_gpt4o/filled.jsonl`. Do not overwrite DeepSeek files.
3. Score type validity and block-id consistency on **both** fills with the same rules. Drain recovers slots post hoc, so GPT-4o will not yield the same 207 slots — compare distributions, not paired slot IDs.

Scripts: `build_x7.py` → `run_x7.py` → `score_x7.py`.
