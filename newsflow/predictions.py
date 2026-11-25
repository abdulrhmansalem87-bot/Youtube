"""Predictions receipt ("كشف حساب التوقعات").

A JSON ledger records each public prediction: who said it, the asset, the number,
the due date and the original source link. After the due date the actual value is
fetched from a free source and compared. Neutral tone: only the speaker's own
published number and its source link are shown.

Free data sources:
- usd_egp and gold_usd_oz: fawazahmed0/currency-api (daily snapshots on jsDelivr,
  no key, history by date, includes EGP and XAU). Not an official CBE rate.
- policy_rate: no free API; the actual value and its source link must be entered
  by hand in the ledger (actual_value, actual_source_url).
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Callable, Optional
from urllib.request import Request, urlopen

LEDGER_PATH = Path(__file__).resolve().parent.parent / "config" / "predictions_ledger.json"
DISCLAIMER_AR = "ليست نصيحة استثمارية"
ASSETS = {
    "usd_egp": {"label_ar": "الدولار مقابل الجنيه", "unit_ar": "جنيه", "decimals": 2},
    "gold_usd_oz": {"label_ar": "الذهب (أوقية)", "unit_ar": "دولار", "decimals": 0},
    "policy_rate": {"label_ar": "سعر الفائدة", "unit_ar": "%", "decimals": 2},
}
REQUIRED = ("id", "speaker", "asset", "predicted_value", "stated_on", "due_date", "source_url")
API_URLS = (
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{d}/v1/currencies/usd.json",
    "https://{d}.currency-api.pages.dev/v1/currencies/usd.json",
)
DEFAULT_TOLERANCE_PCT = 3.0


def validate_entry(entry: dict) -> list[str]:
    errors = [f"missing {key}" for key in REQUIRED if entry.get(key) in (None, "")]
    if entry.get("asset") not in ASSETS:
        errors.append("unknown asset")
    if entry.get("source_url") and not str(entry["source_url"]).startswith("https://"):
        errors.append("source_url must be https")
    for key in ("stated_on", "due_date"):
        try:
            date.fromisoformat(str(entry.get(key)))
        except ValueError:
            errors.append(f"bad {key}")
    try:
        float(entry.get("predicted_value"))
    except (TypeError, ValueError):
        errors.append("predicted_value must be a number")
    return errors


def load_ledger(path: Path = LEDGER_PATH) -> dict:
    ledger = json.loads(Path(path).read_text(encoding="utf-8"))
    for entry in ledger.get("predictions", []):
        errors = validate_entry(entry)
        if errors:
            raise ValueError(f"ledger entry {entry.get('id')!r}: {', '.join(errors)}")
    return ledger


def save_ledger(ledger: dict, path: Path = LEDGER_PATH) -> None:
    Path(path).write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _get_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "NewsFlowPredictions/1.0"})
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_actual(asset: str, on: str, getter: Callable[[str], dict] = _get_json) -> float:
    """Actual value of an automatically priced asset on a date (YYYY-MM-DD)."""
    if asset not in ("usd_egp", "gold_usd_oz"):
        raise ValueError(f"{asset} has no free API; enter actual_value by hand")
    last_error: Optional[Exception] = None
    for template in API_URLS:
        try:
            rates = getter(template.format(d=on))["usd"]
            if asset == "usd_egp":
                return float(rates["egp"])
            return 1.0 / float(rates["xau"])
        except Exception as exc:  # try the mirror
            last_error = exc
    raise RuntimeError(f"could not fetch {asset} for {on}: {last_error}")


def evaluate(entry: dict, actual: float) -> dict:
    predicted = float(entry["predicted_value"])
    diff = actual - predicted
    diff_pct = diff / predicted * 100 if predicted else 0.0
    tolerance = float(entry.get("tolerance_pct", DEFAULT_TOLERANCE_PCT))
    hit = abs(diff_pct) <= tolerance
    return {
        "actual_value": round(actual, 4),
        "diff": round(diff, 4),
        "diff_pct": round(diff_pct, 2),
        "tolerance_pct": tolerance,
        "verdict": "hit" if hit else "miss",
    }


def settle_due(ledger: dict, today: date, getter: Callable[[str], dict] = _get_json) -> list[str]:
    """Settle every unsettled prediction whose due date has passed. Returns settled ids."""
    settled = []
    for entry in ledger.get("predictions", []):
        if entry.get("result") or date.fromisoformat(entry["due_date"]) > today:
            continue
        if entry["asset"] == "policy_rate":
            if entry.get("actual_value") is None or not entry.get("actual_source_url"):
                continue
            actual = float(entry["actual_value"])
        else:
            actual = fetch_actual(entry["asset"], entry["due_date"], getter)
            entry["actual_source_url"] = API_URLS[0].format(d=entry["due_date"])
        entry["result"] = evaluate(entry, actual)
        settled.append(entry["id"])
    return settled


def hit_rate(ledger: dict) -> dict:
    results = [e["result"]["verdict"] for e in ledger.get("predictions", []) if e.get("result")]
    hits = results.count("hit")
    total = len(results)
    return {"hits": hits, "total": total, "percent": round(hits / total * 100) if total else None}


def _num(value: float, asset: str) -> str:
    return f"{value:,.{ASSETS[asset]['decimals']}f}"


def receipt_card(entry: dict, counter: dict) -> dict:
    """Arabic on-screen texts for the before/after card of one settled prediction."""
    result = entry["result"]
    asset = entry["asset"]
    info = ASSETS[asset]
    marker = "✔ توقع صحيح" if result["verdict"] == "hit" else "✘ لم يتحقق"
    sign = "+" if result["diff"] >= 0 else "-"
    counter_text = (
        f"إجمالي الإصابات: {counter['hits']} من {counter['total']}" if counter["total"] else ""
    )
    return {
        "title_ar": f"كشف حساب التوقعات: {info['label_ar']}",
        "before_ar": f"التوقع: {_num(float(entry['predicted_value']), asset)} {info['unit_ar']}",
        "after_ar": f"الفعلي: {_num(result['actual_value'], asset)} {info['unit_ar']}",
        "diff_ar": f"الفرق: {sign}{abs(result['diff_pct'])}%",
        "marker_ar": marker,
        "counter_ar": counter_text,
        "speaker_ar": f"قاله: {entry['speaker']} بتاريخ {entry['stated_on']}",
    }


def receipt_metadata(ledger: dict) -> dict:
    settled = [e for e in ledger.get("predictions", []) if e.get("result")]
    counter = hit_rate(ledger)
    title = "كشف حساب التوقعات: ماذا قيل وماذا حدث فعلا؟"
    lines = [title, ""]
    for e in settled:
        card = receipt_card(e, counter)
        lines += [
            f"- {ASSETS[e['asset']]['label_ar']}: {e['speaker']} توقع {_num(float(e['predicted_value']), e['asset'])} "
            f"بتاريخ {e['stated_on']}، والفعلي {_num(e['result']['actual_value'], e['asset'])} "
            f"({card['marker_ar']}).",
            f"  المصدر الأصلي للتوقع: {e['source_url']}",
            f"  مصدر القيمة الفعلية: {e.get('actual_source_url', '')}",
        ]
    if counter["total"]:
        lines += ["", f"إجمالي الإصابات: {counter['hits']} من {counter['total']} ({counter['percent']}%)"]
    lines += [
        "",
        "نعرض الرقم المنشور كما قاله صاحبه مع مصدره، دون تعليق على النوايا. "
        "هامش الإصابة المعتمد هو الفرق المسموح بالنسبة المئوية المذكور لكل توقع.",
        DISCLAIMER_AR,
        "#كشف_حساب_التوقعات #WealthRadar",
    ]
    return {"title": title, "description": "\n".join(lines), "counter": counter}


def main(argv: list[str]) -> int:
    if argv[:1] != ["settle"]:
        print("usage: python -m newsflow.predictions settle [--today YYYY-MM-DD]")
        return 2
    today = date.fromisoformat(argv[argv.index("--today") + 1]) if "--today" in argv else date.today()
    ledger = load_ledger()
    ids = settle_due(ledger, today)
    save_ledger(ledger)
    print(json.dumps({"settled": ids, "hit_rate": hit_rate(ledger)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
