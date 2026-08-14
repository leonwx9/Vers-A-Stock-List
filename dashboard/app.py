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
import threading
import time
from datetime import date, timedelta

from dotenv import load_dotenv
from flask import (Flask, abort, jsonify, redirect, render_template, request,
                   session, url_for)

load_dotenv()  # read .env so the password/keys below are available

from dashboard.analysis import deep_dive, searcher
from dashboard.config_loader import load_rules
from dashboard.datasources.events_source import EventNewsSource
from dashboard.datasources.live_source import LiveSource
from dashboard.datasources.news_source import GoogleNewsSource
from dashboard.datasources.sample_source import SampleSource
from dashboard.datasources.stock_search import search_stocks
from dashboard.llm.provider import (MissingKeyError, current_provider_name,
                                    get_provider, provider_source,
                                    save_provider_choice)
from dashboard import bulletin, price_watches, scheduler
from dashboard.portfolio.engine import PaperPortfolio
from dashboard.scanner import pivot_scanner
from dashboard.scanner.edgar import EdgarClient
from dashboard.strategy_lab import brainstorm as lab_brainstorm
from dashboard.strategy_lab import setup_scanner
from dashboard.strategy_lab.journal import StrategyJournal
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
# SameSite=Lax tells browsers: don't attach this cookie to requests that
# OTHER websites start (defeats "cross-site request forgery" — a malicious
# page you happen to visit firing POSTs at our API with your login cookie).
# Chrome assumes Lax when unset, but Safari doesn't — so say it explicitly.
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


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
        # A one-second pause per wrong guess makes brute-forcing the
        # password (millions of rapid guesses) impractical, while a human
        # who mistyped barely notices. Skipped in tests to keep them fast.
        if not app.config.get("TESTING"):
            time.sleep(1)
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
# The Strategy Lab: Leon's own event-timing journal, an AI brainstorm
# helper, and a news-based setup scanner. Deliberately walled off from
# the portfolio/scanner/analysis code above — it can inform Leon, but it
# has no way to place even a pretend trade.
events_source = EventNewsSource()
journal = StrategyJournal()

# One paid run at a time. A Lock is a turnstile: the first request through
# holds it until done; anyone else gets a clear "already running" answer
# instead of silently starting a second run (= double AI spend). The Run
# button is disabled in the browser too, but a second tab or the phone
# wouldn't know about that.
analysis_lock = threading.Lock()
scan_lock = threading.Lock()
lab_lock = threading.Lock()


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


def _augment_universe_with_held_stocks(universe):
    """Add every currently-held stock the given universe doesn't already
    cover, so a position never goes unreviewed just because of which
    watchlist (or, for the overnight scheduler, which slot) was chosen.
    Shared by the manual Run button and the overnight scheduler.

    Returns (universe, holdings_for_review, review_only) — review_only
    marks the appended stocks so they can never win a shortlist slot that
    belongs to the scope actually being analysed (see
    searcher.run_analysis's review_only param)."""
    positions = portfolio.current_positions()
    universe = list(universe)
    universe_symbols = {a["symbol"] for a in universe}
    review_only = set()
    for symbol in positions:
        if symbol not in universe_symbols:
            universe.append(watchlists.get_stock(symbol) or
                            {"symbol": symbol, "name": symbol,
                             "type": "stock", "flags": []})
            universe_symbols.add(symbol)
            review_only.add(symbol)
    holdings_for_review = {s: p["avg_cost"] for s, p in positions.items()}
    return universe, holdings_for_review, review_only


