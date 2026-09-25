# PreLog HDFS stdout (R2.3)

Deposited classification reports for Appendix Table 9. **Recompute Table 9 from these files; do not retrain unless you have the PreLog checkpoint and `prelog_data/` JSON (not in git).**

```bash
# from AnomalyGen-main/
python3 eval_results/prelog/check_table9.py
```

Expected: five `OK` rows, heatmap `+0.2 / +0.4 / -1.9 / -0.7`, exit 0.

Manuscript Table 9 uses sklearn **`weighted avg`**, mapped as F1 = f1-score, RC = recall, PC = precision. Test support is fixed: 3453 anomalous / 111559 normal / 115012 total.

## Table 9 cells (`hdfs_1.0_tar`)

| R | PC | RC | F1 | ΔF1 vs R=0 | log |
|---|---|---|---|---|---|
| 0.0 | 0.989 | 0.989 | **0.988** | — | `hdfs_1.0_tar_baseline.log` |
| 0.001 | 0.990 | 0.991 | 0.990 | +0.2 | `hdfs_1.0_tar_plus_new_aug_0.001.log` |
| 0.01 | 0.992 | 0.992 | **0.992** | +0.4 | `hdfs_1.0_tar_plus_new_aug_0.01.log` |
| 0.1 | 0.977 | 0.977 | 0.969 | −1.9 | `hdfs_1.0_tar_plus_new_aug_0.1.log` |
| 1.0 | 0.984 | 0.984 | 0.981 | −0.7 | `hdfs_1.0_tar_plus_new_aug_1.0.log` |

Previous typesetting copied `(precision, recall, f1)` left-to-right into `(F1, RC, PC)`, which swapped F1 and PC at `R=0.1` and `R=1.0`. Weighted F1 need not equal the harmonic mean of weighted P and R. The `anomalous` row is in each log for audit and is **not** Table 9.

`metrics.json` stores both the weighted triple (manuscript) and the anomalous-class triple (audit).

## What is / is not reproducible here

| Claim | How to check |
|---|---|
| Table 9 PreLog F1/RC/PC | `python3 eval_results/prelog/check_table9.py` (no GPU) |
| Retrain PreLog | Needs HuggingFace PreLog checkpoint, `prelog_data/HDFS/.../{train,test}.json`, and `tasks/classification/train.py`. Those files are **not** in this repo. Commands used for the deposited runs are in each `*.log` header. |
| ZooKeeper PreLog (Table 10, 0.998) | Stdout **not recovered**. Do not treat as re-derived. |
| Table 5 PreLog | Treated as the 106-session ablation. AnomalyGen F1/RC/PC = `0.990/0.991/0.990`. Each ablation arm is weighted avg F1/RC/PC = `0.955/0.970/0.941` (sklearn P/R/F1 = `0.941/0.970/0.955`). |

## Table 5 ablation arms

All four predict only `normal` (weighted F1 = 0.955); mapped as F1$=$f1, RC$=$recall, PC$=$precision:

- `hdfs_0.0_tar_plus_heuristic_label_0.001.log` (w/o label)
- `hdfs_0.0_tar_plus_resample_0.001.log`
- `hdfs_0.0_without_cot_plus_new_aug_0.001.log`
- `hdfs_0.0_without_analysis_plus_new_aug_0.001.log`

`data_prep_resample.log`: resampling `tar=0.0` training data adds 0 anomalous sessions.

## Retrain template (only if checkpoint + JSON are present)

```bash
cd tasks/classification
export MODEL_PATH="/path/to/PreLog"   # HuggingFace format
# pip: transformers==4.24.0 accelerate fairseq==0.12.2 yacs datasets tensorboardX rouge
accelerate launch --num_processes=1 train.py \
  --dataset HDFS --model-name bart --model-path $MODEL_PATH \
  --train-file prelog_data/HDFS/hdfs_1.0_tar/train.json \
  --test-file  prelog_data/HDFS/hdfs_1.0_tar/test.json \
  --prompt-template prompt_template.txt \
  --verbalizer anomaly_detection/verbalizer.txt \
  --batch-size 4 --lr 3e-5 --max-steps 1000 \
  --lr-scheduler-type polynomial --do-train --do-eval \
  --grouping --window-size 5 \
  --output-dir prelog_out_hdfs_base_1.0
```

Augmented splits use `hdfs_baseline/hdfs_1.0_tar_plus_new_aug_{0.001,0.01,0.1,1.0}/`. After eval, take the **weighted avg** line, not `anomalous` and not `accuracy`.
