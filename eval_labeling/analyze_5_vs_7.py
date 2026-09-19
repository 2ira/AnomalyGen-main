#!/usr/bin/env python3
"""
Reconcile the old "5 mislabels / 95.28% / 106 HDFS sessions" figure with the new
"7 baseline errors / 93.40%" figure, and quantify curated-keyword overlap
(reviewer comment 8).

What it does
------------
1. Loads exactly the same sessions the published evaluation used
   (output_v1/ablation/baseline/parsed_logs/hdfs_combined_parsed_logs.csv and
   output/zookeeper/zookeeper_combined_parsed_logs.csv) and reports session and
   line counts, so the "106 sessions / 287 lines" and "141 vs 142" claims can be
   checked.

2. Scores THREE labelling rules against the same semantic ground truth:
     R0  level-only          : any ERROR-level line -> anomaly   (the "baseline"
                               of the current eval_results/*.json)
     R1  level + keyword     : ERROR level OR explicit/implicit error keyword
                               -> anomaly, no recovery awareness.  This is the
                               rule the *original* submission described.
     R2  recovery-aware      : the published new rule.
   The hypothesis to test is that the old "5 mislabels" corresponds to R1 and
   the new "7 errors" to R0.

3. Keyword-overlap audit: for every session, reports whether it matches any
   curated recovery keyword and/or any curated fatal keyword, and cross-tabs
   that against ground truth and against correctness, so we can say how much of
   the accuracy is carried by the curated lists.

4. Leave-one-session-out (LOSO) held-out protocol: for each session s, rebuild
   the recovery/fatal keyword lists using only keywords that are *also*
   supported by at least one other session (i.e. drop any keyword whose only
   evidence is s), relabel s with those lists, and report held-out accuracy.
   This is runnable entirely on existing data, with no LLM calls.

Usage:
    cd AnomalyGen-main
    export PYTHONPATH=$PYTHONPATH:$(pwd)
    python3 eval_labeling/analyze_5_vs_7.py
"""
import argparse
import collections
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, HERE)

from utils import (  # noqa: E402
    load_sessions, session_text, has_error_level, any_match, confusion_matrix,
)
import hdfs_recovery_relabel as H  # noqa: E402
import zk_recovery_relabel as Z  # noqa: E402

HDFS_CSV = os.path.join(REPO_ROOT, "output_v1", "ablation", "baseline",
                        "parsed_logs", "hdfs_combined_parsed_logs.csv")
ZK_CSV = os.path.join(REPO_ROOT, "output", "zookeeper",
                      "zookeeper_combined_parsed_logs.csv")

_EXPLICIT = re.compile(r"Exception|\b(ERROR|FATAL)\b")
_IMPLICIT = re.compile(r"\b(fail|cannot|invalid|failed)\b|error_code\s*=\s*\d+",
                       re.IGNORECASE)


def rule_level_only(lines):
    return "anomaly" if has_error_level(lines) else "normal"


def rule_level_plus_keyword(lines):
    """The rule the original submission described: level OR error keyword."""
    text = session_text(lines)
    if has_error_level(lines) or _EXPLICIT.search(text) or _IMPLICIT.search(text):
        return "anomaly"
    return "normal"


def report_rules(name, sessions, gt_fn, rec_fn):
    rows = []
    for bid, lines in sessions.items():
        rows.append({
            "block_id": bid,
            "gt": gt_fn(bid, lines),
            "R0_level_only": rule_level_only(lines),
            "R1_level_keyword": rule_level_plus_keyword(lines),
            "R2_recovery_aware": rec_fn(lines),
        })

    print(f"\n{'=' * 72}\n{name}: {len(rows)} sessions, "
          f"{sum(len(v) for v in sessions.values())} log lines\n{'=' * 72}")
    gt = collections.Counter(r["gt"] for r in rows)
    print(f"ground truth: anomaly={gt['anomaly']} normal={gt['normal']}")
    for key in ("R0_level_only", "R1_level_keyword", "R2_recovery_aware"):
        cm = confusion_matrix(rows, key)
        err = cm["FP"] + cm["FN"]
        print(f"  {key:<20} ACC={cm['accuracy']:.4f}  "
              f"TP={cm['TP']:<3} FP={cm['FP']:<3} FN={cm['FN']:<3} TN={cm['TN']:<3} "
              f"errors={err}   ({1 - err / cm['n']:.4f} = 1 - {err}/{cm['n']})")
    print("\n  disagreements between R0 and R1 (these explain 7 vs 5):")
    for r in rows:
        if r["R0_level_only"] != r["R1_level_keyword"]:
            tag = []
            if r["R0_level_only"] != r["gt"]:
                tag.append("R0 wrong")
            if r["R1_level_keyword"] != r["gt"]:
                tag.append("R1 wrong")
            print(f"    {r['block_id']:<14} gt={r['gt']:<8} "
                  f"R0={r['R0_level_only']:<8} R1={r['R1_level_keyword']:<8} "
                  f"{'/'.join(tag) or 'both right'}")
    return rows


