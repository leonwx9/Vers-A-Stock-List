"""
app.py — the front door of the dashboard.

This is a tiny web server built with Flask. When you run it, your computer
starts listening on http://localhost:5001 and serves the dashboard page to
your browser. Nothing here leaves your machine (except the AI requests the
analysis makes).

Run it from the repo folder with:
    ./venv/bin/python dashboard/app.py
"""

import sys
from pathlib import Path

# Let this file be run directly (python dashboard/app.py) while still using
# clean "from dashboard.xxx import ..." imports: add the repo folder to the
# list of places Python looks for packages.
sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, jsonify, render_template

from dashboard.analysis import searcher
from dashboard.datasources.sample_source import SampleSource
from dashboard.llm.provider import MissingKeyError, get_provider

app = Flask(__name__)


@app.route("/")
def home():
    """Serve the main (and only) dashboard page."""
    return render_template("index.html")


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
        result = searcher.run_analysis(provider, SampleSource())
    except Exception as e:
        return jsonify({"status": "error", "message": f"Analysis failed: {e}"}), 500

    return jsonify({"status": "ok", **result})


if __name__ == "__main__":
    # debug=True auto-reloads on code edits and shows helpful error pages —
    # fine because this server is local-only. Port 5001 avoids clashing with
    # macOS's own service on port 5000.
    app.run(debug=True, port=5001)
