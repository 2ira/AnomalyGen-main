#!/usr/bin/env python3
"""
Recompute LLM call counts and token usage from the pipeline artifacts, and
produce a defensible API-cost estimate (reviewer comment 11.5).

Evidence used
-------------
1. `*/ablation_v1_call_times.txt` — written by main/ablation_merge_node.py.
   Each file records, for one entry method, the number of Phase-II merge calls
   and the summed cl100k_base token count of (prompt + response) over those
   calls.  These are the ONLY direct token measurements in the repository.
   The `output_v2/` copies contain arithmetic overflow / string-concatenation
   corruption in the token field and are discarded (detected as > 1e12).

2. `prune_call_path_javaparser.json` — one entry per analysed method node.
   Used to extrapolate the number of merge calls for entry methods and for
   ZooKeeper, where no call_times file was written (the CoT path in
   main/merge_node.py has no token accounting).

3. `*_compressed_log.json` / `merge_single_log*.json` — Phase-III parameter
   filling (statistic/standard_all_logs.py -> get_log_simulate_v2), one LLM
   call per compressed node.

Usage:
    cd AnomalyGen-main && python3 statistic/estimate_api_cost.py
"""
import glob
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

CORRUPT_THRESHOLD = 10 ** 12  # a single entry method cannot consume 1e12 tokens

# Public list prices, USD per 1M tokens (state the snapshot date in the paper).
PRICES = {
    "gpt-4o":       {"in": 2.50, "out": 10.00},
    "deepseek-v3":  {"in": 0.27, "out": 1.10},
}
# Fraction of the measured (prompt+response) total that is output.  The merge
# prompt is long and the XML answer is short, so we bracket the estimate.
OUT_SHARE_RANGE = (0.15, 0.35)


def read_call_times():
    rows = []
    for path in sorted(glob.glob(os.path.join(ROOT, "output*", "*", "*",
                                              "*call_times*.txt"))):
        txt = open(path, encoding="utf-8", errors="replace").read()
        m_c = re.search(r"all call times\s+(\d+)", txt)
        m_t = re.search(r"all cost token is\s+(\d+)", txt)
        rows.append({
            "path": os.path.relpath(path, ROOT),
            "entry": os.path.basename(os.path.dirname(path)),
            "run": os.path.relpath(path, ROOT).split(os.sep)[0],
            "calls": int(m_c.group(1)) if m_c else None,
            "tokens": int(m_t.group(1)) if m_t else None,
        })
    return rows


def count_nodes(pattern):
    total = 0
    per = {}
    for path in sorted(glob.glob(os.path.join(ROOT, pattern))):
        try:
            d = json.load(open(path, encoding="utf-8", errors="replace"))
        except Exception as e:
            print(f"  [warn] cannot parse {path}: {e}")
            continue
        n = len(d) if isinstance(d, (dict, list)) else 0
        per[os.path.relpath(path, ROOT)] = n
        total += n
    return total, per