def _run_overnight_analysis(slot):
    """Called by the scheduler thread (see scheduler.run_overnight_once)
    when an overnight slot is due.

    The MIDDLE slot (chronologically) is special: if any of Leon's price
    watches (see price_watches.py) has been reached tonight, THIS run is
    dedicated to just those triggered stocks instead of the normal full
    analysis. Every other slot — and the middle slot too, when nothing
    has fired — runs the usual "All watchlists" analysis unchanged."""
    overnight_settings = scheduler.load_overnight_settings()
    slots = scheduler.effective_analysis_times(overnight_settings)

    if scheduler.is_middle_slot(slot, slots):
        # `prices.get_quote` is whatever the live source's most recent
        # daily bar says — Yahoo's price, cached a few minutes (see
        # LiveSource) — plenty good enough for "has this level been
        # reached tonight", which doesn't need to-the-second precision.
        watched_symbols = list(price_watches.load())
        current_prices = {s: prices.get_quote(s)["price"] for s in watched_symbols}
        fired = price_watches.check_all(current_prices)
        if fired:
            _run_price_watch_analysis(fired)
            return

    _run_full_overnight_analysis(slot)


def _run_full_overnight_analysis(slot):
    """The normal, full "All watchlists" overnight run — the same steps
    as pressing "Run analysis" manually. Raises on failure rather than
    returning a Flask response; scheduler.run_overnight_once() catches
    that and records it as the overnight settings' last_error for the
    dashboard to show."""
    provider = get_provider()  # MissingKeyError propagates — the provider
                               # gate already checked claude_code is active,
                               # but the CLI could still be missing/logged
                               # out; that's a real problem worth surfacing.
    universe, holdings_for_review, review_only = \
        _augment_universe_with_held_stocks(watchlists.all_tracked_assets())
    if not universe:
        raise ValueError("No stocks to analyse — add some to a watchlist first.")

    if not analysis_lock.acquire(blocking=False):
        raise RuntimeError(
            "Skipped — a manual analysis was already running at the "
            "scheduled time. Will try again at the next overnight slot.")
    try:
        result = searcher.run_analysis(
            provider, prices, universe=universe,
            scope_name=f"overnight ({slot} ET)",
            holdings=holdings_for_review, review_only=review_only)
        portfolio.place_orders(result["rows"], result["shortlist"],
                               result["held_reviews"])
    finally:
        analysis_lock.release()


def _run_price_watch_analysis(fired):
    """A dedicated, narrowly-scoped run for stocks whose overnight price
    watch just triggered (see price_watches.py). `fired` is
    {symbol: watch}.

    Only these symbols are analysed — place_orders() is told exactly
    that via `analyzed=`, so pending orders for every OTHER stock (from
    tonight's earlier open-session run) are left completely untouched. A
    narrowly-scoped run must never wipe out orders it has nothing new to
    say about (see the portfolio engine's place_orders docstring)."""
    symbols = list(fired)
    provider = get_provider()
    universe = [watchlists.get_stock(s) or
               {"symbol": s, "name": s, "type": "stock", "flags": []}
               for s in symbols]
    positions = portfolio.current_positions()
    holdings_for_review = {s: positions[s]["avg_cost"]
                           for s in symbols if s in positions}
    scope_name = "price watch: " + ", ".join(
        f"{s} reached ${fired[s]['level']}" for s in symbols)

    if not analysis_lock.acquire(blocking=False):
        raise RuntimeError(
            "Skipped — a manual analysis was already running when a "
            "price watch triggered. The watch stays set for next time.")
    try:
        result = searcher.run_analysis(
            provider, prices, universe=universe, scope_name=scope_name,
            holdings=holdings_for_review)
        portfolio.place_orders(result["rows"], result["shortlist"],
                               result["held_reviews"], analyzed=symbols)
    finally:
        analysis_lock.release()
        # One-shot: clear every watch this run acted on, win or lose —
        # once acted upon, tonight's trigger is done being interesting.
        # (Only reached if the lock was actually acquired — if it wasn't,
        # the watch must stay set so it can fire again next tick.)
        for s in symbols:
            price_watches.clear_watch(s)


