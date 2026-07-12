"""
bulletin.py — Leon's own "Fix bulletin": a small persistent, editable note
where he tracks future work items. Nothing here is read by any other part
of the app — it's a sticky note, not configuration.

Seeded once, the first time it's ever loaded, with the known housekeeping
items from the Strategy Lab review. After that first save, whatever Leon
writes — including deleting the seed entirely — is exactly what's kept.
"""

from .storage import get_doc

MAX_LENGTH = 20000  # a generous cap so a runaway paste can't blow up the saved file

SEED_TEXT = """\
- The scan-history file (setups_history.json) grows forever — add a size cap someday.
- News headlines are outside text: a maliciously worded headline could try to steer the AI's phrasing. _Contained_ by the citation/counter-case guardrails, but worth remembering.
- Duplicate source links can appear if the AI cites the same headline twice — cosmetic only.
- The 8am scheduler only fires while the Mac app is running — revisit (launchd, or a cloud cron) if that's ever not enough.
"""


def load():
    """The bulletin's saved text, seeding it with the known items the
    first time this is ever called. An empty/never-saved bulletin gets
    the seed; once Leon has saved anything — including clearing it out —
    that's respected instead."""
    doc = get_doc("bulletin").load()
    if doc is None:
        save(SEED_TEXT)
        return {"text": SEED_TEXT}
    return doc


def save(text):
    """Save the bulletin's text (capped — see MAX_LENGTH). Returns the
    text actually saved, so the caller can hand it straight back."""
    text = str(text)[:MAX_LENGTH]
    get_doc("bulletin").save({"text": text})
    return text