def main():
    print("=" * 78)
    print("1. Direct token measurements (*/ablation_v1_call_times.txt)")
    print("=" * 78)
    rows = read_call_times()
    print(f"{'run':<10}{'entry':<40}{'calls':>7}{'tokens':>28}  status")
    good, bad = [], []
    for r in rows:
        corrupt = r["tokens"] is None or r["tokens"] > CORRUPT_THRESHOLD
        (bad if corrupt else good).append(r)
        print(f"{r['run']:<10}{r['entry']:<40}{r['calls']:>7}{r['tokens']:>28}"
              f"  {'CORRUPT-discard' if corrupt else 'ok'}")

    v1 = [r for r in good if r["run"] == "output"]
    print(f"\nusable measurements: {len(good)} of {len(rows)}")
    print(f"  discarded (token field > 1e12, arithmetic corruption): {len(bad)}")
    calls_v1 = sum(r["calls"] for r in v1)
    tok_v1 = sum(r["tokens"] for r in v1)
    print(f"\nHDFS, no-CoT ablation run (output/hadoop/, {len(v1)} entry methods):")
    print(f"  Phase-II merge calls  : {calls_v1}")
    print(f"  Phase-II tokens (cl100k, prompt+response): {tok_v1:,}")
    print(f"  mean tokens per call  : {tok_v1 / calls_v1:,.0f}")

    print("\n" + "=" * 78)
    print("2. Pipeline node counts (for extrapolation)")
    print("=" * 78)
    for label, pat in (
            ("HDFS  prune_call_path_javaparser.json",
             "output/hadoop/*/prune_call_path_javaparser.json"),
            ("ZK    prune_call_path_javaparser.json",
             "output/zookeeper/*/prune_call_path_javaparser.json"),
            ("HDFS  merge_single_log_without_cot.json",
             "output/hadoop/*/merge_single_log_without_cot.json"),
            ("ZK    merge_single_log.json",
             "output/zookeeper/*/merge_single_log.json"),
    ):
        tot, per = count_nodes(pat)
        print(f"  {label:<42} files={len(per):<4} nodes={tot}")

    hdfs_nodes, _ = count_nodes("output/hadoop/*/prune_call_path_javaparser.json")
    zk_nodes, _ = count_nodes("output/zookeeper/*/prune_call_path_javaparser.json")
    print(f"\n  tokens per analysed node (HDFS, measured): "
          f"{tok_v1 / hdfs_nodes:,.0f}" if hdfs_nodes else "")

    print("\n" + "=" * 78)
    print("3. Phase-III parameter-filling calls (statistic/standard_all_logs.py)")
    print("=" * 78)
    for label, rel in (
            ("baseline_compressed_log.json", "baseline_compressed_log.json"),
            ("ablation_v1_compressed_log.json", "ablation_v1_compressed_log.json"),
            ("ablation_v2_compressed_log.json", "ablation_v2_compressed_log.json"),
            ("baseline_zookeeper_compressed_log.json",
             "baseline_zookeeper_compressed_log.json"),
    ):
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            print(f"  {label:<42} MISSING")
            continue
        d = json.load(open(p, encoding="utf-8", errors="replace"))
        n = len(d) if isinstance(d, (dict, list)) else 0
        print(f"  {label:<42} entries={n}")

    print("\n" + "=" * 78)
    print("4. Cost estimate")
    print("=" * 78)
    scenarios = []
    # HDFS: measured directly.
    scenarios.append(("HDFS (measured, 6 entry methods)", calls_v1, tok_v1))
    # ZooKeeper: extrapolate with the measured tokens-per-node rate.
    if hdfs_nodes and zk_nodes:
        rate = tok_v1 / hdfs_nodes
        zk_tok = int(rate * zk_nodes)
        zk_calls = int(round(calls_v1 / hdfs_nodes * zk_nodes))
        scenarios.append((f"ZooKeeper (extrapolated from {zk_nodes} nodes)",
                          zk_calls, zk_tok))

    print(f"{'scenario':<42}{'calls':>7}{'tokens':>12}"
          f"{'GPT-4o low':>12}{'GPT-4o high':>13}"
          f"{'DS-V3 low':>11}{'DS-V3 high':>12}")
    for name, calls, tok in scenarios:
        cells = []
        for model in ("gpt-4o", "deepseek-v3"):
            p = PRICES[model]
            lo_out, hi_out = OUT_SHARE_RANGE
            c_lo = (tok * (1 - hi_out) * p["in"] + tok * hi_out * p["out"]) / 1e6
            c_hi = (tok * (1 - lo_out) * p["in"] + tok * lo_out * p["out"]) / 1e6
            # low/high ordering: output tokens cost more, so more output = more cost
            cells += [min(c_lo, c_hi), max(c_lo, c_hi)]
        print(f"{name:<42}{calls:>7}{tok:>12,}"
              f"{cells[0]:>12.2f}{cells[1]:>13.2f}{cells[2]:>11.2f}{cells[3]:>12.2f}")

    print(f"\nassumptions:")
    print(f"  * token counts are cl100k_base counts of (prompt + response), "
          f"summed per call")
    print(f"  * output-token share bracketed at "
          f"{OUT_SHARE_RANGE[0]:.0%}-{OUT_SHARE_RANGE[1]:.0%}")
    print(f"  * list prices (USD / 1M tokens): " +
          ", ".join(f"{k} in={v['in']} out={v['out']}" for k, v in PRICES.items()))
    print(f"  * ZooKeeper figures are extrapolated: no call_times file exists "
          f"because the CoT merger (main/merge_node.py) has no token accounting")


if __name__ == "__main__":
    main()
