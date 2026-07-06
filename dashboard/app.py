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

import hmac
import os
import secrets
from datetime import timedelta

from dotenv import load_dotenv
from flask import (Flask, abort, jsonify, redirect, render_template, request,
                   session, url_for)

load_dotenv()  # read .env so the password/keys below are available

from dashboard.analysis import deep_dive, searcher
from dashboard.config_loader import load_rules
from dashboard.datasources.live_source import LiveSource
from dashboard.datasources.news_source import GoogleNewsSource
from dashboard.datasources.sample_source import SampleSource
from dashboard.datasources.stock_search import search_stocks
from dashboard.llm.provider import MissingKeyError, get_provider
from dashboard.portfolio.engine import PaperPortfolio
from dashboard.scanner import pivot_scanner
from dashboard.scanner.edgar import EdgarClient
from dashboard.watchlists.store import WatchlistStore

app = Flask(__name__)

# ── Login wall (only active when a password is set) ─────────────────────
# Locally and over Tailscale no password is needed — leave DASHBOARD_PASSWORD
# out of .env and nothing changes. On a cloud host, set it and every page
# demands the password once per browser (remembered ~30 days).
app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.permanent_session_lifetime = timedelta(days=30)
# On Render (which sets the RENDER env var and serves over HTTPS), mark the
# login cookie HTTPS-only so it can never leak over plain HTTP.
app.config["SESSION_COOKIE_SECURE"] = bool(os.getenv("RENDER"))
app.config["SESSION_COOKIE_HTTPONLY"] = True


@app.before_request
def require_login():
    password = os.getenv("DASHBOARD_PASSWORD", "").strip()
    if not password:
        return None  # no password configured → open (local mode)
    if request.endpoint in ("login", "static"):
        return None  # the login page itself and CSS/JS stay reachable
    if session.get("authed"):
        return None
    if request.path.startswith("/api/"):
        # fetch() calls get a clear JSON error instead of a redirect page.
        return jsonify({"status": "error", "message": "Not logged in."}), 401
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        password = os.getenv("DASHBOARD_PASSWORD", "").strip()
        # compare_digest = constant-time comparison (defeats timing attacks).
        if hmac.compare_digest(request.form.get("password", ""), password):
            session.permanent = True
            session["authed"] = True
            return redirect(url_for("home"))
        error = "Wrong password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# One shared instance of each data source is plenty for a local app.
# rules.yaml decides whether prices are live (Yahoo Finance) or sample.
PRICE_SOURCE_NAME = load_rules().get("data", {}).get("price_source", "sample")
prices = LiveSource() if PRICE_SOURCE_NAME == "live" else SampleSource()
news = GoogleNewsSource()
# Watchlists own the universe now: the AI analysis runs on the union of
# every watchlist, and the portfolio asks the catalogue about risk flags.
watchlists = WatchlistStore()
portfolio = PaperPortfolio(prices, flags_source=watchlists.flags_by_symbol)
edgar = EdgarClient()


def find_asset(symbol):
    """A stock the user has ever added to a watchlist (catalogue lookup),
    or None. For free-range browsing of anything else, see resolve_asset."""
    return watchlists.get_stock(symbol)


def resolve_asset(symbol):
    """Free-range lookup: any US-listed symbol gets a ticker page, whether
    it's watchlisted or not. Watchlisted stocks come from the catalogue;
    unknown ones are looked up on Yahoo (exact ticker match)."""
    asset = find_asset(symbol)
    if asset:
        return asset
    try:
        for match in search_stocks(symbol):
            if match["symbol"].upper() == symbol.upper():
                return {"symbol": match["symbol"], "name": match["name"],
                        "type": match["type"], "flags": []}
    except RuntimeError:
        pass  # search down → treat as not found
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
    """The per-ticker detail page — works for ANY US-listed symbol, not
    just watchlisted ones. <path:...> lets symbols like BRK/B (which
    contain a slash) work in the URL."""
    asset = resolve_asset(symbol)
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
    """Run a fresh analysis of every WATCHLISTED stock (the union of all
    watchlists — searching/browsing is free, only tracked stocks get the
    paid AI treatment). Takes a minute or two."""
    try:
        provider = get_provider()
    except MissingKeyError as e:
        # Friendly message instead of a crash if the API key isn't set up yet.
        return jsonify({"status": "error", "message": str(e)}), 400

    universe = watchlists.all_tracked_assets()
    if not universe:
        return jsonify({"status": "error",
                        "message": "No stocks to analyse — add some to a "
                                   "watchlist first."}), 400

    try:
        result = searcher.run_analysis(provider, prices, universe=universe)
    except Exception as e:
        return jsonify({"status": "error", "message": f"Analysis failed: {e}"}), 500

    return jsonify({"status": "ok", **result})


@app.route("/api/scanner")
def api_scanner():
    """Hand the browser the most recent pivot scan (or 'none yet')."""
    result = pivot_scanner.load_latest()
    if result is None:
        return jsonify({"status": "none"})
    return jsonify({"status": "ok", **result})


@app.route("/api/scan", methods=["POST"])
def api_scan():
    """Run a fresh EDGAR scan for newly disclosed AI pivots.
    Takes a minute or two: EDGAR searches + one AI request per candidate."""
    try:
        provider = get_provider()
    except MissingKeyError as e:
        return jsonify({"status": "error", "message": str(e)}), 400

    try:
        result = pivot_scanner.run_scan(provider, edgar)
    except Exception as e:
        return jsonify({"status": "error", "message": f"Scan failed: {e}"}), 500

    return jsonify({"status": "ok", **result})


