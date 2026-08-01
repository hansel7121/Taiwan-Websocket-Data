import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
import json
import os
import queue
import signal
import threading
import time
import traceback
import urllib.request
from datetime import datetime, time as dtime

import tkinter as tk
from tkinter import ttk, scrolledtext

import clr
assembly_path = r"C:\Users\user\OneDrive\Desktop\websocket\Taiwan-Websocket-Data\QuoteComExamplePy"
sys.path.append(assembly_path)
clr.AddReference("Package")
clr.AddReference("PushClient")
clr.AddReference("QuoteCom")
from Intelligence import QuoteCom, COM_STATUS, DT

from kgi_config import TOKEN, SID, USER_ID, PASSWORD

# ── What this script does ───────────────────────────────────────────────────
# Same architecture as warrant_orderbook_collector.py, adapted for TSMC (2330)
# stock OPTIONS (comid "CDO" on TAIFEX) instead of warrants. See that file's
# header comment for the full failsafe/supervisor rationale — unchanged here.
#
# ONE real simplification vs the warrant version: TAIFEX's own public site
# (mis.taifex.com.tw/futures) turns out to expose a plain, anonymous,
# no-login JSON REST API that reports REAL observed volume/bid/ask for every
# CDO contract directly (confirmed live 2026-08-01). Warrants had no such
# shortcut — KGI's warrant master data has no volume field, forcing a slow
# ~3-minute live poll-and-measure warmup to rank codes. Options don't need
# that: query TAIFEX's REST API once at startup, rank by real CTotalVolume,
# lock in the top TOP_N immediately. Much faster cold start.
#
# UNVERIFIED (no live market to test against off-hours): which DT message
# type an actual option tick arrives as via KGI's push. This assumes it
# reuses QUOTE_STOCK_MATCH1/2 / QUOTE_STOCK_DEPTH1/2 (same as stocks/
# warrants — confirmed via reflection that the SAME SubQuotesMatch/
# SubQuotesDepth calls accept option symbols and return success), but also
# logs the full field dump of any OTHER DT type seen for a locked symbol, so
# a wrong assumption is immediately visible in the debug log instead of
# silently dropping ticks. Check for "[UNRECOGNIZED DT ...]" lines in
# options_orderbook_debug.log after the first live session.
#
# TAIFEX day-session hours for stock options are 08:45-13:45 (NOT the same
# as TWSE's 09:00-13:30 used for stocks/warrants). Individual stock options
# do not appear to have a night/after-hours session — that is currently
# limited to individual stock FUTURES for a few underlyings (TSMC included),
# not stock OPTIONS — so this script only covers the day session.

UNDERLYING_COMID = "CDO"   # TSMC (2330) stock options on TAIFEX
TOP_N = 25

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TODAY = datetime.now().strftime("%Y%m%d")

STATE_PATH = os.path.join(SCRIPT_DIR, f"options_state_{TODAY}.json")
HEARTBEAT_PATH = os.path.join(SCRIPT_DIR, "options_heartbeat.txt")
DONE_MARKER_PATH = os.path.join(SCRIPT_DIR, f"options_done_{TODAY}.marker")
DEBUG_LOG_PATH = os.path.join(SCRIPT_DIR, "options_orderbook_debug.log")

DEPTH_CSV_PATH = os.path.join(SCRIPT_DIR, f"options_depth_{TODAY}.csv")
TRADES_CSV_PATH = os.path.join(SCRIPT_DIR, f"options_trades_{TODAY}.csv")

MARKET_OPEN_TIME = dtime(8, 45)
MARKET_CLOSE_TIME = dtime(13, 45)
# Same reasoning as the warrant collector: total silence from every one of
# the locked codes for this long during market hours means the connection
# is almost certainly dead, not that the market is genuinely quiet.
STALE_THRESHOLD_S = 300

HEARTBEAT_INTERVAL_S = 15

TAIFEX_BASE = "https://mis.taifex.com.tw/futures/api"
_TAIFEX_HEADERS = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}


def log_debug(msg):
    line = f"{datetime.now().isoformat(timespec='milliseconds')} {msg}"
    try:
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line, flush=True)


def is_market_hours(now=None):
    now = now or datetime.now()
    return MARKET_OPEN_TIME <= now.time() <= MARKET_CLOSE_TIME


def write_done_marker(reason):
    try:
        with open(DONE_MARKER_PATH, "w", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} {reason}\n")
    except Exception:
        pass
    log_debug(f"[DONE] {reason} — wrote marker, supervisor should not restart")


