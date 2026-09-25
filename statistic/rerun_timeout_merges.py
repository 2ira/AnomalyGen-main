#!/usr/bin/env python3
"""Re-run timed-out merges and inject JavaParser/source log literals into log_sequence."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from subprocess import TimeoutExpired

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT.parent / ".env.local"
HADOOP_OUT = ROOT / "output/hadoop"
TIMEOUT_LIST = ROOT / "statistic/x5_out/timeout_merge_dirs.txt"
LOG = ROOT / "statistic/x5_out/rerun_timeout_merges.log"
TIMEOUT_MARK = "Failed to get a response"

ARCHIVED = {
    "DataNode_run",
    "DataStreamer_run",
    "BlockManager_run",
    "BlockManager_processReport",
    "DFSClient_addLocatedBlocksRefresh",
    "Receiver_processOp",
    "FsDatasetAsyncDiskService_run",
    "PendingReconstructionBlocks_run",
    "BlockReceiver_adjustCrcFilePosition",
    "DataNode_transferBlocks",
}


def load_env():
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def skip_dir(d: Path) -> bool:
    if not d.is_dir() or d.name in ARCHIVED:
        return True
    if "javacg" in d.name or d.name in {"entries", "parsed_logs", "block_labels"}:
        return True
    return False


def has_source(d: Path) -> bool:
    p = d / "extracted_methods.json"
    if not p.is_file():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return isinstance(data, dict) and any(
        isinstance(v, dict) and v.get("source_code") for v in data.values()
    )


def timed_out(d: Path) -> bool:
    p = d / "merge_single_log.json"
    if not p.is_file():
        return False
    try:
        return TIMEOUT_MARK in p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def ensure_inputs(d: Path) -> None:
    pruned = d / "pruned_call_deps.txt"
    if not pruned.exists():
        pruned.write_text("", encoding="utf-8")
    pathj = d / "prune_call_path_javaparser.json"
    if not pathj.exists():
        pathj.write_text("{}", encoding="utf-8")
    ext = d / "extracted_methods.json"
    if not ext.exists():
        ext.write_text("{}", encoding="utf-8")


LLM_TIMEOUT_SEC = 90
MAX_EDGES_FOR_LLM = 25


def pruned_edge_count(d: Path) -> int:
    p = d / "pruned_call_deps.txt"
    if not p.is_file():
        return 0
    return sum(1 for line in p.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())


def run_merge(d: Path, no_llm: bool, log) -> int:
    ensure_inputs(d)
    cmd = [
        sys.executable,
        "main/merge_node.py",
        "--call_chain_file",
        str(d / "pruned_call_deps.txt"),
        "--source_mapping",
        str(d / "extracted_methods.json"),
        "--single_call_path",
        str(d / "prune_call_path_javaparser.json"),
        "--output_dir",
        str(d),
    ]
    if no_llm:
        cmd.append("--no-llm")
    log.write(f"# merge {d.name} no_llm={no_llm}\n")
    log.flush()
    try:
        r = subprocess.run(
            cmd,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=os.environ.copy(),
            timeout=None if no_llm else LLM_TIMEOUT_SEC,
        )
        rc = r.returncode
    except TimeoutExpired:
        log.write(f"# timeout {d.name} after {LLM_TIMEOUT_SEC}s; keep injected merge\n")
        log.flush()
        print(f"llm {d.name} timeout={LLM_TIMEOUT_SEC}s keep-inject", flush=True)
        return 124
    log.write(f"# exit {rc} {d.name}\n")
    log.flush()
    print(f"{'inject' if no_llm else 'llm'} {d.name} exit={rc}", flush=True)
    return rc


def main():
    load_env()
    os.environ["PYTHONPATH"] = str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")
    os.environ.setdefault("OPENAI_TIMEOUT", "300")
    os.chdir(ROOT)
    only_llm = "--llm-only" in sys.argv
    inject_only = "--inject-only" in sys.argv
    remaining_file = ROOT / "statistic/x5_out/timeout_llm_remaining.txt"

    timeout_dirs = []
    inject_dirs = []
    saved = []
    if TIMEOUT_LIST.exists():
        saved = [HADOOP_OUT / n.strip() for n in TIMEOUT_LIST.read_text().splitlines() if n.strip()]
        saved = [d for d in saved if d.is_dir()]
    for d in sorted(HADOOP_OUT.iterdir()):
        if skip_dir(d) or not has_source(d):
            continue
        if timed_out(d) or d in saved:
            timeout_dirs.append(d)
        else:
            inject_dirs.append(d)
    timeout_dirs = sorted(set(timeout_dirs), key=lambda p: p.name)
    inject_dirs = [d for d in inject_dirs if d not in timeout_dirs]
    TIMEOUT_LIST.parent.mkdir(parents=True, exist_ok=True)
    if timeout_dirs and not TIMEOUT_LIST.exists():
        TIMEOUT_LIST.write_text("\n".join(d.name for d in timeout_dirs) + "\n")

    LOG.parent.mkdir(parents=True, exist_ok=True)
    print(f"timeout_dirs={len(timeout_dirs)} inject_dirs={len(inject_dirs)}", flush=True)
    with LOG.open("a") as log:
        log.write(f"\n# timeout={len(timeout_dirs)} inject={len(inject_dirs)}\n")
        if not only_llm:
            for d in inject_dirs + timeout_dirs:
                run_merge(d, no_llm=True, log=log)
        if not inject_only:
            skipped_big = 0
            for d in timeout_dirs:
                if remaining_file.exists():
                    allow = {n.strip() for n in remaining_file.read_text().splitlines() if n.strip()}
                    if d.name not in allow:
                        continue
                if pruned_edge_count(d) > MAX_EDGES_FOR_LLM:
                    print(f"skip-big {d.name} edges={pruned_edge_count(d)} keep-inject", flush=True)
                    log.write(f"# skip-big {d.name}\n")
                    skipped_big += 1
                    continue
                run_merge(d, no_llm=False, log=log)
                time.sleep(1.5)
            log.write(f"# skipped_big={skipped_big}\n")
    print("done", flush=True)


if __name__ == "__main__":
    main()