@app.route("/api/portfolio")
def api_portfolio():
    """The paper portfolio: value, holdings, history for the graph."""
    return jsonify({"status": "ok", **portfolio.summary()})


@app.route("/api/portfolio/sync", methods=["POST"])
def api_portfolio_sync():
    """Make the paper portfolio mirror the latest shortlist."""
    latest = searcher.load_latest()
    if latest is None:
        return jsonify({"status": "error",
                        "message": "Run an analysis first — the portfolio "
                                   "buys from the shortlist."}), 400
    trades = portfolio.sync_to_shortlist(latest["shortlist"])
    return jsonify({"status": "ok", "trades_made": trades, **portfolio.summary()})


@app.route("/api/portfolio/reset", methods=["POST"])
def api_portfolio_reset():
    """Start the pretend portfolio over from fresh cash."""
    portfolio.reset()
    return jsonify({"status": "ok", **portfolio.summary()})


@app.route("/api/ticker/<path:symbol>")
def api_ticker(symbol):
    """Everything the detail page needs in one call: price history for the
    chart, statistics, news headlines, the quick-screen row, the cached
    deep dive (if one was generated before), and which watchlists hold it."""
    asset = resolve_asset(symbol)
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
        "data_source": PRICE_SOURCE_NAME,
        "in_watchlists": watchlists.lists_containing(symbol),
    })


# ── Watchlists & free-range search ──────────────────────────────────────

@app.route("/api/search")
def api_search():
    """Free-range lookup: ?q=ticker-or-company-name → US-listed matches.
    Plain data lookup, no AI — browsing costs nothing."""
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"status": "ok", "results": []})
    try:
        return jsonify({"status": "ok", "results": search_stocks(query)})
    except RuntimeError as e:
        return jsonify({"status": "error", "message": str(e)}), 502


@app.route("/api/watchlists")
def api_watchlists():
    """All watchlists plus the stock catalogue (for names/flags)."""
    return jsonify({"status": "ok", **watchlists.summary()})


@app.route("/api/watchlists", methods=["POST"])
def api_watchlist_create():
    """Create a watchlist: {name, tag?}. Colours rotate if no tag given."""
    body = request.get_json(silent=True) or {}
    try:
        wl = watchlists.create(body.get("name"), body.get("tag"))
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    return jsonify({"status": "ok", "watchlist": wl})


@app.route("/api/watchlists/<wl_id>", methods=["POST", "DELETE"])
def api_watchlist_update(wl_id):
    """POST {name?, tag?} renames/re-colours; DELETE removes the list
    (the stocks themselves stay in the catalogue and in any other list)."""
    try:
        if request.method == "DELETE":
            watchlists.delete(wl_id)
            return jsonify({"status": "ok"})
        body = request.get_json(silent=True) or {}
        wl = watchlists.update(wl_id, body.get("name"), body.get("tag"))
        return jsonify({"status": "ok", "watchlist": wl})
    except KeyError:
        return jsonify({"status": "error", "message": "Unknown watchlist"}), 404
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route("/api/watchlists/<wl_id>/stocks", methods=["POST"])
def api_watchlist_add_stock(wl_id):
    """Add a stock to a watchlist: {symbol, name?, type?}. The catalogue
    keeps one entry per stock, so flags survive remove/re-add."""
    body = request.get_json(silent=True) or {}
    symbol = (body.get("symbol") or "").strip().upper()
    if not symbol:
        return jsonify({"status": "error", "message": "No symbol given."}), 400
    # Fill in name/type from the resolver if the browser didn't send them.
    stock = {"symbol": symbol, "name": body.get("name"), "type": body.get("type")}
    if not stock["name"]:
        resolved = resolve_asset(symbol)
        if resolved is None:
            return jsonify({"status": "error",
                            "message": f"Couldn't find {symbol} on a US exchange."}), 404
        stock = resolved
    try:
        watchlists.add_stock(wl_id, stock)
    except KeyError:
        return jsonify({"status": "error", "message": "Unknown watchlist"}), 404
    return jsonify({"status": "ok", **watchlists.summary()})


@app.route("/api/watchlists/<wl_id>/stocks/<path:symbol>", methods=["DELETE"])
def api_watchlist_remove_stock(wl_id, symbol):
    """Take a stock out of one watchlist. If that was its last list, the
    next analysis won't include it (and the next portfolio sync sells it)."""
    try:
        watchlists.remove_stock(wl_id, symbol)
    except KeyError:
        return jsonify({"status": "error", "message": "Unknown watchlist"}), 404
    return jsonify({"status": "ok", **watchlists.summary()})


@app.route("/api/ticker/<path:symbol>/deep-dive", methods=["POST"])
def api_deep_dive(symbol):
    """Generate (or refresh) the plain-English deep dive for one ticker.
    Costs one AI request; the result is cached for future visits."""
    try:
        provider = get_provider()
    except MissingKeyError as e:
        return jsonify({"status": "error", "message": str(e)}), 400

    asset = resolve_asset(symbol)
    if asset is None:
        return jsonify({"status": "error", "message": "Unknown ticker"}), 404

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
    # host="0.0.0.0" makes the dashboard reachable from Leon's OTHER devices
    # (phone via Tailscale or home Wi-Fi) — not just this Mac. It is still
    # private: nothing on the public internet can reach a home machine.
    app.run(debug=True, host="0.0.0.0", port=5001)