def touch_heartbeat():
    try:
        with open(HEARTBEAT_PATH, "w", encoding="utf-8") as f:
            f.write(datetime.now().isoformat())
    except Exception:
        pass


# ── DT enum -> name (same pattern as warrant-liveprices.py) ────────────────
DT_NAMES = {}
for _name in dir(DT):
    if _name.isupper():
        try:
            DT_NAMES[int(getattr(DT, _name))] = _name
        except Exception:
            pass


def dt_name(value):
    try:
        return DT_NAMES.get(int(value), f"UNKNOWN({value})")
    except Exception:
        return f"UNPARSEABLE({value!r})"


def fmt_time(raw_match_time):
    raw_t = str(raw_match_time).zfill(9)
    return f"{raw_t[0:2]}:{raw_t[2:4]}:{raw_t[4:6]}"


# ── TAIFEX public REST helpers (no auth needed — confirmed 2026-08-01) ──────
def taifex_post(action, body):
    req = urllib.request.Request(
        f"{TAIFEX_BASE}/{action}",
        data=json.dumps(body).encode("utf-8"),
        headers=_TAIFEX_HEADERS,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def taifex_get_months():
    data = taifex_post("getCmdyMonthDDLItemByKind", {"CID": UNDERLYING_COMID, "MarketType": "0"})
    items = data.get("RtData", {}).get("Items", []) if data.get("RtCode") == "0" else []
    return [it["item"] for it in items if it["item"] and it["item"] != "現貨"]


def taifex_get_quotes(month):
    data = taifex_post("getQuoteListOption",
                        {"CID": UNDERLYING_COMID, "MarketType": "0", "ExpireMonth": month})
    if data.get("RtCode") != "0":
        return []
    return data.get("RtData", {}).get("QuoteList", []) or []


# ── Cross-thread plumbing ───────────────────────────────────────────────────
gui_queue = queue.Queue()
last_message_at = time.time()
last_message_lock = threading.Lock()


def mark_message_received():
    global last_message_at
    with last_message_lock:
        last_message_at = time.time()


def seconds_since_last_message():
    with last_message_lock:
        return time.time() - last_message_at


# ── CSV writers: opened once, appended+flushed on every row. Header written
# only if the file doesn't already exist (so a restart mid-day resumes the
# same file instead of duplicating a header partway through).
_depth_lock = threading.Lock()
_trades_lock = threading.Lock()


def _ensure_header(path, header, lock):
    with lock:
        is_new = not os.path.exists(path) or os.path.getsize(path) == 0
        if is_new:
            with open(path, "a", encoding="utf-8", newline="") as f:
                f.write(header + "\n")


_ensure_header(
    DEPTH_CSV_PATH,
    "time,code,Bid_1_Price,Bid_1_Qty,Bid_2_Price,Bid_2_Qty,Bid_3_Price,Bid_3_Qty,"
    "Bid_4_Price,Bid_4_Qty,Bid_5_Price,Bid_5_Qty,Ask_1_Price,Ask_1_Qty,Ask_2_Price,"
    "Ask_2_Qty,Ask_3_Price,Ask_3_Qty,Ask_4_Price,Ask_4_Qty,Ask_5_Price,Ask_5_Qty",
    _depth_lock,
)
_ensure_header(TRADES_CSV_PATH, "time,code,price,qty", _trades_lock)


def write_depth_row(t_fmt, code, bids, asks):
    fields = [t_fmt, code]
    for price, qty in bids:
        fields += [price, qty]
    for price, qty in asks:
        fields += [price, qty]
    line = ",".join(str(x) for x in fields)
    with _depth_lock:
        try:
            with open(DEPTH_CSV_PATH, "a", encoding="utf-8", newline="") as f:
                f.write(line + "\n")
        except Exception:
            log_debug("write_depth_row failed:\n" + traceback.format_exc())


def write_trade_row(t_fmt, code, price, qty):
    line = f"{t_fmt},{code},{price},{qty}"
    with _trades_lock:
        try:
            with open(TRADES_CSV_PATH, "a", encoding="utf-8", newline="") as f:
                f.write(line + "\n")
        except Exception:
            log_debug("write_trade_row failed:\n" + traceback.format_exc())


def choose_top_n_by_taifex_volume():
    """Query TAIFEX's public REST API once for real observed volume across
    every CDO contract in every expiry month, and pick the TOP_N by volume.
    Unlike warrants (no volume field available anywhere), this needs no live
    warmup at all — it's a couple of quick, free, anonymous HTTP calls."""
    months = taifex_get_months()
    log_debug(f"[DISCOVER] TAIFEX expiry months for {UNDERLYING_COMID}: {months}")

    all_candidates = []
    for month in months:
        try:
            quotes = taifex_get_quotes(month)
        except Exception:
            log_debug(f"[DISCOVER] taifex_get_quotes({month}) failed:\n" + traceback.format_exc())
            continue
        all_candidates.extend(quotes)
        time.sleep(0.2)   # be polite to a public anonymous endpoint

    log_debug(f"[DISCOVER] {len(all_candidates)} total CDO contracts across all months")
    if not all_candidates:
        raise RuntimeError("No CDO contracts resolved from TAIFEX REST API at all")

    def volume_of(q):
        try:
            return int(q.get("CTotalVolume") or 0)
        except ValueError:
            return 0

    def has_quote(q):
        return bool(q.get("CBidPrice1")) or bool(q.get("CAskPrice1"))

    # Sort by (real volume desc, has a live quote desc, original discovery
    # order) so degenerate/off-hours runs still produce a deterministic,
    # reasonable pick instead of crashing — same spirit as the warrant
    # collector's fallback, just expressed as one sort instead of tiers.
    ranked = sorted(enumerate(all_candidates),
                     key=lambda iq: (-volume_of(iq[1]), -int(has_quote(iq[1])), iq[0]))
    top = [q for _, q in ranked[:TOP_N]]

    if volume_of(top[0]) == 0:
        log_debug(f"[DISCOVER] WARNING: no CDO contract shows any real volume "
                  f"(market likely closed) — falling back to a volume-blind "
                  f"pick. This is NOT a liquidity ranking; rerun during "
                  f"active market hours for a real one.")

    for i, q in enumerate(top):
        log_debug(f"[DISCOVER] rank {i+1}: {q['SymbolID']} strike={q.get('StrikePrice')} "
                  f"CP={q.get('CP')} volume={volume_of(q)}")

    kgi_codes = [q["SymbolID"].split("-")[0] for q in top]
    return kgi_codes


quoteCom = None
login_ready = threading.Event()
locked_codes = []
stop_event = threading.Event()
shutdown_lock = threading.Lock()


def onQuoteGetStatus(sender, status, msg):
    try:
        log_debug(f"[STATUS] {status}")
        gui_queue.put({"type": "status", "text": f"Status: {status}"})
        if status == COM_STATUS.LOGIN_FAIL:
            log_debug("[STATUS] LOGIN FAILED")
    except Exception:
        log_debug("[STATUS] callback error:\n" + traceback.format_exc())


def onQuoteGetStatus_login_hook(sender, status, msg):
    try:
        if status in (COM_STATUS.LOGIN_READY, COM_STATUS.LOGIN_FAIL):
            login_ready.set()
    except Exception:
        log_debug("[STATUS hook] error:\n" + traceback.format_exc())


def onQuoteRcvMessage(sender, pkg):
    # Every branch is wrapped in the outer try/except: an unhandled Python
    # exception escaping a .NET-invoked callback has previously corrupted
    # the pythonnet/GIL state badly enough to segfault the whole process
    # (see test.py's AccessViolationException history) — caught exceptions
    # here just get logged, never allowed to propagate back into .NET.
    try:
        mark_message_received()
        dtv = int(pkg.DT)
        name = dt_name(dtv)

        if name in ("QUOTE_STOCK_DEPTH1", "QUOTE_STOCK_DEPTH2"):
            code = str(pkg.StockNo).strip()
            if code not in locked_codes:
                return
            bids = [(str(pkg.BUY_DEPTH[i].PRICE), str(pkg.BUY_DEPTH[i].QUANTITY)) for i in range(5)]
            asks = [(str(pkg.SELL_DEPTH[i].PRICE), str(pkg.SELL_DEPTH[i].QUANTITY)) for i in range(5)]
            t_fmt = fmt_time(pkg.Match_Time)
            write_depth_row(t_fmt, code, bids, asks)
            gui_queue.put({"type": "depth", "code": code, "bids": bids, "asks": asks})

        elif name in ("QUOTE_STOCK_MATCH1", "QUOTE_STOCK_MATCH2"):
            code = str(pkg.StockNo).strip()
            if code not in locked_codes:
                return
            price = str(pkg.Match_Price)
            qty = str(pkg.Match_Qty)
            t_fmt = fmt_time(pkg.Match_Time)
            write_trade_row(t_fmt, code, price, qty)
            gui_queue.put({"type": "trade", "code": code, "price": price,
                            "qty": qty, "time": t_fmt})

        elif name == "LOGIN":
            qnum = getattr(pkg, "Qnum", None)
            log_debug(f"[LOGIN MSG] Qnum (registrable quote codes) = {qnum}")
            gui_queue.put({"type": "qnum", "qnum": qnum})

        else:
            # Diagnostic only: this project has never confirmed which DT an
            # option tick actually arrives as. If a locked symbol's data is
            # coming through under a DT name we don't recognize above, dump
            # everything about it here so it's visible in the debug log
            # instead of silently missing from the CSVs.
            try:
                stockno = str(getattr(pkg, "StockNo", "")).strip()
            except Exception:
                stockno = ""
            if stockno in locked_codes:
                try:
                    fields = {f.Name: str(f.GetValue(pkg)) for f in clr.GetClrType(pkg.GetType()).GetFields()}
                except Exception:
                    fields = {}
                log_debug(f"[UNRECOGNIZED DT] {dtv} ({name}) for locked symbol "
                          f"{stockno}: fields={fields}")

    except Exception:
        log_debug("[MSG] callback error:\n" + traceback.format_exc())


def save_state(codes):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"date": TODAY, "locked_codes": codes,
                    "locked_at": datetime.now().isoformat()}, f, indent=2)


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            log_debug("load_state failed:\n" + traceback.format_exc())
    return None