def keyword_overlap(name, sessions, rows, recovery_pats, fatal_pats):
    print(f"\n--- {name}: curated-keyword coverage ---")
    print(f"recovery keyword set: {len(recovery_pats)} patterns")
    print(f"fatal    keyword set: {len(fatal_pats)} patterns")
    gtmap = {r["block_id"]: r["gt"] for r in rows}
    predmap = {r["block_id"]: r["R2_recovery_aware"] for r in rows}

    tab = collections.Counter()
    hit_rec = hit_fat = 0
    per_pat_rec = collections.Counter()
    per_pat_fat = collections.Counter()
    for bid, lines in sessions.items():
        text = session_text(lines)
        r = any_match(recovery_pats, text)
        f = any_match(fatal_pats, text)
        hit_rec += r
        hit_fat += f
        tab[(r, f, gtmap[bid], predmap[bid] == gtmap[bid])] += 1
        for p in recovery_pats:
            if re.search(p, text, re.I):
                per_pat_rec[p] += 1
        for p in fatal_pats:
            if re.search(p, text, re.I):
                per_pat_fat[p] += 1

    n = len(sessions)
    print(f"sessions matching >=1 recovery keyword: {hit_rec}/{n} "
          f"({hit_rec / n:.1%})")
    print(f"sessions matching >=1 fatal    keyword: {hit_fat}/{n} "
          f"({hit_fat / n:.1%})")
    both = sum(v for (r, f, _, _), v in tab.items() if r and f)
    neither = sum(v for (r, f, _, _), v in tab.items() if not r and not f)
    print(f"sessions matching both: {both}/{n} ({both / n:.1%})")
    print(f"sessions matching neither: {neither}/{n} ({neither / n:.1%})")
    print("\n  accuracy of the recovery-aware rule, split by keyword match:")
    for flag, label in ((True, "matches >=1 curated keyword"),
                        (False, "matches NO curated keyword")):
        sel = [(k, v) for k, v in tab.items() if (k[0] or k[1]) == flag]
        tot = sum(v for _, v in sel)
        okc = sum(v for k, v in sel if k[3])
        if tot:
            print(f"    {label:<30} n={tot:<4} correct={okc:<4} "
                  f"acc={okc / tot:.4f}")
    print("\n  per-pattern session support (recovery):")
    for p, c in per_pat_rec.most_common():
        print(f"    {c:>4}  {p}")
    print("  per-pattern session support (fatal):")
    for p, c in per_pat_fat.most_common():
        print(f"    {c:>4}  {p}")
    singles_r = [p for p, c in per_pat_rec.items() if c == 1]
    singles_f = [p for p, c in per_pat_fat.items() if c == 1]
    print(f"\n  patterns supported by exactly ONE session: "
          f"{len(singles_r)} recovery + {len(singles_f)} fatal "
          f"(these are the ones a held-out protocol must drop)")


def loso(name, sessions, gt_fn, recovery_pats, fatal_pats, label_fn_builder):
    """
    Leave-one-session-out: for the held-out session s, drop every curated
    keyword whose only supporting evidence in the corpus is s, then relabel s.
    """
    support = collections.defaultdict(set)
    for bid, lines in sessions.items():
        text = session_text(lines)
        for p in list(recovery_pats) + list(fatal_pats):
            if re.search(p, text, re.I):
                support[p].add(bid)

    n = ok = 0
    fails = []
    for bid, lines in sessions.items():
        rec = [p for p in recovery_pats if support[p] - {bid}]
        fat = [p for p in fatal_pats if support[p] - {bid}]
        pred = label_fn_builder(rec, fat)(lines)
        gt = gt_fn(bid, lines)
        n += 1
        if pred == gt:
            ok += 1
        else:
            fails.append((bid, gt, pred))
    print(f"\n--- {name}: leave-one-session-out held-out accuracy ---")
    print(f"n={n}  correct={ok}  held-out accuracy = {ok / n:.4f}")
    dropped = sum(1 for p in support if len(support[p]) == 1)
    print(f"({dropped} of {len(support)} curated patterns are supported by a "
          f"single session and are therefore removed when that session is held out)")
    if fails:
        print("  held-out failures:")
        for bid, gt, pred in fails[:25]:
            print(f"    {bid:<14} gt={gt:<8} pred={pred}")
        if len(fails) > 25:
            print(f"    ... and {len(fails) - 25} more")
    return ok, n


def hdfs_label_builder(rec, fat):
    def f(lines):
        text = session_text(lines)
        suspect = (has_error_level(lines) or bool(_EXPLICIT.search(text))
                   or bool(_IMPLICIT.search(text)))
        if not suspect:
            return "normal"
        if any_match(fat, text):
            return "anomaly"
        if any_match(rec, text) and not any_match(fat, text):
            return "normal"
        return "anomaly"
    return f


