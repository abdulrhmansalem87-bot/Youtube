"""Glue between the audit format and the pipeline: writes the review package and decides whether upload is allowed.

Upload is blocked (strict mode) while any affiliate placeholder remains, the brief is not publishable, or the
required on-screen method notes have not been confirmed by the renderer. This function never uploads anything.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import calculator, charts, description, episode, thumbnails


def prepare_episode(out_dir, amount: float = 100000, start: int = 2021, end: int = 2025,
                    links: dict | None = None, ledger: dict | None = None) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    brief = episode.build_brief(amount, start, end, ledger=ledger)
    (out / "brief.json").write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    results = calculator.run_scenarios(amount, start, end)
    chart_paths = charts.scenario_charts(results, out, start, end)
    thumbs = thumbnails.make_pair(brief, out)  # A/B pair for YouTube Test & Compare
    review_text = description.render_description(brief["question_ar"], brief["chapters"], links)
    (out / "description.txt").write_text(review_text, encoding="utf-8")
    blockers = list(brief["blockers"])
    placeholders = description.unresolved_placeholders(review_text)
    if placeholders:
        blockers.append("affiliate placeholders unresolved: " + ", ".join(placeholders))
    blockers.append("narration not recorded (owner voice) and render not run")
    warnings = []
    if brief["receipt"]["status"] != "ok":
        warnings.append("predictions receipt segment dropped: " + brief["receipt"]["reason"])
    return {"out": str(out), "charts": chart_paths, "thumbnails": thumbs["variants"], "brief": brief, "blockers": blockers,
            "warnings": warnings, "on_screen_required": brief["on_screen_required"],
            "upload_allowed": not blockers}