def subscribe_locked(codes):
    joined = "|".join(codes)
    try:
        s1 = quoteCom.SubQuotesMatch(joined)
        s2 = quoteCom.SubQuotesDepth(joined)
        log_debug(f"Subscribed {len(codes)} locked codes (match={s1}, depth={s2})")
    except Exception:
        log_debug("subscribe_locked failed:\n" + traceback.format_exc())


def unsubscribe_locked(codes):
    if not codes:
        return
    joined = "|".join(codes)
    try:
        quoteCom.UnSubQuotesMatch(joined)
        quoteCom.UnSubQuotesDepth(joined)
    except Exception:
        log_debug("unsubscribe_locked failed:\n" + traceback.format_exc())


def staleness_watchdog():
    while not stop_event.is_set():
        time.sleep(10)
        if not locked_codes:
            continue  # still in setup, nothing to be stale yet
        if is_market_hours() and seconds_since_last_message() > STALE_THRESHOLD_S:
            log_debug(f"[WATCHDOG] no messages from any of {len(locked_codes)} "
                      f"locked codes in {STALE_THRESHOLD_S}s during market "
                      f"hours — treating connection as dead, exiting for "
                      f"supervisor restart.")
            gui_queue.put({"type": "status", "text": "Connection appears dead — restarting..."})
            os._exit(1)   # hard exit: don't rely on any possibly-wedged cleanup path


