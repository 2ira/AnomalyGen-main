#!/usr/bin/env python3
"""Sequential ChatAnywhere jobs: smoke, CoT v2, X7, ctx v2.

Key from OPENAI_API_KEY only. Host https://api.chatanywhere.tech/v1.
"""
import os
import subprocess
import sys
import json
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.dirname(HERE)
REPO = os.path.dirname(EVAL)
PY = sys.executable


def run(script, extra=None):
    cmd = [PY, os.path.join(HERE, script)] + (extra or [])
    print("==>", " ".join(cmd), flush=True)
    env = os.environ.copy()
    env.setdefault("OPENAI_BASE_URL", "https://api.chatanywhere.tech/v1")
    env.setdefault("OPENAI_MODEL", "gpt-4o")
    rc = subprocess.call(cmd, cwd=REPO, env=env)
    if rc != 0:
        raise SystemExit(f"{script} failed rc={rc}")


def smoke():
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("OPENAI_API_KEY is not set")
    base = os.environ.get("OPENAI_BASE_URL", "https://api.chatanywhere.tech/v1").rstrip("/")
    body = json.dumps({
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o"),
        "messages": [{"role": "user", "content": "Reply with exactly: ping-ok"}],
        "max_tokens": 16,
        "temperature": 0,
    }).encode()
    req = urllib.request.Request(
        base + "/chat/completions",
        data=body,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    text = data["choices"][0]["message"]["content"]
    print("SMOKE", text, "finish", data["choices"][0].get("finish_reason"), flush=True)
    if "ping-ok" not in (text or "").lower() and "ping" not in (text or "").lower():
        print("SMOKE unexpected body; continuing if HTTP 200", flush=True)


def main():
    smoke()
    run("build_feasibility_v2.py")
    run("build_x7.py")
    run("build_ctx_v2.py")
    run("run_feasibility_v2.py", ["--variant", "cot"])
    run("run_x7.py")
    run("run_ctx_v2.py")
    run("score_feasibility_v2.py", [
        "--pred",
        os.path.join(EVAL, "eval_results", "feasibility_v2", "pred_cot.jsonl"),
    ])
    run("score_x7.py")
    run("score_ctx_v2.py", [
        "--pred",
        os.path.join(EVAL, "eval_results", "ctx_v2", "filled.jsonl"),
    ])
    print("ALL JOBS DONE", flush=True)


if __name__ == "__main__":
    main()
