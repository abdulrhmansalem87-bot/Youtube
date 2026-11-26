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

# Top bank-certificate rate in force during each year, percent per year.
# Only verified points are filled. Missing years block the certificate scenario by design.
CERTIFICATE_RATE = {
    "values": {2021: 11.0},
    "source": "Masrawy, 2021-01-08: highest NBE certificate rate at the start of 2021 was 11%",
    "url": "https://www.masrawy.com/news/news-banking/details/2021/1/8/1947209/",
    "verified": True,
    "note": "2022-2025 rates still to be sourced from CBE/NBE announcements before the certificate scenario can run.",
}

# Official pegs, for the Gulf segment (gold in USD terms is the same as in pegged SAR/AED terms).
GULF_PEGS = {"SAR_per_USD": 3.75, "AED_per_USD": 3.6725}

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
    return [f"{SOURCES[n]['source']}: {SOURCES[n]['url']}" for n in names if n in SOURCES]