def market_close_watchdog():
    while not stop_event.is_set():
        time.sleep(10)
        if datetime.now().time() > MARKET_CLOSE_TIME:
            log_debug("[WATCHDOG] market close time reached, shutting down gracefully")
            trigger_shutdown("market closed")
            return


def heartbeat_loop():
    while not stop_event.is_set():
        touch_heartbeat()
        time.sleep(HEARTBEAT_INTERVAL_S)


def setup_and_run():
    global quoteCom, locked_codes

    log_debug("=" * 70)
    log_debug(f"SETUP: starting (date={TODAY})")
    log_debug("=" * 70)

    quoteCom = QuoteCom("", 443, SID, TOKEN)
    quoteCom.OnGetStatus += onQuoteGetStatus
    quoteCom.OnRcvMessage += onQuoteRcvMessage

    log_debug("Connecting...")
    quoteCom.Connect2Quote("quoteapi.kgi.com.tw", 443, USER_ID, PASSWORD, ' ', "")

    if not login_ready.wait(timeout=20):
        log_debug("SETUP FAILED: login timeout")
        gui_queue.put({"type": "status", "text": "SETUP FAILED: login timeout"})
        os._exit(1)
    time.sleep(2)

    try:
        quoteCom.LoadTaifexProductXML()
    except Exception:
        log_debug("LoadTaifexProductXML failed:\n" + traceback.format_exc())
    time.sleep(5)

    state = load_state()
    if state and state.get("locked_codes"):
        locked_codes[:] = state["locked_codes"]
        log_debug(f"[RESUME] found existing state for {TODAY}, resuming with "
                  f"already-locked {len(locked_codes)} codes (no re-discovery)")
        gui_queue.put({"type": "locked", "codes": list(locked_codes)})
    else:
        gui_queue.put({"type": "status", "text": "Discovering liquid CDO contracts via TAIFEX..."})
        try:
            chosen = choose_top_n_by_taifex_volume()
        except Exception:
            log_debug("SETUP FAILED: choose_top_n_by_taifex_volume failed:\n" + traceback.format_exc())
            os._exit(1)
        if stop_event.is_set():
            return
        locked_codes[:] = chosen
        save_state(chosen)
        log_debug(f"[LOCKED] today's {TOP_N}: {chosen}")
        gui_queue.put({"type": "locked", "codes": list(chosen)})

    subscribe_locked(locked_codes)
    mark_message_received()   # start the staleness clock fresh from lock-in
    gui_queue.put({"type": "status",
                    "text": f"Recording {len(locked_codes)} codes -> "
                            f"{os.path.basename(DEPTH_CSV_PATH)} / "
                            f"{os.path.basename(TRADES_CSV_PATH)}"})
    log_debug("SETUP: done. Recording live.")

    threading.Thread(target=staleness_watchdog, daemon=True).start()
    threading.Thread(target=market_close_watchdog, daemon=True).start()


