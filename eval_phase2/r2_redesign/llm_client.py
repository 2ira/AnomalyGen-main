"""Shared ChatAnywhere client. Key only from env; never written to disk.

Uses stdlib urllib so the run does not depend on the openai package.
"""
import json
import os
import urllib.error
import urllib.request


def openai_client():
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("OPENAI_API_KEY is not set")
    base = os.environ.get("OPENAI_BASE_URL", "https://api.chatanywhere.tech/v1")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o")
    timeout = float(os.environ.get("OPENAI_TIMEOUT", "180"))
    client = {"key": key, "base": base.rstrip("/"), "timeout": timeout}
    return client, model, base


def chat(client, model, prompt, max_tokens=8192, temperature=0):
    url = client["base"] + "/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": "Bearer " + client["key"],
            "Content-Type": "application/json",
        },
        method="POST",
    )
    last = None
    for attempt in range(1, 6):
        try:
            with urllib.request.urlopen(req, timeout=client["timeout"]) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:400]
            last = RuntimeError(f"HTTP {e.code}: {detail}")
            if e.code in (403, 429, 500, 502, 503) and attempt < 5:
                import time
                time.sleep(min(2 ** attempt, 30))
                continue
            raise last from e
        except Exception as e:
            last = e
            if attempt < 5:
                import time
                time.sleep(min(2 ** attempt, 30))
                continue
            raise
    else:
        raise last
    choices = data.get("choices") or []
    text = ""
    finish = None
    if choices:
        text = (choices[0].get("message") or {}).get("content") or ""
        finish = choices[0].get("finish_reason")
    usage_raw = data.get("usage") or {}
    usage = {
        "prompt_tokens": usage_raw.get("prompt_tokens") or 0,
        "completion_tokens": usage_raw.get("completion_tokens") or 0,
        "total_tokens": usage_raw.get("total_tokens") or 0,
    }
    return text, usage, finish
