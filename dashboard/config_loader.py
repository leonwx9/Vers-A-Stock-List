"""
config_loader.py — reads the two YAML config files so the rest of the app
never has to know where configuration lives.
"""

from pathlib import Path

import yaml

# The config/ folder sits next to this file, so this works no matter which
# directory you start the app from.
CONFIG_DIR = Path(__file__).parent / "config"


def load_universe():
    """Return the list of assets (dicts with symbol, name, type, flags)."""
    with open(CONFIG_DIR / "universe.yaml") as f:
        data = yaml.safe_load(f)
    assets = data["assets"]
    # Not every entry lists flags — give the missing ones an empty list so
    # code elsewhere can always write `asset["flags"]` without checking first.
    for asset in assets:
        asset.setdefault("flags", [])
    return assets


def load_rules():
    """Return the rules dict (portfolio / analysis / scanner sections)."""
    with open(CONFIG_DIR / "rules.yaml") as f:
        return yaml.safe_load(f)