def trigger_shutdown(reason):
    with shutdown_lock:
        if stop_event.is_set():
            return
        stop_event.set()
    log_debug(f"Shutting down: {reason}")
    # setup_and_run runs on its own thread and may still be mid-discovery
    # (HTTP calls to TAIFEX, or a KGI call) — join it first so nothing is
    # still calling into quoteCom when Dispose() runs below. Concurrent
    # Dispose()+in-flight-call is exactly the kind of pythonnet native-
    # interop hazard that has already caused a hard crash elsewhere in this
    # project (see test.py's AccessViolationException). In the common case
    # setup_and_run has long since finished, so this join is a no-op.
    try:
        setup_thread.join(timeout=2)
    except Exception:
        pass
    try:
        if quoteCom is not None and locked_codes:
            unsubscribe_locked(locked_codes)
    except Exception:
        log_debug("Unsubscribe on shutdown failed:\n" + traceback.format_exc())
    try:
        if quoteCom is not None:
            quoteCom.OnRcvMessage -= onQuoteRcvMessage
            quoteCom.OnGetStatus -= onQuoteGetStatus
            quoteCom.OnGetStatus -= onQuoteGetStatus_login_hook
    except Exception:
        pass
    try:
        if quoteCom is not None:
            quoteCom.Dispose()
    except Exception:
        log_debug("Dispose on shutdown failed:\n" + traceback.format_exc())

    write_done_marker(reason)
    try:
        root.after(0, root.destroy)
    except Exception:
        os._exit(0)


# ── Tkinter GUI: full 5-level table, one row per locked code ────────────────
root = tk.Tk()
root.title(f"TSMC ({UNDERLYING_COMID}) Top-{TOP_N} Options Orderbook Recorder")
root.geometry("1500x700")

top = ttk.Frame(root, padding=8)
top.pack(fill="x")
status_var = tk.StringVar(value="Starting...")
qnum_var = tk.StringVar(value="Qnum: (unknown yet)")
ttk.Label(top, textvariable=status_var, font=("Segoe UI", 10, "bold")).pack(anchor="w")
ttk.Label(top, textvariable=qnum_var).pack(anchor="w")

COLUMNS = ("code", "bid5", "bid4", "bid3", "bid2", "bid1",
           "ask1", "ask2", "ask3", "ask4", "ask5", "last", "last_time")
HEADINGS = {"code": "Code", "bid5": "Bid 5", "bid4": "Bid 4", "bid3": "Bid 3",
            "bid2": "Bid 2", "bid1": "Bid 1 (best)", "ask1": "Ask 1 (best)",
            "ask2": "Ask 2", "ask3": "Ask 3", "ask4": "Ask 4", "ask5": "Ask 5",
            "last": "Last Trade", "last_time": "Trade Time"}

tree_frame = ttk.Frame(root)
tree_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
tree = ttk.Treeview(tree_frame, columns=COLUMNS, show="headings", height=TOP_N)
for col in COLUMNS:
    tree.heading(col, text=HEADINGS[col])
    tree.column(col, width=105 if col != "code" else 110, anchor="center")

