#!/usr/bin/env python3
"""Build feasibility_v2.jsonl from the same 40 CFG merge points.

Does not invent new GT labels. Strips leak tokens, wraps logs as generation-style
XML, keeps infeasible_reason off the prompt payload.
"""
import hashlib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.dirname(HERE)
REPO = os.path.dirname(EVAL)
sys.path.insert(0, EVAL)
sys.path.insert(0, REPO)

from build_feasibility_dataset import build  # noqa: E402
from common import write_jsonl, EVAL_DATA_DIR  # noqa: E402
from models.prompts.merge_node_info import get_merge_nodes_by_llm_v7  # noqa: E402

LEAK = re.compile(
    r"\[INFEASIBLE\]"
    r"|//\s*INFEASIBLE:[^\n]*"
    r"|_conflict:[^\n]*"
    r"|\[CALLER STATE\]"
    r"|\[MERGE[^\]]*\]"
    r"|\[STATE\]",
    re.IGNORECASE,
)


def strip_leak(text):
    if not text:
        return ""
    return re.sub(r"\n{3,}", "\n\n", LEAK.sub("", text)).strip()


def as_generation_xml(exec_text, log_text, path_id="P1"):
    """Wrap a CFG snippet the way merge_node.py stores parent/child logs."""
    exec_text = strip_leak(exec_text) or "ENTRY -> EXIT"
    log_text = strip_leak(log_text) or exec_text
    return (
        "```xml\n<merge_result>\n  <valid_paths>\n    <path>\n"
        f"      <id>{path_id}</id>\n      <eval>true</eval>\n"
        f"      <exec_flow>\n{exec_text}\n      </exec_flow>\n"
        f"      <log_sequence>\n{log_text}\n      </log_sequence>\n"
        "    </path>\n  </valid_paths>\n  <wrong_path></wrong_path>\n"
        "</merge_result>\n```"
    )


def parent_info(mp):
    # Exact concatenation used in main/merge_node.py::_merge_parent
    node = mp["caller"]
    parent_log = mp["caller_log_xml"]
    parent_code = mp.get("caller_code") or ""
    return "node name is " + node + "node log is" + str(parent_log) + "souce code:" + str(parent_code)


def child_info(mp):
    node = mp["callee"]
    child_log = mp["callee_log_xml"]
    child_code = mp.get("callee_code") or ""
    return "node name is" + node + "node log is" + str(child_log) + "source code:" + str(child_code)


def prompt_fingerprint():
    tmpl = list(get_merge_nodes_by_llm_v7("{parent_info}", "{child_info}"))[0]
    return {
        "function": "get_merge_nodes_by_llm_v7",
        "sha256": hashlib.sha256(tmpl.encode()).hexdigest(),
        "contains_eval_true_example": "<eval>true</eval>" in tmpl,
        "output_tag_rejected": "wrong_path",
        "eval_harness_edits": "none — identical to generation",
    }


def main():
    rows = build(REPO)
    out_rows = []
    for mp in rows:
        item = {
            "mp_id": mp["mp_id"],
            "caller": mp["caller"],
            "callee": mp["callee"],
            "gt": mp["gt"],
            "stratum": mp.get("stratum", "simple"),
            "infeasible_reason": mp.get("infeasible_reason") or "",
            "rationale": mp.get("rationale") or mp.get("gt_detail", {}).get("rationale", ""),
            "caller_code": mp.get("caller_code") or "",
            "callee_code": mp.get("callee_code") or "",
            "caller_log_raw_stripped": strip_leak(mp.get("caller_log", "")),
            "callee_log_raw_stripped": strip_leak(mp.get("callee_log", "")),
        }
        item["caller_log_xml"] = as_generation_xml(
            item["caller_log_raw_stripped"], item["caller_log_raw_stripped"], "P1"
        )
        item["callee_log_xml"] = as_generation_xml(
            item["callee_log_raw_stripped"], item["callee_log_raw_stripped"], "C1"
        )
        item["parent_info"] = parent_info(item)
        item["child_info"] = child_info(item)
        # Sanity: leak tokens must not appear in anything sent to the model.
        sent = item["parent_info"] + item["child_info"]
        assert not LEAK.search(sent), item["mp_id"]
        assert "infeasible_reason" not in item["parent_info"].lower()
        out_rows.append(item)

    os.makedirs(EVAL_DATA_DIR, exist_ok=True)
    path = os.path.join(EVAL_DATA_DIR, "feasibility_v2.jsonl")
    write_jsonl(path, out_rows)
    n_pos = sum(1 for r in out_rows if r["gt"] == "valid")
    n_neg = sum(1 for r in out_rows if r["gt"] != "valid")
    fp = prompt_fingerprint()
    meta = os.path.join(EVAL_DATA_DIR, "feasibility_v2_meta.json")
    import json
    with open(meta, "w", encoding="utf-8") as f:
        json.dump({"n": len(out_rows), "n_valid": n_pos, "n_infeasible": n_neg,
                   "prompt": fp, "protocol": "r2_redesign/PROTOCOL.md"}, f, indent=2)
    print(f"wrote {path}  n={len(out_rows)} valid={n_pos} infeasible={n_neg}")
    print(f"v7 sha256={fp['sha256'][:12]} eval_true_example={fp['contains_eval_true_example']}")


if __name__ == "__main__":
    main()
