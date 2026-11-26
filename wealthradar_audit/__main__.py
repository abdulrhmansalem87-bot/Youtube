"""CLI: python -m wealthradar_audit --amount 100000 --start 2021 --end 2025 --out output/episode3"""
from __future__ import annotations

import argparse
from . import hook


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="wealthradar_audit")
    ap.add_argument("--amount", type=float, default=100000)
    ap.add_argument("--start", type=int, default=2021)
    ap.add_argument("--end", type=int, default=2025)
    ap.add_argument("--out", default="output/episode3")
    a = ap.parse_args(argv)
    res = hook.prepare_episode(a.out, a.amount, a.start, a.end)
    brief = res["brief"]
    for note in res["on_screen_required"]:
        print(f"[AUDIT] on-screen note required: {note}")
    print(f"[AUDIT] brief + {len(res['charts'])} charts written to {res['out']}; publishable={brief['publishable']} upload_allowed={res['upload_allowed']}")
    for w in res["warnings"]:
        print(f"[AUDIT] WARNING: {w}")
    for b in res["blockers"]:
        print(f"[AUDIT] BLOCKER: {b}")
    return 0 if res["upload_allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
