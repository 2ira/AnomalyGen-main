#!/usr/bin/env python3
"""Resolve remaining long-template enclosing methods to javacg2 signatures in MySQL."""
from __future__ import annotations

import configparser
from pathlib import Path

import mysql.connector

ROOT = Path(__file__).resolve().parents[1]
ENTRIES = ROOT / "statistic/x5_out/remaining_entries.txt"
OUT = ROOT / "statistic/x5_out/remaining_entries_resolved_d3.txt"
CFG = ROOT / "mysql/config.ini"


def db():
    c = configparser.ConfigParser()
    c.read(CFG)
    return mysql.connector.connect(
        host=c.get("mysql", "host"),
        port=c.getint("mysql", "port"),
        user=c.get("mysql", "user"),
        password=c.get("mysql", "password"),
        database=c.get("mysql", "database"),
        charset="utf8mb4",
    )


def _add_like(cur, like: str, seen: set, found: list, limit: int = 8):
    cur.execute(
        f"SELECT DISTINCT caller FROM method_call WHERE caller LIKE %s LIMIT {int(limit)}",
        (like,),
    )
    for (caller,) in cur.fetchall():
        if caller not in seen:
            seen.add(caller)
            found.append(caller)


def resolve_one(cur, raw: str) -> list[str]:
    fqcn, _, rest = raw.partition(":")
    meth = rest.split("(", 1)[0]
    simple = fqcn.split(".")[-1].split("$")[-1]
    found, seen = [], set()
    if meth in {"unknown", ""}:
        cur.execute(
            "SELECT caller, COUNT(*) AS c FROM method_call "
            "WHERE caller LIKE %s OR caller LIKE %s "
            "GROUP BY caller ORDER BY c DESC LIMIT 3",
            (f"{fqcn}:%", f"{fqcn}$%:%"),
        )
        for caller, _c in cur.fetchall():
            if caller not in seen:
                seen.add(caller)
                found.append(caller)
        return found
    names = ["<init>"] if meth in {simple, fqcn.split(".")[-1]} else [meth]
    for name in names:
        _add_like(cur, f"{fqcn}:{name}(%", seen, found, 3)
        if not found:
            _add_like(cur, f"{fqcn}$%:{name}(%", seen, found, 3)
    if found:
        found = [sorted(found, key=len)[0]]
    return found


def main():
    raw = [e.strip() for e in ENTRIES.read_text().splitlines() if e.strip()]
    conn = db()
    cur = conn.cursor()
    resolved, missing = [], []
    for e in raw:
        hits = resolve_one(cur, e)
        if hits:
            resolved.extend(hits)
        else:
            missing.append(e)
    out, seen = [], set()
    for s in resolved:
        if s not in seen:
            seen.add(s)
            out.append(s)
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    miss_path = OUT.with_name("remaining_entries_unresolved_d3.txt")
    miss_path.write_text("\n".join(missing) + "\n", encoding="utf-8")
    print(f"stubs={len(raw)} resolved_sigs={len(out)} unresolved={len(missing)}")
    print("unresolved sample:", missing[:20])
    conn.close()


if __name__ == "__main__":
    main()