@app.route("/api/run-analysis", methods=["POST"])
def api_run_analysis():
    """Run a fresh analysis of watchlisted stocks. The browser sends
    {"watchlist": <id>} to analyse ONE list, or "all" (the union of every
    list). Searching/browsing is free — only what's here costs AI money.

    Every currently-held stock ALSO gets reviewed for hold/sell, even if
    it's outside this run's scope — a position never goes unreviewed just
    because of which watchlist was chosen. The run then places pending
    orders (see PaperPortfolio.place_orders); there is no more instant buy."""
    try:
        provider = get_provider()
    except MissingKeyError as e:
        # Friendly message instead of a crash if the API key isn't set up yet.
        return jsonify({"status": "error", "message": str(e)}), 400

    # Which watchlist is this run scoped to? (Chosen before pressing Run.)
    body = request.get_json(silent=True) or {}
    wl_id = body.get("watchlist", "all")
    if wl_id == "all":
        universe, scope_name = watchlists.all_tracked_assets(), None
    else:
        try:
            universe = watchlists.assets_in(wl_id)
            scope_name = next(w["name"] for w in watchlists.summary()["watchlists"]
                              if w["id"] == wl_id)
        except (KeyError, StopIteration):
            return jsonify({"status": "error",
                            "message": "That watchlist no longer exists."}), 404

    universe, holdings_for_review, review_only = \
        _augment_universe_with_held_stocks(universe)

    if not universe:
        return jsonify({"status": "error",
                        "message": "No stocks to analyse — add some to a "
                                   "watchlist first."}), 400

    if not analysis_lock.acquire(blocking=False):
        return jsonify({"status": "error",
                        "message": "An analysis is already running — wait "
                                   "for it to finish."}), 409
    try:
        result = searcher.run_analysis(provider, prices, universe=universe,
                                       scope_name=scope_name,
                                       holdings=holdings_for_review,
                                       review_only=review_only)
        orders = portfolio.place_orders(result["rows"], result["shortlist"],
                                        result["held_reviews"])
    except Exception as e:
        return jsonify({"status": "error", "message": f"Analysis failed: {e}"}), 500
    finally:
        analysis_lock.release()

    return jsonify({"status": "ok", "orders_placed": orders, **result})


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

    if not scan_lock.acquire(blocking=False):
        return jsonify({"status": "error",
                        "message": "A scan is already running — wait for it "
                                   "to finish."}), 409
    try:
        result = pivot_scanner.run_scan(provider, edgar)
    except Exception as e:
        return jsonify({"status": "error", "message": f"Scan failed: {e}"}), 500
    finally:
        scan_lock.release()

    return jsonify({"status": "ok", **result})



# ── Event Strategy Lab ───────────────────────────────────────────────────
# Ideas to research, never advice — see strategy_lab/ for the full rules.

@app.route("/api/lab")
def api_lab():
    """Strategies, the latest scan, and settings — one call for the whole
    Strategy Lab. If the once-daily auto-scan is turned on and NOTHING has
    scanned today yet (automatic OR a manual "Scan now" — either satisfies
    the daily rule), kicks one off in a background thread so the page
    never waits on it."""
    settings = setup_scanner.load_settings()
    today = date.today().isoformat()
    latest = setup_scanner.load_latest()
    daily_scan_started = False

    if setup_scanner.should_auto_scan(settings, latest, today):
        try:
            get_provider()  # only bother if a key is actually configured
        except MissingKeyError:
            pass
        else:
            # Mark today as done BEFORE starting the thread — a second
            # request landing a moment later (another tab) then sees
            # last_auto_scan_date already == today and won't also fire
            # one. (The cloud's two separate worker processes could each
            # still slip through once — worst case one extra ~1-2c scan a
            # day; not worth extra machinery to prevent.)
            settings["last_auto_scan_date"] = today
            setup_scanner.save_settings(settings)
            daily_scan_started = True

            def _run_daily_scan():
                if not lab_lock.acquire(blocking=False):
                    return  # Leon is already scanning by hand — skip today's auto one
                try:
                    # The OTHER cloud worker may have just finished today's
                    # scan while this thread waited for the lock — check
                    # again right before spending anything. Shrinks the
                    # double-fire race to near-impossible; doesn't need to
                    # be perfect (worst case ~2c, harmless).
                    if setup_scanner.ran_today(setup_scanner.load_latest(), today):
                        return
                    setup_scanner.run_scan(get_provider(), events_source,
                                           journal, load_rules())
                except Exception:
                    pass  # a failed background scan just means try again tomorrow
                finally:
                    lab_lock.release()

            threading.Thread(target=_run_daily_scan, daemon=True).start()
    elif (settings.get("daily_scan") and settings.get("last_auto_scan_date") != today
          and setup_scanner.ran_today(latest, today)):
        # A manual "Scan now" already covered today — record that so the
        # check above doesn't have to re-derive it on the next page view.
        settings["last_auto_scan_date"] = today
        setup_scanner.save_settings(settings)

    return jsonify({
        "status": "ok",
        "strategies": journal.list(),
        "setups": latest,
        "settings": settings,
        "daily_scan_running": daily_scan_started,
    })


