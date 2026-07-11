"""
brainstorm.py — asks the AI to suggest MORE event-timing patterns.

One request, one reply: the AI sees Leon's existing journal (so it adds to
his thinking instead of repeating it) and proposes new patterns in the
same shape a journal entry has. Every suggestion is saved with
origin="ai" — permanently badged as AI-suggested, never mistaken for
Leon's own notes (see journal.py for why that badge can't be forged).

Ideas to research, never advice: the prompt says so, and nothing this
module produces can place an order — it only ever calls journal.create().
"""

import json
import re

SYSTEM_PROMPT = """\
You are a research assistant inside a private, INFORMATION-ONLY dashboard.
You suggest event-timing PATTERNS for further research — never a specific
stock to buy, never trading advice. Nothing you write is investment advice.
You respond ONLY with a JSON array — no prose before or after it."""

BRAINSTORM_PROMPT = """\
Leon researches event-driven TIMING patterns: repeatable situations where a
real-world event (war, commodity shock, a shipping chokepoint closing,
an election, a natural disaster, a central-bank surprise, etc.) tends to
cause a predictable, temporary move in certain assets or sectors. This is
about WHEN to look closer — never which specific stock, never a signal to
actually buy or sell.

Patterns already in his journal (suggest genuinely NEW ones — don't repeat
these or offer a trivial variation of one):
{existing_summary}

Suggest {count} new event-timing patterns. For EACH pattern return one JSON
object with exactly these keys:
  "name":           short name, e.g. "Oil chokepoint closure"
  "description":    1-3 plain-English sentences explaining the pattern
  "entry_trigger":  what happening in the world would make this worth
                    researching a BUY
  "exit_trigger":   what happening would make this worth researching an
                    exit
  "assets":         array of 1-4 short strings — SECTORS or asset TYPES
                    this affects (never a specific ticker)
  "risk_notes":     1-2 sentences on how this pattern can fail or reverse
  "tags":           array of 2-5 short lowercase keywords, useful for
                    searching news about this pattern later

Respond with a JSON array of {count} objects, nothing else."""


def _summarize_existing(strategies, limit=12):
    """A compact bullet list of existing strategy names/descriptions for
    the prompt — enough for the AI to avoid duplicates, without spending
    tokens on the full journal."""
    if not strategies:
        return "(the journal is empty so far)"
    lines = [f'- "{s["name"]}": {s["description"]}' for s in strategies[:limit]]
    return "\n".join(lines)


def parse_brainstorm_response(text):
    """Pull the JSON array of suggested patterns out of the AI's reply.

    Kept as a pure function so tests can feed it canned text. Validation
    of individual fields happens in run_brainstorm (it needs the count
    limit from rules.yaml); this just gets the raw list out safely.
    """
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON array found in AI reply: {text[:200]}")
    items = json.loads(cleaned[start : end + 1])
    return items if isinstance(items, list) else []


def _is_complete(item):
    """A usable suggestion needs its name, description, and BOTH triggers
    — a pattern with no trigger isn't a pattern, just a headline."""
    if not isinstance(item, dict):
        return False
    return all(str(item.get(key, "")).strip()
              for key in ("name", "description", "entry_trigger", "exit_trigger"))


def run_brainstorm(provider, journal, rules=None):
    """Ask the AI for new patterns, save the good ones, return them.

    provider — an LLM provider (from llm.provider.get_provider())
    journal  — a StrategyJournal (created entries are saved through it,
               with origin="ai" — never accepted from the AI's reply)
    rules    — the rules dict (uses rules["lab"]["brainstorm_count"])
    """
    from ..config_loader import load_rules
    rules = rules or load_rules()
    count = rules.get("lab", {}).get("brainstorm_count", 4)

    existing_summary = _summarize_existing(journal.list())
    prompt = BRAINSTORM_PROMPT.format(existing_summary=existing_summary, count=count)
    reply = provider.complete(SYSTEM_PROMPT, prompt, max_tokens=2000)
    items = parse_brainstorm_response(reply)

    created = []
    for item in items:
        if len(created) >= count:
            break
        if not _is_complete(item):
            continue  # a malformed suggestion is dropped, not guessed-at
        created.append(journal.create(item, origin="ai"))
    return created
