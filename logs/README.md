# Replacement Deep-Loglizer ablation logs (R2.3)

These files **supersede** the corresponding entries in `log.zip` for three copied Table 5 cells.

| Table 5 cell | log.zip path that was wrong | Replacement |
|---|---|---|
| lstm-sequentials × w/o analysis | `ablation/LSTM_sequentials/without_analysis.log` (was a copy of `0d4ca3d7`) | `ablation/LSTM_sequentials/without_analysis.log` → F1 **0.958 / 0.996 / 0.923**, `784c7b7e` |
| lstm-next_log × w/o analysis | `ablation/LSTM_next/without_analysis.log` (genuine CUDA `0d4ca3d7`, printed 0.901) | independent MPS rerun **0.916 / 0.942 / 0.891**, same `hash_id` |
| lstm-next_log × w/o label | (no file in `log.zip`) | `ablation/LSTM_next/without_label.log` → F1 **0.921 / 0.952 / 0.893**, `24cc32be` |
| lstm-semantic-next_log × w/o analysis | `ablation/LSTM_next_log_semantic/without_analysis.log` (truncated Transformer `359ff04b`) | CPU rerun **0.766 / 0.632 / 0.974**, `d65380d6` |
| transformer-semantic × w/o analysis | `ablation/Transformer-semantic/without_analysis.log` | **kept**; genuine Transformer **0.697 / 0.561 / 0.920**, `359ff04b` |

Full dump_final lines, params.json, and README: `eval_results/x2_deeploglizer/`.
Do not mix these F1 values into the Table 9/10 12-model mean ($1.750$ / $1.692$).
