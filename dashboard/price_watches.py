"""
price_watches.py — Leon's own overnight price alerts: one per stock,
"tell me if it reaches this price tonight."

Checked ONCE, at the overnight scheduler's MIDDLE run (see scheduler.py's
is_middle_slot and app.py's _run_overnight_analysis) — not continuously.
Real-time, always-watching alerts are a bigger feature (a polling loop
plus a way to notify Leon) saved for another day; see the Fix bulletin.

Direction is worked out automatically from the price at the moment the
watch was set: if it was BELOW the level, the watch fires once the price
rises to meet it; if it was ABOVE, it fires once the price falls to meet
it — the plain meaning of "reaches this level," without asking Leon to
pick a direction himself.

One watch per symbol; saving a new one for a symbol replaces the old.
Fired watches are one-shot — cleared right after the run that acted on
them, win or lose (see app.py's overnight callback).
"""

from datetime import datetime

from .storage import get_doc


def load():
    """{"<symbol>": {"level": float, "set_when_price": float,
    "set_at": "YYYY-MM-DDTHH:MM:SS"}} for every symbol with an active
    watch right now."""
    return get_doc("price_watches").load() or {}


def save(watches):
    get_doc("price_watches").save(watches)


def set_watch(symbol, level, current_price):
    """Save (or replace) the watch for one symbol. `current_price` is
    the price at the moment of saving — it's what decides the watch's
    direction (see the module docstring), not stored for any other
    reason. Returns the saved watch entry."""
    watches = load()
    entry = {
        "level": level,
        "set_when_price": current_price,
        "set_at": datetime.now().isoformat(timespec="seconds"),
    }
    watches[symbol] = entry
    save(watches)
    return entry


def clear_watch(symbol):
    """Remove a symbol's watch, if it has one. A quiet no-op otherwise —
    clearing something that isn't there isn't an error."""
    watches = load()
    if symbol in watches:
        del watches[symbol]
        save(watches)


def watch_triggered(watch, current_price):
    """Has this watch's level been reached? Pure function — direction
    comes entirely from where the price was when the watch was set (see
    the module docstring): was below the level → fires on RISING to/
    through it; was above → fires on FALLING to/through it."""
    level = watch["level"]
    was_below = watch["set_when_price"] < level
    if was_below:
        return current_price >= level
    return current_price <= level


def check_all(current_prices):
    """Which saved watches have fired, given {symbol: current_price}?
    Returns {symbol: watch} for every one that has — a symbol with no
    saved watch, or whose current price wasn't supplied, is simply
    skipped (not an error; the caller may only have prices for a subset)."""
    fired = {}
    for symbol, watch in load().items():
        price = current_prices.get(symbol)
        if price is not None and watch_triggered(watch, price):
            fired[symbol] = watch
    return fired
