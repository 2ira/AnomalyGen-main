#!/usr/bin/env python3
"""Depth-3 auto_run on remaining unresolved-coverage entries (unique output dirs)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT.parent / ".env.local"
ENTRIES = ROOT / "statistic/x5_out/remaining_entries_resolved_d3.txt"
LOG = ROOT / "statistic/x5_out/remaining_d3_auto_run.log"
BATCH = 6
DEPTH = "3"


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


def main():
    load_env()
    os.environ["JAVA_HOME"] = "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home"
    os.environ["PATH"] = os.environ["JAVA_HOME"] + "/bin:/opt/homebrew/bin:" + os.environ.get("PATH", "")
    os.environ["PYTHONPATH"] = str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", "")
    os.environ["UNIQUE_ENTRY_DIRS"] = "1"
    os.environ.setdefault("OPENAI_TIMEOUT", "90")
    os.environ.setdefault("MERGE_TIMEOUT", "180")
    if os.environ.get("NO_LLM"):
        print("NO_LLM=1 (source-literal merge; skip ChatAnywhere)", flush=True)
    os.chdir(ROOT)
    entries = [e.strip() for e in ENTRIES.read_text().splitlines() if e.strip()]
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else len(entries)
    entries = entries[start : start + limit]
    LOG.parent.mkdir(parents=True, exist_ok=True)
    print(f"n={len(entries)} depth={DEPTH} unique_dirs=1", flush=True)
    with LOG.open("a") as log:
        log.write(f"\n# remaining d3 n={len(entries)} start={start}\n")
        for i in range(0, len(entries), BATCH):
            chunk = entries[i : i + BATCH]
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
            print(f"batch {i}-{i+len(chunk)} exit={r.returncode}", flush=True)
            log.write(f"# batch exit {r.returncode}\n")
            log.flush()
    print("done", flush=True)


if __name__ == "__main__":
    main()
