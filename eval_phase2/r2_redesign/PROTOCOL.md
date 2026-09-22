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

## X7 / X12 GPT-4o vs archived DeepSeek-V3 parameter fill (R2.12)

Archived Phase III fill = **DeepSeek-V3**. Do not attribute the 207 Drain slots to GPT-4o.

**Headline is X12 same-slot $n{=}144$**, not the X7 same-prompt Drain recount:

1. Lock the 144 type-decidable DeepSeek slots on the 15 paired HDFS methods.
2. Convert each Drain `<*>` to `{}` and call `get_log_simulate_v2` (GPT-4o, temperature 0).
3. Extract with the *locked* template + `slot_idx` + `slot_type`. Missing = False, so both models share denominator 144.
4. Role-prefixed `nodeid` (`namenode`/`datanode`/`node-`/`node` already in the template) must be a numeric suffix, not a hostname. A recovered `node-namenode01` is type-invalid.
5. Result: DeepSeek $141/144=0.979$, GPT-4o $127/144=0.882$ (14 missing counted false: 9 `node-<*>`/`datanode<*>` rewritten as `namenode01`, 5 camelCase wording; recovered $127/130=0.977$).
6. Same 15 methods, R2.7 block-id invariant. Strict same-slot on the 27 locked block-prefix slots (missing / no unique session block = False): DeepSeek $26/27=0.963$, GPT-4o $19/27=0.704$. Session-level among decidable: DeepSeek $4/4$, GPT-4o $2/2$ (13/15 GPT-4o fills have $<2$ block mentions). Old `ctx_consistent` is diagnostic only (DeepSeek $11/58$, GPT-4o $17/68$).

Scripts: `run_x12_same_slot.py` `{build,run,score}`. Artifact: `eval_results/x12_same_slot/compare.json`.

X7 (`build_x7.py` → `run_x7.py` → `score_x7.py`) remains a same-prompt distribution check and is not the matched-$n$ figure.
