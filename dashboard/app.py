"""
app.py — the front door of the dashboard.

This is a tiny web server built with Flask. When you run it, your computer
starts listening on http://localhost:5001 and serves the dashboard page to
your browser. Nothing here leaves your machine (except the AI requests the
analysis makes and the news-headline fetches).

Run it from the repo folder with:
    ./venv/bin/python dashboard/app.py
"""

import sys
from pathlib import Path

# Let this file be run directly (python dashboard/app.py) while still using
# clean "from dashboard.xxx import ..." imports: add the repo folder to the
# list of places Python looks for packages.
sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, abort, jsonify, render_template

from dashboard.analysis import deep_dive, searcher
from dashboard.config_loader import load_universe
from dashboard.datasources.news_source import GoogleNewsSource
from dashboard.datasources.sample_source import SampleSource
from dashboard.llm.provider import MissingKeyError, get_provider

app = Flask(__name__)

# One shared instance of each data source is plenty for a local app.
prices = SampleSource()
news = GoogleNewsSource()


def find_asset(symbol):
    """Look a symbol up in the universe, or None if it isn't one of ours."""
    for asset in load_universe():
        if asset["symbol"] == symbol:
            return asset
    return None


def latest_screen_for(symbol):
    """The row for this symbol from the most recent full analysis run."""
    latest = searcher.load_latest()
    if latest:
        for row in latest["rows"]:
            if row["symbol"] == symbol:
                return row
    return None


# ── Pages ───────────────────────────────────────────────────────────────

@app.route("/")
def home():
    """The main dashboard page."""
    return render_template("index.html")


@app.route("/ticker/<path:symbol>")
def ticker_page(symbol):
    """The per-ticker detail page. <path:...> lets symbols like BRK/B
    (which contain a slash) work in the URL."""
    asset = find_asset(symbol)
    if asset is None:
        abort(404)
    return render_template("ticker.html", asset=asset)


# ── Data endpoints the browser calls ────────────────────────────────────

@app.route("/api/analysis")
def api_analysis():
    """Hand the browser the most recent analysis run (or 'none yet')."""
    result = searcher.load_latest()
    if result is None:
        return jsonify({"status": "none"})
    return jsonify({"status": "ok", **result})


@app.route("/api/run-analysis", methods=["POST"])
def api_run_analysis():
    """Run a fresh analysis of all 85 tickers. Takes a minute or two —
    the browser shows a 'running' state while it waits."""
    try:
        provider = get_provider()
    except MissingKeyError as e:
        # Friendly message instead of a crash if the API key isn't set up yet.
        return jsonify({"status": "error", "message": str(e)}), 400

    try:
        result = searcher.run_analysis(provider, prices)
    except Exception as e:
        return jsonify({"status": "error", "message": f"Analysis failed: {e}"}), 500

    return jsonify({"status": "ok", **result})


@app.route("/api/ticker/<path:symbol>")
def api_ticker(symbol):
    """Everything the detail page needs in one call: price history for the
    chart, statistics, news headlines, the quick-screen row, and the cached
    deep dive (if one was generated before)."""
    asset = find_asset(symbol)
    if asset is None:
        return jsonify({"status": "error", "message": "Unknown ticker"}), 404

    return jsonify({
        "status": "ok",
        "asset": asset,
        "quote": prices.get_quote(symbol),
        "stats": prices.get_stats(symbol),
        "history": prices.get_history(symbol, days=365),
        "news": news.get_headlines(symbol, asset["name"]),
        "screen": latest_screen_for(symbol),
        "deep_dive": deep_dive.load_cached(symbol),
        "data_source": "sample",  # flipped to "live" in milestone 6
    })


@app.route("/api/ticker/<path:symbol>/deep-dive", methods=["POST"])
def api_deep_dive(symbol):
    """Generate (or refresh) the plain-English deep dive for one ticker.
    Costs one AI request; the result is cached for future visits."""
    asset = find_asset(symbol)
    if asset is None:
        return jsonify({"status": "error", "message": "Unknown ticker"}), 404

    try:
        provider = get_provider()
    except MissingKeyError as e:
        return jsonify({"status": "error", "message": str(e)}), 400

    screen = latest_screen_for(symbol)
    conviction = screen["conviction"] if screen else "unrated"
    try:
        result = deep_dive.run_deep_dive(
            provider,
            asset,
            prices.get_quote(symbol),
            news.get_headlines(symbol, asset["name"]),
            conviction,
        )
    except Exception as e:
        return jsonify({"status": "error", "message": f"Deep dive failed: {e}"}), 500

    return jsonify({"status": "ok", "deep_dive": result})


if __name__ == "__main__":
    # debug=True auto-reloads on code edits and shows helpful error pages —
    # fine because this server is local-only. Port 5001 avoids clashing with
    # macOS's own service on port 5000.
    app.run(debug=True, port=5001)
