# eval_labeling — Label Accuracy Evaluation (M.2 / R1.2)

Validates whether AnomalyGen's automatic labelling rules can reliably
distinguish **true anomalies** from **benign fault-tolerant recovery** in
synthesised log sessions.  Complements `eval_phase2/` (M.3, sequence &
parameter quality).

## Experiment Design

### Research Question
Can severity-level + keyword heuristics correctly label generated sessions,
especially in fault-tolerant systems where errors may be recovered?

### Two Labelling Rules Compared
| Rule | Description |
|---|---|
| **baseline** (Level heuristic) | Any ERROR-level log in the session → anomaly |
| **recovery-aware** | Adds recovery-signal detection (e.g. "successfully converted to complete") and fatal-signal override (e.g. "already retried N times") |

### Ground Truth Construction (Independent of Evaluated Rules)
- **HDFS**: 45 anomaly / 61 normal across 106 sessions.  38 anomalies auto-
  labelled by an independent `access_denied` rule; 7 anomalies + 3 special
  normals hand-reviewed with rationale (see `GT_RATIONALE` in scripts).
- **ZooKeeper**: 17 hand-reviewed sessions covering NIO cleanup, SASL recovery,
  JMX noise, follower transitions, and true failures; remaining sessions use
  conservative auto-rules.

### Key Results
| System | Rule | ACC | PC | RC | F1 |
|---|---|---|---|---|---|
| HDFS | baseline | 0.934 | 0.975 | 0.867 | 0.918 |
| HDFS | recovery-aware | **0.991** | 1.000 | 0.978 | 0.989 |
| ZK | baseline | see `eval_results/zk_recovery_relabel.json` |
| ZK | recovery-aware | see `eval_results/zk_recovery_relabel.json` |

The level-only baseline makes **7** errors on the 106 HDFS sessions (1 FP + 6 FN).
**5** of the 6 FN are `structural` (true anomalies with no ERROR-level line) —
that is the original-submission “5 mislabels”. The remaining errors are
`kw_miss` 1 + `recovery_fp` 1. Recovery-aware flips 6 sessions (5 structural +
1 recovery FP) and leaves `kw_miss`. See `analyze_5_vs_7.py` and
`eval_results/hdfs_recovery_relabel.json` (`miscls_baseline`).

## Directory Structure
```
eval_labeling/
├── README.md                              # this file
├── utils.py                               # shared: session loading, metrics, I/O
├── hdfs_recovery_relabel.py               # HDFS experiment (106 sessions)
├── zk_recovery_relabel.py                 # ZooKeeper experiment
├── analyze_5_vs_7.py                      # R2.8: 5 vs 7, keyword overlap, LOSO
├── eval_results/
│   ├── hdfs_recovery_relabel.{json,csv}   # HDFS metrics + per-session detail
│   └── zk_recovery_relabel.{json,csv}     # ZK metrics + per-session detail
```

## Usage
```bash
cd AnomalyGen-main
export PYTHONPATH=$PYTHONPATH:$(pwd)

# HDFS (default CSV: output_v1/ablation/baseline/parsed_logs/...)
python eval_labeling/hdfs_recovery_relabel.py

# ZooKeeper (default CSV: output/zookeeper/zookeeper_combined_parsed_logs.csv)
python eval_labeling/zk_recovery_relabel.py

# Custom CSV path
python eval_labeling/hdfs_recovery_relabel.py --csv /path/to/parsed_logs.csv
```

## Prerequisites
- Generated pipeline artifacts (`output_v1/`, `output/zookeeper/`).
- No LLM calls required — pure rule-based evaluation on existing data.