@app.route("/api/lab/strategies", methods=["POST"])
def api_lab_create_strategy():
    """Add a strategy to Leon's own journal. Always badged origin='leon'
    — the browser never gets to choose that."""
    body = request.get_json(silent=True) or {}
    try:
        strategy = journal.create(body, origin="leon")
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    return jsonify({"status": "ok", "strategy": strategy})


@app.route("/api/lab/strategies/<strategy_id>", methods=["POST", "DELETE"])
def api_lab_update_strategy(strategy_id):
    """POST edits a strategy's own fields (its MINE/AI badge never
    changes); DELETE removes it."""
    try:
        if request.method == "DELETE":
            journal.delete(strategy_id)
            return jsonify({"status": "ok"})
        body = request.get_json(silent=True) or {}
        strategy = journal.update(strategy_id, body)
        return jsonify({"status": "ok", "strategy": strategy})
    except KeyError:
        return jsonify({"status": "error", "message": "Unknown strategy"}), 404
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route("/api/lab/brainstorm", methods=["POST"])
def api_lab_brainstorm():
    """Ask the AI for new event-timing patterns, built on Leon's existing
    journal. One AI request; results are saved badged origin='ai'."""
    try:
        provider = get_provider()
    except MissingKeyError as e:
        return jsonify({"status": "error", "message": str(e)}), 400

    if not lab_lock.acquire(blocking=False):
        return jsonify({"status": "error",
                        "message": "The Lab is already busy — wait for it "
                                   "to finish."}), 409
    try:
        created = lab_brainstorm.run_brainstorm(provider, journal, load_rules())
    except Exception as e:
        return jsonify({"status": "error", "message": f"Brainstorm failed: {e}"}), 500
    finally:
        lab_lock.release()

    return jsonify({"status": "ok", "strategies": created})


@app.route("/api/lab/scan", methods=["POST"])
def api_lab_scan():
    """Fetch current event headlines and ask, in ONE AI request, whether
    any saved strategy pattern looks like it's currently in play."""
    try:
        provider = get_provider()
    except MissingKeyError as e:
        return jsonify({"status": "error", "message": str(e)}), 400

    if not lab_lock.acquire(blocking=False):
        return jsonify({"status": "error",
                        "message": "The Lab is already busy — wait for it "
                                   "to finish."}), 409
    try:
        result = setup_scanner.run_scan(provider, events_source, journal, load_rules())
    except RuntimeError as e:
        # Our own friendly messages (no strategies yet; news feed down).
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"Scan failed: {e}"}), 500
    finally:
        lab_lock.release()

    return jsonify({"status": "ok", **result})


