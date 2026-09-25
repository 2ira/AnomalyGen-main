# X2 Deep-Loglizer Table 5 reruns (R2.3)

Independent reruns of Table 5 `w/o analysis` cells that `log.zip` had filled from the wrong stdout.

Official Deep-Loglizer clone: `AnomalyGen-main/deep-loglizer/` (`logpai/deep-loglizer`).
Augmentation: `aug_hdfs_data.py`, `R=0.001`, `random_seed=42`, 106-session `without_analysis` pool.
Split: LogHub HDFS_v1, 80/20, seed 42.
Printed F1/RC/PC are `dump_final_results` of the best epoch (same convention as Table 5 / Table 9).

## Who was copied

`ablation/Transformer-semantic/without_analysis.log` is a complete Transformer run (`hash_id=359ff04b`, `P27904`, `model_name=Transformer`, `0.697/0.561/0.920`). That cell is **genuine** and is kept.

`ablation/LSTM_next_log_semantic/without_analysis.log` is a **truncated copy of the same process**: same `P27904`, same timestamps, no config block, same `359ff04b` checkpoint path. That is the cell that was replaced.

## Cells written into Table 5

| Model × arm | F1 / RC / PC | `hash_id` | device | stdout |
|---|---|---|---|---|
| lstm-sequentials × w/o analysis | **0.958 / 0.996 / 0.923** | `784c7b7e` | MPS | `lstm_sequentials_wo_analysis.stdout.txt` |
| lstm-next_log × w/o analysis | **0.916 / 0.942 / 0.891** | `0d4ca3d7` | MPS | `lstm_next_log_wo_analysis.stdout.txt` |
| lstm-semantic-next_log × w/o analysis | **0.766 / 0.632 / 0.974** | `d65380d6` | CPU (`--gpu -1`) | `lstm_semantic_next_log_wo_analysis.stdout.txt` |
| transformer-semantic × w/o analysis | **0.697 / 0.561 / 0.920** | `359ff04b` | original CUDA | `original_transformer_359ff04b/without_analysis.stdout.txt` |
| lstm-next_log × w/o label | **0.921 / 0.952 / 0.893** | `24cc32be` | MPS | `lstm_next_log_wo_label.stdout.txt` |

LSTM semantic next_log used the archived sibling hyperparameters (`window_size=5`, `stride=5`, `max_token_len=30`, `min_token_count=3`, `batch_size=256`, `--use_tfidf --use_attention`). CPU was required because Apple MPS rejects the tfidf embedder's `.double()`.

`HDFS_dump_final_results.txt` holds the `dump_final_results` lines (`f1-0.9581`, `f1-0.9159`, `f1-0.7664`, `f1-0.9214`).
Heuristic labels for the w/o-label cell: `x2_wo_label/` (66 normal / 40 anomaly).
The truncated copy that used to occupy the LSTM cell is kept at `original_transformer_359ff04b/copied_into_lstm_semantic_next_log.stdout.txt`.
