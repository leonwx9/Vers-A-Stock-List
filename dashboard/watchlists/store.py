"""
store.py — watchlists: the user's own folders of stocks.

Think of it like a music library:
  - the CATALOGUE is the song library — every stock ever added, stored ONCE,
    with the facts that belong to the stock itself (name, type, risk flags);
  - each WATCHLIST is a playlist — an id, a display name, a colour tag,
    and an ordered list of ticker symbols;
  - MEMBERSHIP is a symbol appearing in a watchlist's list. The same symbol
    can sit in many watchlists while its data exists only once.

The "universe" the AI analysis runs on is simply the union of every
watchlist (all_tracked_assets) — searching/browsing stocks costs nothing,
only stocks the user deliberately tracks get the paid AI treatment.

Everything lives in data/watchlists.json. On first run the file is created
from config/universe.yaml — the old fixed 98-ticker list becomes the
default "CMC Invest — Single Share List" watchlist, risk flags preserved.
"""

import json
import secrets
from pathlib import Path

from ..config_loader import load_universe

STATE_PATH = Path(__file__).parent.parent / "data" / "watchlists.json"

DEFAULT_LIST_NAME = "CMC Invest — Single Share List"

# The colours offered for new watchlists (the UI cycles through these).
# A tag is {"kind": "color", "value": ...} rather than a bare string so a
# later upgrade to icons/emojis is a new "kind", not a restructure.
TAG_PALETTE = ["#0f9d6e", "#3b82d6", "#d13c3c", "#c98a12", "#8b5cd6", "#6b6b6b"]


def _new_id():
    # A short random id that never changes, so renaming a watchlist can't
    # break anything that points at it.
    return "wl-" + secrets.token_hex(4)


class WatchlistStore:
    def __init__(self, state_path=None, seed_universe=None):
        """seed_universe — injectable for tests; defaults to universe.yaml,
        which is only used ONCE (the first-run migration)."""
        self.state_path = Path(state_path or STATE_PATH)
        self._seed_universe = seed_universe
        self.state = self._load()

    # ── State on disk ───────────────────────────────────────────────────
    def _load(self):
        if self.state_path.exists():
            with open(self.state_path) as f:
                return json.load(f)
        return self._migrate_from_universe()

    def _migrate_from_universe(self):
        """First run: turn the old fixed universe into the default watchlist
        so nothing is lost."""
        seed = self._seed_universe if self._seed_universe is not None else load_universe()
        stocks = {
            a["symbol"]: {"name": a["name"], "type": a["type"], "flags": a["flags"]}
            for a in seed
        }
        state = {
            "stocks": stocks,  # the catalogue: symbol -> facts about the stock
            "watchlists": [{
                "id": _new_id(),
                "name": DEFAULT_LIST_NAME,
                "tag": {"kind": "color", "value": TAG_PALETTE[0]},
                "symbols": [a["symbol"] for a in seed],
            }],
        }
        self.state = state
        self._save()
        return state

    def _save(self):
        self.state_path.parent.mkdir(exist_ok=True)
        with open(self.state_path, "w") as f:
            json.dump(self.state, f, indent=2)

    # ── Reading ─────────────────────────────────────────────────────────
    def summary(self):
        """Everything the watchlists panel displays."""
        return {
            "watchlists": [
                {**wl, "count": len(wl["symbols"])} for wl in self.state["watchlists"]
            ],
            "stocks": self.state["stocks"],
        }

    def all_tracked_assets(self):
        """Every stock sitting in AT LEAST ONE watchlist — the universe the
        AI analysis runs on. Same shape load_universe() returned, so the
        searcher/portfolio code didn't have to change."""
        tracked = []
        seen = set()
        for wl in self.state["watchlists"]:
            for symbol in wl["symbols"]:
                if symbol in seen:
                    continue  # in several watchlists → analysed once
                seen.add(symbol)
                info = self.state["stocks"][symbol]
                tracked.append({"symbol": symbol, **info})
        return sorted(tracked, key=lambda a: a["symbol"])

    def flags_by_symbol(self):
        """symbol -> set of risk flags, for the portfolio's buy check."""
        return {s: set(info["flags"]) for s, info in self.state["stocks"].items()}

    def get_stock(self, symbol):
        """The catalogue entry for a symbol (with its symbol included),
        or None if we've never seen it."""
        info = self.state["stocks"].get(symbol)
        return {"symbol": symbol, **info} if info else None

    def lists_containing(self, symbol):
        """Ids of every watchlist this symbol sits in."""
        return [wl["id"] for wl in self.state["watchlists"] if symbol in wl["symbols"]]

    def _find(self, wl_id):
        for wl in self.state["watchlists"]:
            if wl["id"] == wl_id:
                return wl
        raise KeyError(f"No watchlist with id {wl_id}")

    # ── Managing watchlists ─────────────────────────────────────────────
    def create(self, name, tag=None):
        name = (name or "").strip()
        if not name:
            raise ValueError("A watchlist needs a name.")
        if tag is None:
            # Rotate through the palette so new lists get distinct colours.
            used = len(self.state["watchlists"])
            tag = {"kind": "color", "value": TAG_PALETTE[used % len(TAG_PALETTE)]}
        wl = {"id": _new_id(), "name": name, "tag": tag, "symbols": []}
        self.state["watchlists"].append(wl)
        self._save()
        return wl

    def update(self, wl_id, name=None, tag=None):
        """Rename and/or re-tag a watchlist (id never changes)."""
        wl = self._find(wl_id)
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("A watchlist needs a name.")
            wl["name"] = name
        if tag is not None:
            wl["tag"] = tag
        self._save()
        return wl

    def delete(self, wl_id):
        wl = self._find(wl_id)
        self.state["watchlists"].remove(wl)
        self._save()

    # ── Managing membership ─────────────────────────────────────────────
    def add_stock(self, wl_id, stock):
        """Put a stock into a watchlist. `stock` is {symbol, name, type}
        (e.g. straight from a search result). If the catalogue already
        knows the symbol, the existing entry — including its risk flags —
        is kept; a brand-new symbol starts with no flags."""
        wl = self._find(wl_id)
        symbol = stock["symbol"]
        if symbol not in self.state["stocks"]:
            self.state["stocks"][symbol] = {
                "name": stock.get("name", symbol),
                "type": stock.get("type", "stock"),
                "flags": stock.get("flags", []),
            }
        if symbol not in wl["symbols"]:
            wl["symbols"].append(symbol)
        self._save()

    def remove_stock(self, wl_id, symbol):
        """Take a stock out of ONE watchlist. It stays in the catalogue
        (so its flags are remembered if re-added) and stays analysed as
        long as any other watchlist still holds it."""
        wl = self._find(wl_id)
        if symbol in wl["symbols"]:
            wl["symbols"].remove(symbol)
            self._save()
