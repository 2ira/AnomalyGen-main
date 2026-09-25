#!/usr/bin/env python3
"""Run auto_run.py on resolved unreached HDFS entries (callgraph already in MySQL)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT.parent / ".env.local"
ENTRIES = ROOT / "statistic/x5_out/unreached_entries_resolved.txt"
LOG = ROOT / "statistic/x5_out/unreached_auto_run.log"
BATCH = 6
DEPTH = "2"


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


def entry_dir_name(entry: str) -> str:
    parts = entry.split(":", 1)
    fqcn = parts[0]
    method_with_params = parts[1]
    simple_class_name = fqcn.split("$")[-1] if "$" in fqcn else fqcn.split(".")[-1]
    method_name = method_with_params[: method_with_params.find("(")]
    return f"{simple_class_name}_{method_name}"


def is_complete(entry: str) -> bool:
    d = ROOT / "output" / "hadoop" / entry_dir_name(entry)
    if d.name in ARCHIVED_DIRS:
        return True
    return (d / "merge_single_log.json").is_file()


ARCHIVED_DIRS = {
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


def reset_incomplete(entry: str) -> None:
    """auto_run skips any existing entry dir, so drop dirs that never merged."""
    d = ROOT / "output" / "hadoop" / entry_dir_name(entry)
    if d.name in ARCHIVED_DIRS:
        return
    if d.is_dir() and not (d / "merge_single_log.json").is_file():
        shutil.rmtree(d)


def main():
    load_env()
    os.environ["JAVA_HOME"] = "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"
    os.environ["PATH"] = os.environ["JAVA_HOME"] + "/bin:/opt/homebrew/bin:" + os.environ.get("PATH", "")
    os.environ["PYTHONPATH"] = str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")
    os.chdir(ROOT)
    entries = [e.strip() for e in ENTRIES.read_text().splitlines() if e.strip()]
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else len(entries)
    entries = entries[start : start + limit]
    pending = []
    seen_dirs = set()
    for e in entries:
        name = entry_dir_name(e)
        if is_complete(e):
            continue
        if name in seen_dirs:
            continue
        reset_incomplete(e)
        pending.append(e)
        seen_dirs.add(name)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as log:
        log.write(f"\n# start={start} n={len(pending)} (of {len(entries)})\n")
        log.flush()
        for i in range(0, len(pending), BATCH):
            chunk = pending[i : i + BATCH]
            log.write(f"# batch {i}-{i+len(chunk)}\n")
            log.flush()
            cmd = [
                sys.executable,
                "main/auto_run.py",
                "--project_dir",
                "hadoop",
                "--depth",
                DEPTH,
                "--entry_functions",
                *chunk,
            ]
            r = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, env=os.environ.copy())
            log.write(f"# batch exit {r.returncode}\n")
            log.flush()
            print(f"batch {i}-{i+len(chunk)} exit={r.returncode}", flush=True)


if __name__ == "__main__":
    main()