@app.route("/api/lab/settings", methods=["POST"])
def api_lab_settings():
    """{"daily_scan": bool} — turn the once-a-day automatic scan on/off."""
    body = request.get_json(silent=True) or {}
    settings = setup_scanner.load_settings()
    if "daily_scan" in body:
        settings["daily_scan"] = bool(body["daily_scan"])
    setup_scanner.save_settings(settings)
    return jsonify({"status": "ok", "settings": settings})


@app.route("/api/portfolio")
def api_portfolio():
    """The paper portfolio: value, holdings, history, pending orders, and
    the trade log. Every call settles any orders that have become due
    against real trading sessions since the last look — self-updating,
    no button required."""
    return jsonify({"status": "ok", **portfolio.summary(),
                    "scheduler": scheduler.load_settings()})


@app.route("/api/portfolio/reset", methods=["POST"])
def api_portfolio_reset():
    """Start the pretend portfolio over from fresh cash."""
    portfolio.reset()
    return jsonify({"status": "ok", **portfolio.summary()})


@app.route("/api/scheduler", methods=["POST"])
def api_scheduler_settings():
    """{"enabled": bool} — turn the daily 8am order-fill run on/off. Free:
    no AI is ever involved here, only settling orders that already have a
    plan (the same process_fills()/snapshot() every page view already
    triggers, just guaranteed to happen once a day on its own)."""
    body = request.get_json(silent=True) or {}
    settings = scheduler.load_settings()
    if "enabled" in body:
        settings["enabled"] = bool(body["enabled"])
    scheduler.save_settings(settings)
    return jsonify({"status": "ok", "scheduler": settings})


@app.route("/api/overnight")
def api_overnight_settings():
    """The overnight analysis scheduler's saved settings, plus the
    EFFECTIVE run times right now (Leon's own times if he's customised
    them, else rules.yaml's defaults) — the dashboard always has real
    numbers to show, whether or not he's ever touched the setting."""
    settings = scheduler.load_overnight_settings()
    return jsonify({"status": "ok", "settings": settings,
                    "effective_times_et": scheduler.effective_analysis_times(settings)})


@app.route("/api/overnight", methods=["POST"])
def api_overnight_settings_save():
    """{"enabled": bool?, "times_et": [3 "HH:MM" strings]?} — either or
    both at once. Free: this only decides WHEN the scheduler thread tries
    to run — it still only actually fires while the toggle above is ALSO
    set to Leon's own Claude account (the provider gate lives in
    scheduler.py, checked fresh on every tick)."""
    body = request.get_json(silent=True) or {}
    settings = scheduler.load_overnight_settings()
    if "times_et" in body:
        try:
            scheduler.validate_analysis_times(body["times_et"])
        except ValueError as e:
            return jsonify({"status": "error", "message": str(e)}), 400
        settings["times_et"] = body["times_et"]
    if "enabled" in body:
        settings["enabled"] = bool(body["enabled"])
    scheduler.save_overnight_settings(settings)
    return jsonify({"status": "ok", "settings": settings,
                    "effective_times_et": scheduler.effective_analysis_times(settings)})


# ── AI provider: Leon's own Claude account, or a paid API key ────────────

@app.route("/api/llm")
def api_llm_settings():
    """Which AI provider is in effect right now, and whether that comes
    from Leon's dashboard toggle or just .env's LLM_PROVIDER default."""
    return jsonify({"status": "ok", "provider": current_provider_name(),
                    "source": provider_source()})


@app.route("/api/llm", methods=["POST"])
def api_llm_settings_save():
    """{"provider": "claude_code" | "openrouter" | "anthropic"} — Leon's
    connect/disconnect toggle for using his own Claude account. Saved in
    shared storage, so the cloud copy shows the same choice too: pressing
    an AI button there while set to claude_code just gets
    ClaudeCodeProvider's own friendly "Mac only" message — correct
    behaviour, since no cloud server can ever use Leon's account login."""
    body = request.get_json(silent=True) or {}
    try:
        save_provider_choice(body.get("provider"))
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    return jsonify({"status": "ok", "provider": current_provider_name(),
                    "source": provider_source()})


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
        "watch": price_watches.load().get(symbol),
    })


