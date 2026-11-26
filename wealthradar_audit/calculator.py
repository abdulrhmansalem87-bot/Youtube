"""Scenario calculator: what happens to an amount of EGP held as cash, dollars, gold or a bank certificate.

Method: annual-average basis. Value at `end_year` is the amount's growth between the `start_year` and
`end_year` annual averages. Inflation is compounded over start_year+1 .. end_year. Real value is
nominal value divided by cumulative inflation. This is a historical comparison, not advice or a forecast.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import data

CAVEATS = [
    "حساب تقريبي على متوسط السنة وليس لتاريخ شراء أو بيع بعينه",
    "سعر الدولار هو السعر الرسمي المتوسط، والسوق الموازي كان مختلفا في 2022 وأوائل 2024",
    "لا يشمل رسوم الشراء والبيع أو الضرائب",
    "هذه مقارنة تاريخية وليست توصية أو توقعا",
]


@dataclass
class Result:
    key: str
    name_ar: str
    start_value: float
    end_value: float | None
    real_end_value: float | None
    multiple: float | None
    real_return_pct: float | None
    status: str = "ok"  # ok | blocked
    missing: list = field(default_factory=list)
    verified: bool = True

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def _need(series: dict, years: list[int], label: str) -> list[str]:
    return [f"{label}:{y}" for y in years if y not in series]


def cumulative_inflation(start_year: int, end_year: int, cpi: dict | None = None) -> float:
    cpi = cpi if cpi is not None else data.series("inflation")
    years = list(range(start_year + 1, end_year + 1))
    missing = _need(cpi, years, "inflation")
    if missing:
        raise ValueError("missing inflation data: " + ", ".join(missing))
    factor = 1.0
    for y in years:
        factor *= 1 + cpi[y] / 100.0
    return factor


def _result(key, name, amount, multiple, inflation, verified=True) -> Result:
    end = amount * multiple
    real = end / inflation
    return Result(key, name, amount, end, real, multiple, (real / amount - 1) * 100, verified=verified)


def run_scenarios(amount: float, start_year: int, end_year: int, certificate_rates: dict | None = None) -> list[Result]:
    if amount <= 0 or end_year <= start_year:
        raise ValueError("amount must be positive and end_year after start_year")
    fx, gold = data.series("usd_egp"), data.series("gold")
    infl = cumulative_inflation(start_year, end_year)
    results = [_result("cash", "كاش", amount, 1.0, infl)]

    miss = _need(fx, [start_year, end_year], "usd_egp")
    results.append(_blocked("dollar", "دولار", amount, miss) if miss else
                   _result("dollar", "دولار", amount, fx[end_year] / fx[start_year], infl))

    miss = _need(fx, [start_year, end_year], "usd_egp") + _need(gold, [start_year, end_year], "gold")
    if miss:
        results.append(_blocked("gold", "ذهب", amount, miss))
    else:
        ratio = (gold[end_year] * fx[end_year]) / (gold[start_year] * fx[start_year])
        results.append(_result("gold", "ذهب", amount, ratio, infl))

    rates = certificate_rates if certificate_rates is not None else data.series("certificate")
    years = list(range(start_year + 1, end_year + 1))
    miss = _need(rates, years, "certificate_rate")
    if miss:
        results.append(_blocked("certificate", "شهادة بنك", amount, miss))
    else:
        mult = 1.0
        for y in years:
            mult *= 1 + rates[y] / 100.0
        verified = bool(data.CERTIFICATE_RATE["verified"]) and certificate_rates is None
        results.append(_result("certificate", "شهادة بنك", amount, mult, infl, verified=verified))
    return results


def _blocked(key, name, amount, missing) -> Result:
    return Result(key, name, amount, None, None, None, None, status="blocked", missing=missing, verified=False)


def publishable(results: list[Result]) -> tuple[bool, list[str]]:
    problems = []
    for r in results:
        if r.status != "ok":
            problems.append(f"{r.key} blocked: missing {', '.join(r.missing)}")
        elif not r.verified:
            problems.append(f"{r.key} uses unverified data")
    return (not problems, problems)
