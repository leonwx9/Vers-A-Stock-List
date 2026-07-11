"""
journal.py — Leon's own notebook of event-timing STRATEGIES.

A strategy is a repeatable pattern like "when a key oil chokepoint closes
during conflict, energy-exposed assets tend to spike; when peace is
restored, they retrace" — a recipe for WHEN to research buying or selling,
never which specific stock and never an instruction to trade. Nothing in
this module ever touches the paper portfolio, the scanner, or the
analysis engine — the Lab is information-only by construction.

Every strategy is tagged with its `origin`: "leon" (written by hand) or
"ai" (suggested by the brainstorm feature). That tag is set HERE, by the
code paths that create entries — never accepted as input from the browser
— so the MINE/AI badge in the UI can't be spoofed, and editing an
AI-suggested entry never quietly relabels it as Leon's own thinking.
"""

import secrets
from datetime import datetime

from ..storage import FileDoc, get_doc


def _new_id():
    # A short random id that never changes, so editing/deleting a
    # strategy can always find it again (same trick as watchlist ids).
    return "strat-" + secrets.token_hex(4)


def _clean_list(value):
    """Turn whatever the browser sent (a list, or nothing) into a list of
    trimmed, non-empty strings."""
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


class StrategyJournal:
    def __init__(self, state_path=None):
        # state_path — tests point this at a temp file; normally the
        # document lives wherever storage.py says (file, or cloud database).
        self.doc = FileDoc(state_path) if state_path else get_doc("strategies")
        self.state = self._load()

    # ── Saved state ─────────────────────────────────────────────────────
    def _load(self):
        return self.doc.load() or {"strategies": []}

    def _refresh(self):
        """Re-read before acting — on the cloud, two server workers share
        one database, and each must see the other's saved changes."""
        saved = self.doc.load()
        if saved is not None:
            self.state = saved

    def _save(self):
        self.doc.save(self.state)

    def _find(self, strategy_id):
        for s in self.state["strategies"]:
            if s["id"] == strategy_id:
                return s
        raise KeyError(f"No strategy with id {strategy_id}")

    # ── Reading ─────────────────────────────────────────────────────────
    def list(self):
        """Every saved strategy, newest first."""
        self._refresh()
        return list(reversed(self.state["strategies"]))

    def get(self, strategy_id):
        """One strategy by id, or None if it's gone (e.g. deleted since a
        scan referenced it)."""
        self._refresh()
        for s in self.state["strategies"]:
            if s["id"] == strategy_id:
                return s
        return None

    # ── Writing ─────────────────────────────────────────────────────────
    def create(self, fields, origin):
        """Add a new strategy. `origin` is ALWAYS supplied by the calling
        code path (the journal API route hardcodes "leon"; the brainstorm
        module hardcodes "ai") — it is never read out of `fields`, so the
        browser can't forge which badge an entry gets."""
        self._refresh()
        name = str(fields.get("name", "")).strip()
        description = str(fields.get("description", "")).strip()
        if not name:
            raise ValueError("A strategy needs a name.")
        if not description:
            raise ValueError("A strategy needs a description.")
        if origin not in ("leon", "ai"):
            raise ValueError(f"Invalid strategy origin: {origin!r}")

        now = datetime.now().isoformat(timespec="seconds")
        strategy = {
            "id": _new_id(),
            "origin": origin,
            "name": name,
            "description": description,
            "entry_trigger": str(fields.get("entry_trigger", "")).strip(),
            "exit_trigger": str(fields.get("exit_trigger", "")).strip(),
            "assets": _clean_list(fields.get("assets")),
            "risk_notes": str(fields.get("risk_notes", "")).strip(),
            "tags": _clean_list(fields.get("tags")),
            "created_at": now,
            "updated_at": now,
        }
        self.state["strategies"].append(strategy)
        self._save()
        return strategy

    def update(self, strategy_id, fields):
        """Edit a strategy's own fields. `origin` is deliberately NOT
        accepted here — editing an AI-suggested strategy never turns it
        into one of Leon's own; the badge is permanent history, not a
        current setting."""
        self._refresh()
        strategy = self._find(strategy_id)

        if "name" in fields:
            name = str(fields["name"]).strip()
            if not name:
                raise ValueError("A strategy needs a name.")
            strategy["name"] = name
        if "description" in fields:
            description = str(fields["description"]).strip()
            if not description:
                raise ValueError("A strategy needs a description.")
            strategy["description"] = description
        for key in ("entry_trigger", "exit_trigger", "risk_notes"):
            if key in fields:
                strategy[key] = str(fields[key]).strip()
        for key in ("assets", "tags"):
            if key in fields:
                strategy[key] = _clean_list(fields[key])

        strategy["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._save()
        return strategy

    def delete(self, strategy_id):
        self._refresh()
        strategy = self._find(strategy_id)
        self.state["strategies"].remove(strategy)
        self._save()