vscroll = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
hscroll = ttk.Scrollbar(tree_frame, orient="horizontal", command=tree.xview)
tree.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)
tree.grid(row=0, column=0, sticky="nsew")
vscroll.grid(row=0, column=1, sticky="ns")
hscroll.grid(row=1, column=0, sticky="ew")
tree_frame.rowconfigure(0, weight=1)
tree_frame.columnconfigure(0, weight=1)

log_frame = ttk.LabelFrame(root, text="Trade log", padding=4)
log_frame.pack(fill="both", expand=False, padx=8, pady=(0, 8))
log_widget = scrolledtext.ScrolledText(log_frame, height=8, state="disabled", wrap="word")
log_widget.pack(fill="both", expand=True)
_log_line_count = 0
MAX_LOG_LINES_IN_GUI = 500


def append_log_line(text):
    global _log_line_count
    log_widget.configure(state="normal")
    log_widget.insert("end", text + "\n")
    _log_line_count += 1
    if _log_line_count > MAX_LOG_LINES_IN_GUI:
        log_widget.delete("1.0", "2.0")
        _log_line_count -= 1
    log_widget.see("end")
    log_widget.configure(state="disabled")


def cell(price, qty):
    return f"{price} ({qty})"


def drain_queue():
    try:
        while True:
            event = gui_queue.get_nowait()
            etype = event.get("type")

            if etype == "locked":
                codes = event["codes"]
                for code in codes:
                    if not tree.exists(code):
                        tree.insert("", "end", iid=code,
                                    values=(code, "-", "-", "-", "-", "-",
                                            "-", "-", "-", "-", "-", "-", "-"))
                status_var.set(f"Locked in top {len(codes)} codes for today. Recording...")

            elif etype == "depth":
                code = event["code"]
                bids = event["bids"]   # index 0 = best bid ... 4 = 5th level
                asks = event["asks"]   # index 0 = best ask ... 4 = 5th level
                if tree.exists(code):
                    tree.set(code, "bid1", cell(*bids[0]))
                    tree.set(code, "bid2", cell(*bids[1]))
                    tree.set(code, "bid3", cell(*bids[2]))
                    tree.set(code, "bid4", cell(*bids[3]))
                    tree.set(code, "bid5", cell(*bids[4]))
                    tree.set(code, "ask1", cell(*asks[0]))
                    tree.set(code, "ask2", cell(*asks[1]))
                    tree.set(code, "ask3", cell(*asks[2]))
                    tree.set(code, "ask4", cell(*asks[3]))
                    tree.set(code, "ask5", cell(*asks[4]))

            elif etype == "trade":
                code = event["code"]
                if tree.exists(code):
                    tree.set(code, "last", event["price"])
                    tree.set(code, "last_time", event["time"])
                append_log_line(f"{code} traded {event['qty']} @ {event['price']} at {event['time']}")

            elif etype == "qnum":
                qnum_var.set(f"Qnum (account subscription-slot limit): {event['qnum']}")

            elif etype == "status":
                status_var.set(event["text"])
                append_log_line(f"[STATUS] {event['text']}")

    except queue.Empty:
        pass
    root.after(100, drain_queue)


def on_close():
    trigger_shutdown("user closed window")


def on_sigint(signum, frame):
    trigger_shutdown("user pressed Ctrl+C")


root.protocol("WM_DELETE_WINDOW", on_close)
signal.signal(signal.SIGINT, on_sigint)
# SIGBREAK (Windows-only) is what a supervisor process sends via
# CTRL_BREAK_EVENT to ask this process to shut down gracefully rather than
# being force-killed outright — same graceful path as Ctrl+C/window-close,
# so a supervisor-initiated stop still writes the "done" marker correctly.
if hasattr(signal, "SIGBREAK"):
    signal.signal(signal.SIGBREAK, on_sigint)


def _install_login_hook():
    for _ in range(200):
        if quoteCom is not None:
            quoteCom.OnGetStatus += onQuoteGetStatus_login_hook
            return
        time.sleep(0.05)


threading.Thread(target=_install_login_hook, daemon=True).start()
setup_thread = threading.Thread(target=setup_and_run, daemon=True)
setup_thread.start()
threading.Thread(target=heartbeat_loop, daemon=True).start()

root.after(100, drain_queue)
log_debug(f"Debug log: {DEBUG_LOG_PATH}")
root.mainloop()

# If we get here via root.destroy() rather than a hard os._exit, make sure
# the process actually terminates (Tk can leave background threads alive).
os._exit(0 if os.path.exists(DONE_MARKER_PATH) else 1)
