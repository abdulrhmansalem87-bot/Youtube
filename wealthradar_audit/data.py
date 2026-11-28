"""Verified data snapshot for the Money Audit format.

Every series carries its source URL. Values were read from the cited pages on 2026-11-26.
`refresh_hint` says where to re-read a series; update the snapshot and `SNAPSHOT_DATE` together.
A value that is not verified must be marked verified=False (or left out): calculator and episode
builders refuse to produce publish-ready output from unverified points.
"""
from __future__ import annotations

SNAPSHOT_DATE = "2026-11-26"

# Official annual-average EGP per USD (World Bank WDI PA.NUS.FCRF).
# Caveat: this is the official rate. In 2022-early 2024 the parallel-market rate was weaker.
USD_EGP_AVG = {
    "values": {2020: 15.7592, 2021: 15.6445, 2022: 19.1604, 2023: 30.6264, 2024: 45.2993, 2025: 49.2278},
    "source": "World Bank WDI PA.NUS.FCRF, official exchange rate, period average",
    "url": "https://api.worldbank.org/v2/country/EGY/indicator/PA.NUS.FCRF?format=json&date=2019:2025",
    "verified": True,
}

# LBMA gold price, annual average, USD per troy ounce.
GOLD_USD_OZ_AVG = {
    "values": {2020: 1769.72, 2021: 1799.42, 2022: 1801.13, 2023: 1943.44, 2024: 2387.98, 2025: 3441.58},
    "source": "LBMA gold price annual average (BCRP series PM05570XA)",
    "url": "https://estadisticas.bcrp.gob.pe/estadisticas/series/anuales/resultados/PM05570XA/html",
    "verified": True,
}

# Egypt consumer-price inflation, annual average, percent (World Bank WDI via FRED).
EGYPT_CPI_INFLATION = {
    "values": {2020: 5.0449, 2021: 5.2140, 2022: 13.8957, 2023: 33.8848, 2024: 28.2706, 2025: 14.0735},
    "source": "World Bank WDI FP.CPI.TOTL.ZG via FRED FPCPITOTLZGEGY",
    "url": "https://fred.stlouisfed.org/data/FPCPITOTLZGEGY",
    "verified": True,
}

# Certificate method (decided with the owner 2026-11-26): each January the saver rolls the whole amount into the
# best NBE certificate rate available that month, and earns that annual rate for the year. Only sourced rates.
# Not modelled: sales windows, caps, "new money only" limits, early-exit rules, tax. Years: the rate applies to that year.
CERTIFICATE_RATE = {
    "values": {2021: 11.0, 2022: 11.0, 2023: 25.0, 2024: 27.0, 2025: 30.0},
    "by_year": {
        2021: {"rate": 11.0, "note": "highest NBE certificate rate at start of 2021",
               "url": "https://www.masrawy.com/news/news-banking/details/2021/1/8/1947209/"},
        2022: {"rate": 11.0, "note": "NBE Platinum fixed certificate, up to 11% in Dec 2021 / Jan 2022",
               "url": "https://www.bnok24.com/2021/12/%D8%A3%D8%B3%D8%B9%D8%A7%D8%B1-%D8%A7%D9%84%D9%81%D8%A7%D8%A6%D8%AF%D8%A9-%D8%B9%D9%84%D9%89-%D8%B4%D9%87%D8%A7%D8%AF%D8%A7%D8%AA-%D8%A7%D8%AF%D8%AE%D8%A7%D8%B1-%D8%A7%D9%84%D8%A8%D9%86%D9%83-%D8%A7/"},
        2023: {"rate": 25.0, "note": "1-year certificate launched 4 Jan 2023 by NBE and Banque Misr, stopped 31 Jan 2023 (22.5% if paid monthly)",
               "url": "https://www.almasryalyoum.com/news/details/2784538"},
        2024: {"rate": 27.0, "note": "27% certificate, NBE, reported 14 Jan 2024 (tenor not confirmed from the page text)",
               "url": "https://www.bnok24.com/2024/01/%D8%A3%D8%B3%D8%B9%D8%A7%D8%B1-%D8%A7%D9%84%D9%81%D8%A7%D8%A6%D8%AF%D8%A9-%D8%B9%D9%84%D9%89-%D8%B4%D9%87%D8%A7%D8%AF%D8%A7%D8%AA-%D8%A7%D8%AF%D8%AE%D8%A7%D8%B1-%D8%A7%D9%84%D8%A8%D9%86%D9%83-31/"},
        2025: {"rate": 30.0, "note": "3-year stepped certificate, 30% in year one (then 25%, 20%), NBE and Banque Misr, 7 Jan 2025",
               "url": "https://www.elaosboa.com/2010003/"},
    },
    "source": "Egyptian press reports of NBE certificate rates (per-year URLs in by_year)",
    "url": "https://www.almasryalyoum.com/news/details/2784538",
    "verified": True,
    "gaps": [
        "March-May 2022: an 18% NBE/Banque Misr certificate existed (launched 21 Mar 2022, stopped 30 May 2022); a January-only rule misses it",
        "January 2023 rate (25%) was available only from 4 to 31 January 2023",
        "2024 tenor and 2025 stepped structure are approximations of a plain annual rate",
    ],
}

# Official pegs, for the Gulf segment (gold in USD terms is the same as in pegged SAR/AED terms).
GULF_PEGS = {"SAR_per_USD": 3.75, "AED_per_USD": 3.6725}

# Consumer-price inflation, annual average, percent (World Bank WDI FP.CPI.TOTL.ZG).
GULF_INFLATION = {
    "SAU": {"values": {2021: 3.1300, 2022: 2.5442, 2023: 2.4739, 2024: 1.5010, 2025: 2.0356},
            "url": "https://api.worldbank.org/v2/country/SAU/indicator/FP.CPI.TOTL.ZG?format=json&date=2021:2025"},
    "ARE": {"values": {2021: 0.1799, 2022: 5.2912, 2023: 1.6267, 2024: 1.6634, 2025: 1.2509},
            "url": "https://api.worldbank.org/v2/country/ARE/indicator/FP.CPI.TOTL.ZG?format=json&date=2021:2025"},
    "verified": True,
}

SOURCES = {
    "usd_egp": USD_EGP_AVG,
    "gold": GOLD_USD_OZ_AVG,
    "inflation": EGYPT_CPI_INFLATION,
    "certificate": CERTIFICATE_RATE,
}


TROY_OUNCE_GRAMS = 31.1034768


def series(name: str) -> dict[int, float]:
    return dict(SOURCES[name]["values"])


def source_lines(names=("inflation", "usd_egp", "gold", "certificate")) -> list[str]:
    lines = []
    for n in names:
        if n == "certificate":
            lines += [f"شهادات البنك الأهلي {y}: {v['url']}" for y, v in sorted(CERTIFICATE_RATE["by_year"].items())]
        elif n in SOURCES:
            lines.append(f"{SOURCES[n]['source']}: {SOURCES[n]['url']}")
    lines += [f"Gulf inflation {k}: {GULF_INFLATION[k]['url']}" for k in ("SAU", "ARE")]
    return lines
