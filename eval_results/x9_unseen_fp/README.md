# X9 — baseline false alarms vs unseen templates (R2.13)

LSTM next_log at `R=0` on `hdfs_0.0_tar` (`hash_id` `4607b793`).
Best epoch F1 **0.928** at top-5 (`dump_final`: `f1-0.9278 rc-0.8949 pc-0.9632`).
This is a diagnostic rerun; it does **not** replace Table 9's 0.919 cell.

## Result

| Quantity | Value |
|---|---|
| Test sessions | 115,012 |
| Train Drain vocab | 17 |
| Unseen test templates | 10, **all on anomalous sessions only** (795 / 3,453 anomalies) |
| Normal test sessions with an unseen template | **0** |
| False alarms | 118 / 111,559 normals (0.11%) |
| FPs that contain an unseen template | **0 / 118** |

Reproduce the split (no GPU):

```bash
python3 eval_results/x9_unseen_fp/analyze_unseen_fp.py \
  --train-pkl deep-loglizer/data/processed/HDFS/hdfs_0.0_tar/session_train.pkl \
  --test-pkl  deep-loglizer/data/processed/HDFS/hdfs_0.0_tar/session_test.pkl \
  --pred-csv  eval_results/x9_unseen_fp/session_preds.csv \
  --topk 5
```

Stdout of the training run: `deep-loglizer/cpu_reruns/lstm_next_log_baseline_R0.log`.
