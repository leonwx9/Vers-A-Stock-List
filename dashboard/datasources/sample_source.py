"""
sample_source.py — FAKE price data for building and testing the dashboard.

It generates a realistic-looking daily price path for each ticker using a
"random walk" (each day the price nudges up or down a little, like a real
chart). The walk is seeded from the ticker's name, so the same ticker always
produces the same data — that makes the app stable to develop against and
easy to test. Milestone 6 swaps this class for a live source behind the same
PriceSource interface.

Each day is a full OHLC bar (Open, High, Low, Close — what candlestick
charts are drawn from) plus a trading volume.
"""

import random
import zlib
from datetime import date, timedelta

from .base import PriceSource

# Rough ballpark price per ticker so the fake data feels plausible (an AAPL
# at $6 would look silly). These are approximations, NOT real market prices.
BASE_PRICES = {
    "MSFT": 430, "INTC": 22, "AMD": 165, "AAPL": 230, "TSLA": 250,
    "SMCI": 40, "AMZN": 210, "TSM": 190, "BRK/B": 465, "MSTR": 350,
    "META": 560, "VOO": 520, "NVDA": 130, "BABA": 85, "PLTR": 90,
    "GOOGL": 175, "GOOG": 177, "COIN": 220, "PYPL": 70, "DIS": 100,
    "BA": 180, "NKE": 75, "SOFI": 12, "CRWD": 350, "SHOP": 95,
    "NVO": 95, "PFE": 27, "ARM": 130, "V": 290, "GME": 22,
    "COST": 900, "NFLX": 700, "BAC": 42, "ADBE": 480, "SNOW": 140,
    "RIOT": 12, "UBER": 75, "JD": 35, "RIVN": 12, "NIO": 5,
    "ABNB": 140, "XYZ": 70, "CCL": 22, "SCHD": 28, "SPOT": 480,
    "GE": 180, "MRNA": 45, "PANW": 340, "JPM": 220, "RDDT": 120,
    "CRM": 280, "HD": 380, "KO": 65, "NOC": 480, "PBR/A": 14,
    "SOXL": 30, "SQQQ": 8, "TMF": 45, "TQQQ": 70, "VXX": 14,
    "MU": 110, "TEM": 55, "MSTU": 8, "VTI": 280, "QCOM": 170,
    "HOOD": 30, "TTD": 100, "ANET": 110, "IBIT": 55, "RGTI": 10,
    "RKLB": 25, "TSLL": 12, "ASTS": 30, "HIMS": 20, "SMH": 250,
    "ELF": 120, "UNH": 520, "AVGO": 180, "APP": 350, "TTWO": 160,
    "CL": 95, "OXY": 55, "TMC": 4, "VRT": 110, "WMT": 90,
}

# How many days of fake history we always generate internally. Requests for
# fewer days get the most recent slice of this one series — that way a 30-day
# request and a 120-day request agree on what "yesterday's price" was.
FULL_SERIES_DAYS = 400


class SampleSource(PriceSource):
    """Deterministic fake prices behind the standard PriceSource socket."""

    def get_history(self, symbol, days):
        if days > FULL_SERIES_DAYS:
            days = FULL_SERIES_DAYS

        # crc32 turns the ticker string into a stable number — unlike Python's
        # built-in hash(), it gives the same answer every time the app runs.
        seed = zlib.crc32(symbol.encode())
        rng = random.Random(seed)

        # Unknown symbols (e.g. a test ticker) get a seed-derived base price.
        close = BASE_PRICES.get(symbol, 10 + seed % 490)
        # Typical daily volume, also seed-derived (5M–80M shares).
        base_volume = 5_000_000 + seed % 75_000_000

        today = date.today()
        history = []
        for i in range(FULL_SERIES_DAYS):
            day = today - timedelta(days=FULL_SERIES_DAYS - 1 - i)
            prev_close = close

            # The day's move: average drift ~0, daily wobble ~2% — roughly
            # what a typical stock does.
            close = max(0.5, prev_close * (1 + rng.gauss(0.0005, 0.02)))
            # Open near yesterday's close; high/low wrap around open & close.
            open_ = max(0.5, prev_close * (1 + rng.gauss(0, 0.005)))
            hi_lo_pad = abs(rng.gauss(0, 0.008))
            high = max(open_, close) * (1 + hi_lo_pad)
            low = min(open_, close) * (1 - hi_lo_pad)
            # Busier days on bigger moves — like real markets.
            move_pct = abs(close - prev_close) / prev_close
            volume = int(base_volume * (0.7 + rng.random() * 0.6 + move_pct * 20))

            history.append({
                "date": day.isoformat(),
                "open": round(open_, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "volume": volume,
            })

        # Hand back only the most recent `days` entries.
        return history[-days:]
