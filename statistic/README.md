# Reproducing Table 1 and Table 4 coverage (D1)

All coverage numbers in the manuscript use **one** convention, implemented in
`coverage_stats.py` and aggregated by `d1_long_all.py`.

## Convention

- **Universe / denominator.** Unique production format strings whose skeleton
  has at least two literal tokens (`min_tokens=2`). Short strings such as
  `"Created "` never score, so they leave both the numerator and the
  denominator. HDFS drops 147 of 2,886 unique formats, leaving `|T| = 2,739`.
- **Hit / numerator.** A source format is covered when a corpus message
  contains all of its literal tokens in order. Placeholders `{}`, `<*>`, `%s`,
  `%(name)s`, `{0}`, and `${...}` are stripped first; pure-digit tokens are
  dropped; test-tree paths (`src/test`, `/test/`, `/tests/`) are excluded.
- **Table 1 `# Observed`.** D1 hits of the public Drain list on that universe
  (not Drain-list size).
- **Table 4 AG-HDFS.** D1 hits of `output/log_events/final_logs.json`.

## Reproduce the paper cells (no source trees required)

Frozen extracts and LogHub CSVs live under `statistic/x5_out/`. From the
`AnomalyGen-main` root:

```bash
python3 statistic/d1_long_all.py --check
```

This writes `statistic/x5_out/d1_long_all.json` and exits 0 only if every
Table 1 / Table 4 cell matches the manuscript freeze:

| System | # Source (long) | # Observed (D1) | Coverage | Source tree | Public Drain list |
|---|---:|---:|---:|---|---|
| HDFS | 2,739 | 13 | 0.47% | Hadoop 3.3.6 `hadoop-hdfs-project` | LogHub HDFS_v1 (30 templates) |
| Hadoop Common | 1,344 | 17 | 1.26% | Hadoop 3.3.6 Common | LogHub Hadoop_2k |
| OpenStack Nova | 1,812 | 31 | 1.71% | Nova tag `13.1.4` | LogHub OpenStack_2k |
| ZooKeeper | 499 | 55 | 11.02% | `release-3.4.5` `src/java/main` | LogHub Zookeeper |
| Spark | 2,391 | 16 | 0.67% | Spark tag `v2.4.8` | LogHub Spark_2k |
| MapReduce | 874 | 57 | 6.52% | Hadoop 3.3.6 MapReduce | LogHub Hadoop_2k |
| **Pooled** | **9,659** | **189** | **1.96%** | | |
| AG-HDFS (Table 4) | 2,739 | 2,646 | 96.60% (203.5× vs LogHub) | same HDFS universe | `output/log_events/final_logs.json` |

Single-system:

```bash
python3 statistic/coverage_stats.py \
    --source-templates statistic/x5_out/hdfs_3.3.6_log_templates.txt \
    --generated output/log_events/final_logs.json \
    --public statistic/x5_out/loghub/HDFS_templates.csv
```

`--include-short` restores the all-template denominator (not the paper
convention).

## Re-extract from source (optional)

The `*.txt` files under `statistic/x5_out/` are the universe used in the
paper. Hadoop / Nova / Spark / ZooKeeper trees are gitignored (`hadoop/`,
`zookeeper/`, `third_party_src/`) and are **not** required to reproduce the
tables. To rebuild an extract:

```bash
# Java (Hadoop Common / MapReduce / ZooKeeper / HDFS)
python3 statistic/extract_log_templates.py \
    --root <tree> --out statistic/x5_out/<name>_log_templates.txt

# Python (OpenStack Nova 13.1.4)
git clone --depth 1 --branch 13.1.4 \
    https://opendev.org/openstack/nova.git third_party_src/nova-13.1.4
python3 statistic/extract_python_log_templates.py \
    --root third_party_src/nova-13.1.4 \
    --out statistic/x5_out/nova_13.1.4_log_templates.txt

# Scala + Java (Spark 2.4.8)
git clone --depth 1 --branch v2.4.8 \
    https://github.com/apache/spark.git third_party_src/spark-2.4.8
python3 statistic/extract_scala_log_templates.py \
    --root third_party_src/spark-2.4.8 \
    --out statistic/x5_out/spark_2.4.8_log_templates.txt
```

Then re-run `python3 statistic/d1_long_all.py --check`.

## Residual (HDFS Table 4)

Of 2,886 unique HDFS formats, 147 shorts are filtered out of `|T|`. Of the
remaining 2,739, AnomalyGen hits 2,646. The residual 93 long misses sit
mostly in inner classes or constructors that JavaParser did not map into
extracted methods, so those format strings never enter a merge
`log_sequence`.
