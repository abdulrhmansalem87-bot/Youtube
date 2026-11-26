"""Prediction-receipt segment: reuses the existing ledger and card builders in newsflow.predictions.

Only settled predictions with an original source link are shown. An empty ledger means the segment is dropped
from the episode; it is never filled with an invented prediction.
"""
from __future__ import annotations

import json
from pathlib import Path

LEDGER_PATH = Path(__file__).resolve().parent.parent / "config" / "predictions_ledger.json"


def load_ledger(path: Path = LEDGER_PATH) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"predictions": []}


def receipt_segment(ledger: dict | None = None) -> dict:
    ledger = ledger if ledger is not None else load_ledger()
    settled = [e for e in ledger.get("predictions", []) if e.get("result")]
    if not settled:
        return {"status": "empty", "reason": "no settled, sourced prediction in the ledger", "entries": [], "counter": {"hits": 0, "total": 0, "percent": None}}
    from newsflow import predictions  # existing module; imported lazily so this package stays standalone

    counter = predictions.hit_rate(ledger)
    entries = [{"id": e["id"], "card": predictions.receipt_card(e, counter), "script_ar": predictions.receipt_script(e, counter),
                "source_url": e["source_url"], "actual_source_url": e.get("actual_source_url", "")} for e in settled]
    return {"status": "ok", "entries": entries, "counter": counter}
