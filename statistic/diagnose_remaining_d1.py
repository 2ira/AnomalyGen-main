#!/usr/bin/env python3
"""Why combined D1 is still ~79% after the unreached-entry refill."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "statistic"))
from coverage_stats import covered_templates, load_generated, read_source_templates, skeleton  # noqa: E402
from refill_unreached_templates import enclosing_method, fqcn_from_path, instantiate, LINE_RE  # noqa: E402

SOURCE = ROOT / "hadoop/hadoop-hdfs-project/log_templates.txt"
HDFS_ROOT = ROOT / "hadoop/hadoop-hdfs-project"
ARCHIVED = ROOT / "output/log_events/final_logs.json"
HADOOP_OUT = ROOT / "output/hadoop"
START_NODES = ROOT / "output/hadoop/start_nodes.txt"
ENTRIES = ROOT / "statistic/x5_out/unreached_entries_resolved.txt"
OUT = ROOT / "statistic/x5_out/remaining_d1_diagnosis.json"

ARCHIVED_DIRS = {
    "DataNode_run", "DataStreamer_run", "BlockManager_run", "BlockManager_processReport",
    "DFSClient_addLocatedBlocksRefresh", "Receiver_processOp", "FsDatasetAsyncDiskService_run",
    "PendingReconstructionBlocks_run", "BlockReceiver_adjustCrcFilePosition", "DataNode_transferBlocks",
}


def recs_with_path():
    recs, seen = [], set()
    for line in SOURCE.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        jp, text = m.group(1), m.group(2)
        if "src/test" in jp or "/test/" in jp:
            continue
        if text in seen:
            continue
        seen.add(text)
        recs.append({"path": jp, "text": text, "fqcn": fqcn_from_path(jp)})
    return recs


def load_analyzed_blobs():
    sources = []
    merges = []
    timed_out = []
    dirs_ok = []
    dirs_fail = []
    simple_ok = set()
    for d in sorted(HADOOP_OUT.iterdir()):
        if not d.is_dir() or d.name in {"entries", "parsed_logs", "block_labels"}:
            continue
        if "javacg" in d.name:
            continue
        ext = d / "extracted_methods.json"
        merge = d / "merge_single_log.json"
        if merge.is_file():
            dirs_ok.append(d.name)
            simple_ok.add(d.name)
            try:
                merges.append(merge.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
        elif d.name not in ARCHIVED_DIRS:
            dirs_fail.append(d.name)
        if ext.is_file():
            try:
                data = json.loads(ext.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                for v in data.values():
                    if isinstance(v, dict) and v.get("source_code"):
                        sources.append(v["source_code"])
        if merge.is_file():
            try:
                txt = merge.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "Failed to get a response" in txt:
                timed_out.append(d.name)
    return sources, merges, timed_out, dirs_ok, dirs_fail, simple_ok


def start_classes():
    out = set()
    if START_NODES.exists():
        for line in START_NODES.read_text(encoding="utf-8", errors="replace").splitlines():
            if ":" in line:
                out.add(line.split(":", 1)[0].split("$")[0])
    return out


def selected_classes():
    out = set()
    if ENTRIES.exists():
        for line in ENTRIES.read_text().splitlines():
            if ":" in line:
                out.add(line.split(":", 1)[0].split("$")[0])
    return out


def main():
    recs = recs_with_path()
    templates = [r["text"] for r in recs]
    archived = load_generated(str(ARCHIVED))
    sources, merges, timed_out, dirs_ok, dirs_fail, _ = load_analyzed_blobs()
    extra = []
    for p in HADOOP_OUT.glob("*/merge_single_log.json"):
        extra.append(p.read_text(encoding="utf-8", errors="replace"))
    combined = archived + extra

    cov_old, _ = covered_templates(archived, templates)
    cov_comb, usable = covered_templates(combined, templates)
    cov_src, _ = covered_templates(archived + sources, templates)
    cov_src_only, _ = covered_templates(sources, templates)
    still = [i for i in range(len(templates)) if i not in cov_comb]

    starts = start_classes()
    selected = selected_classes()
    src_blob = "\n".join(sources)
    merge_blob = "\n".join(merges)

    cats = Counter()
    remaining_entries = []
    seen_ent = set()
    samples = defaultdict(list)
    for i in still:
        r = recs[i]
        toks = skeleton(r["text"])
        fq = r["fqcn"]
        java = HDFS_ROOT / r["path"]
        method = None
        if java.exists():
            src = java.read_text(encoding="utf-8", errors="replace")
            method = enclosing_method(src, r["text"]) or enclosing_method(src, r["text"].rstrip())
        in_src = r["text"][:40] in src_blob or (len(r["text"]) >= 20 and r["text"][:20] in src_blob)
        in_merge = r["text"][:40] in merge_blob or (len(r["text"]) >= 20 and r["text"][:20] in merge_blob)
        if len(toks) < 2:
            cat = "short_lt2"
        elif in_merge or in_src:
            cat = "reached_but_d1_miss"
        elif fq in selected:
            cat = "selected_class_not_in_extracted"
        elif fq in starts:
            cat = "in_start_nodes_not_selected"
        else:
            cat = "class_never_in_pipeline"
        cats[cat] += 1
        if len(samples[cat]) < 5:
            samples[cat].append({"fqcn": fq, "method": method, "text": r["text"][:120], "ntok": len(toks)})
        if len(toks) >= 2 and cat != "short_lt2":
            meth = method or "unknown"
            sig = f"{fq}:{meth}()"
            if sig not in seen_ent:
                seen_ent.add(sig)
                remaining_entries.append({"sig": sig, "cat": cat, "text": r["text"][:80]})

    still_long = cats["reached_but_d1_miss"] + cats["selected_class_not_in_extracted"] + cats["in_start_nodes_not_selected"] + cats["class_never_in_pipeline"]
    ceiling = len(cov_comb) + still_long  # if every long miss were hit; shorts remain
    # 90% of 2886 = 2598, need max(0, 2598-combined)
    need90 = max(0, int(0.90 * len(templates) + 0.999) - len(cov_comb))

    summary = {
        "universe": len(templates),
        "archived_hit": len(cov_old),
        "combined_hit": len(cov_comb),
        "combined_pct": round(100.0 * len(cov_comb) / len(templates), 2),
        "source_harvest_hit": len(cov_src),
        "source_harvest_pct": round(100.0 * len(cov_src) / len(templates), 2),
        "new_source_only_hit": len(cov_src_only),
        "usable_ge2": len(usable),
        "d1_ceiling_if_all_long": f"{len(usable)}/{len(templates)} = {100.0*len(usable)/len(templates):.2f}%",
        "remaining": len(still),
        "remaining_by_cause": dict(cats),
        "need_for_90pct": need90,
        "new_merge_dirs": len(dirs_ok),
        "new_fail_empty_graph": len(dirs_fail),
        "merge_files_with_api_timeout_string": len(timed_out),
        "remaining_long_entries": len(remaining_entries),
        "samples": samples,
        "note": (
            "short_lt2 can never count under D1 min_tokens=2. "
            "reached_but_d1_miss = format (prefix) already in extracted/merge text but token subsequence still fails. "
            "in_start_nodes_not_selected = logging class is in start_nodes.txt but was not one of the 325 refill entries. "
            "class_never_in_pipeline = not even listed as a log-relevant start."
        ),
    }
    OUT.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT.parent / "remaining_entries.txt").write_text(
        "\n".join(e["sig"] for e in remaining_entries) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: summary[k] for k in summary if k != "samples"}, indent=2, ensure_ascii=False))
    print("--- samples ---")
    for cat, rows in samples.items():
        print(f"[{cat}]")
        for s in rows:
            print(f"  {s['fqcn']}:{s['method']}  ntok={s['ntok']}  {s['text'][:90]}")


if __name__ == "__main__":
    main()