def zk_label_builder(rec, fat):
    def f(lines):
        text = session_text(lines)
        if has_error_level(lines) and Z._is_jmx_only(lines):
            return "normal"
        suspect = (has_error_level(lines)
                   or bool(re.search(r"Exception|\b(ERROR|FATAL)\b", text)))
        if not suspect:
            return "normal"
        if any_match(fat, text):
            return "anomaly"
        if any_match(rec, text):
            return "normal"
        if not has_error_level(lines):
            return "normal"
        return "anomaly"
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hdfs-csv", default=HDFS_CSV)
    ap.add_argument("--zk-csv", default=ZK_CSV)
    args = ap.parse_args()

    print(f"HDFS csv: {args.hdfs_csv}")
    print(f"ZK   csv: {args.zk_csv}")

    hs = load_sessions(args.hdfs_csv)
    zs = load_sessions(args.zk_csv)

    hrows = report_rules("HDFS", hs, H.semantic_gt, H.recovery_aware_label)
    zrows = report_rules("ZooKeeper", zs, Z.semantic_gt, Z.recovery_aware_label)

    keyword_overlap("HDFS", hs, hrows, H._RECOVERY_SIGNALS, H._FATAL_SIGNALS)
    keyword_overlap("ZooKeeper", zs, zrows, Z._RECOVERY_KW, Z._FATAL_KW)

    loso("HDFS", hs, H.semantic_gt, H._RECOVERY_SIGNALS, H._FATAL_SIGNALS,
         hdfs_label_builder)
    loso("ZooKeeper", zs, Z.semantic_gt, Z._RECOVERY_KW, Z._FATAL_KW,
         zk_label_builder)

    # --- circularity audit: is the GT itself defined by an evaluated keyword? --
    print("\n" + "=" * 72)
    print("CIRCULARITY AUDIT: sessions whose ground truth is decided by a keyword")
    print("that the evaluated rule also uses")
    print("=" * 72)
    hs_ad = [b for b, l in hs.items()
             if b not in H.GT_RATIONALE
             and re.search(r"access denied", session_text(l), re.I)]
    hs_auto_normal = [b for b in hs
                      if b not in H.GT_RATIONALE and b not in hs_ad]
    print(f"HDFS: {len(H.GT_RATIONALE)} hand-adjudicated, "
          f"{len(hs_ad)} auto-anomaly via 'access denied' "
          f"({len(hs_ad) / len(hs):.1%}), "
          f"{len(hs_auto_normal)} auto-normal by default")
    print("      -> 'access denied' is in BOTH semantic_gt() and _FATAL_SIGNALS,"
          " so those sessions are trivially correct for any rule using it.")
    zk_auto = [b for b, l in zs.items()
               if b not in Z.GT_RATIONALE and Z._AUTO_FATAL.search(session_text(l))]
    print(f"ZK  : {len(Z.GT_RATIONALE)} hand-adjudicated, "
          f"{len(zk_auto)} auto-anomaly via _AUTO_FATAL "
          f"({len(zk_auto) / len(zs):.1%}), "
          f"{len(zs) - len(Z.GT_RATIONALE) - len(zk_auto)} auto-normal by default")
    print("\n  accuracy restricted to the NON-circular subset "
          "(hand-adjudicated sessions only):")
    for nm, sess, gtr, gt_fn, rec_fn in (
            ("HDFS", hs, H.GT_RATIONALE, H.semantic_gt, H.recovery_aware_label),
            ("ZK", zs, Z.GT_RATIONALE, Z.semantic_gt, Z.recovery_aware_label)):
        sub = [{"gt": gt_fn(b, sess[b]),
                "R0": rule_level_only(sess[b]),
                "R2": rec_fn(sess[b])} for b in gtr if b in sess]
        if not sub:
            continue
        c0 = confusion_matrix(sub, "R0")
        c2 = confusion_matrix(sub, "R2")
        print(f"    {nm}: n={len(sub)}  level-only ACC={c0['accuracy']:.4f}  "
              f"recovery-aware ACC={c2['accuracy']:.4f}")

    # session-size sanity checks for the "287 lines" / "141 vs 142" claims
    print("\n--- line/session sanity checks ---")
    for nm, s in (("HDFS", hs), ("ZK", zs)):
        tot = sum(len(v) for v in s.values())
        print(f"  {nm}: {len(s)} sessions, {tot} lines, "
              f"empty-BlockId sessions={sum(1 for k in s if not k.strip())}")
        sizes = collections.Counter(len(v) for v in s.values())
        print(f"      session sizes: {sorted(sizes.items())}")


if __name__ == "__main__":
    main()