# ── Overnight price watches: "tell me if this reaches $X tonight" ────────

@app.route("/api/ticker/<path:symbol>/watch", methods=["POST"])
def api_set_price_watch(symbol):
    """{"level": float} — set (or replace) tonight's overnight price
    watch for one stock. Direction is worked out automatically from
    today's price vs the level Leon chose — see price_watches.py. Free:
    this only saves a number; the AI spend happens later, if and only if
    the level is actually reached (see app.py's overnight callback)."""
    body = request.get_json(silent=True) or {}
    try:
        level = float(body.get("level"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Give a real price."}), 400
    if level <= 0:
        return jsonify({"status": "error", "message": "Give a real price."}), 400

    current = prices.get_quote(symbol)["price"]
    watch = price_watches.set_watch(symbol, level, current)
    return jsonify({"status": "ok", "watch": watch})


@app.route("/api/ticker/<path:symbol>/watch", methods=["DELETE"])
def api_clear_price_watch(symbol):
    """Remove tonight's price watch for one stock, if it has one."""
    price_watches.clear_watch(symbol)
    return jsonify({"status": "ok"})


@app.route("/api/watches")
def api_watches():
    """Every active overnight price watch, for the Stock Searcher panel's
    compact list — checked once, at the overnight scheduler's middle
    slot, not continuously."""
    return jsonify({"status": "ok", "watches": price_watches.load()})


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
            data_source=PRICE_SOURCE_NAME,
        )
    except Exception as e:
        return jsonify({"status": "error", "message": f"Deep dive failed: {e}"}), 500

    return jsonify({"status": "ok", "deep_dive": result})


# ── Fix bulletin: Leon's own editable list of future to-dos ──────────────
# A sticky note, not configuration — nothing else in the app reads this.

@app.route("/api/bulletin")
def api_bulletin():
    """The bulletin's saved text (seeded with known housekeeping items the
    very first time it's ever loaded)."""
    return jsonify({"status": "ok", **bulletin.load()})


@app.route("/api/bulletin", methods=["POST"])
def api_bulletin_save():
    """{"text": str} — overwrite the bulletin with Leon's own edit."""
    body = request.get_json(silent=True) or {}
    text = bulletin.save(body.get("text", ""))
    return jsonify({"status": "ok", "text": text})


if __name__ == "__main__":
    # Port 5001 avoids clashing with macOS's own service on port 5000.
    #
    # Two ways to run:
    #   normal (default)      — reachable from other devices (phone via
    #                           Tailscale or home Wi-Fi), debugger OFF.
    #   DASHBOARD_DEBUG=1     — auto-reload + rich error pages, but bound to
    #                           THIS Mac only (127.0.0.1).
    # They're mutually exclusive on purpose: Flask's debugger can execute
    # code on this Mac from the browser, so it must never be reachable by
    # anything else on the network.
    debug = os.getenv("DASHBOARD_DEBUG", "").strip() == "1"

    # The two optional background schedulers — order fills (rules.yaml →
    # scheduler.fill_hour_sydney) and overnight analysis (→
    # scheduler.analysis_times_et, off by default, only actually fires
    # while Leon's Claude account is the active provider) — share one
    # thread, for as long as this Mac process keeps running. In debug
    # mode, Werkzeug's auto-reloader actually runs this file in TWO
    # processes (a watcher and a worker) — only the real worker (which
    # has WERKZEUG_RUN_MAIN set) should start the thread, or a debug run
    # would end up with two schedulers ticking at once.
    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        fill_hour = load_rules().get("scheduler", {}).get("fill_hour_sydney", 8)
        scheduler.start_scheduler_thread(
            portfolio, fill_hour=fill_hour,
            run_overnight_analysis=_run_overnight_analysis)

    app.run(debug=debug,
            host="127.0.0.1" if debug else "0.0.0.0",
            port=5001)
