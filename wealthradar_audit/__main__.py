"""CLI: python -m wealthradar_audit --amount 100000 --start 2021 --end 2025 --out output/episode3"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import charts, calculator, description, episode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="wealthradar_audit")
    ap.add_argument("--amount", type=float, default=100000)
    ap.add_argument("--start", type=int, default=2021)
    ap.add_argument("--end", type=int, default=2025)
    ap.add_argument("--out", default="output/episode3")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    brief = episode.build_brief(a.amount, a.start, a.end)
    (out / "brief.json").write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    results = calculator.run_scenarios(a.amount, a.start, a.end)
    paths = charts.scenario_charts(results, out, a.start, a.end)
    desc = description.render_description(brief["question_ar"], brief["chapters"])
    (out / "description.txt").write_text(desc, encoding="utf-8")
    print(f"[AUDIT] brief + {len(paths)} charts written to {out}; publishable={brief['publishable']}")
    for b in brief["blockers"]:
        print(f"[AUDIT] BLOCKER: {b}")
    return 0 if brief["publishable"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
