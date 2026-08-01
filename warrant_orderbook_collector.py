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
# 1. WARMUP: poll every 2330 (TSMC) warrant code via RetriveLastPriceStock for
#    WARMUP_DURATION_S, tracking cumulative traded volume per code (same
#    signal HYBRID uses: Total_Qty/TotalMatchQty). At the end, rank all codes
#    by (volume observed / time observed) and lock in the top TOP_N as
#    "today's 25 most liquid". This is a one-time decision — KGI's warrant
#    master data (GetWarrantTargetStock) has no static volume/liquidity
#    field (confirmed by reflecting its properties: only contract terms like
#    StrikePrice/ExpiredDate/IssuingBalVol are exposed, no traded-volume
#    field), so there is no way to know which 25 will be liquid before
#    watching them actually trade.
# 2. LOCK-IN: once chosen, the 25 codes never change for the rest of the day
#    (no rotation, per explicit instruction) — bulk push-subscribe to
#    SubQuotesMatch + SubQuotesDepth for exactly those 25, which fits the
#    Qnum=25 cap with zero slack, by design.
# 3. RECORD: every DEPTH message (5 bid + 5 ask levels) and every MATCH
#    message (trade price/qty/time) for the 25 is appended IMMEDIATELY to
#    today's CSV files (flushed on every write) — not buffered in memory
#    until close. This means a crash never loses data older than the last
#    write, and "converting to CSV at the end" doesn't need to be a separate
#    step: the day's file is already complete and valid at every point in
#    time, it just gets a final summary line logged when the day ends.
# 4. FAILSAFE: this process is meant to be run under
#    warrant_orderbook_supervisor.py, not directly. That supervisor is a
#    separate, pythonnet-free process specifically because pythonnet has
#    already caused one confirmed hard native crash on this project
#    (AccessViolationException inside PyGILState_Ensure during
#    QuoteCom.Finalize(), seen in test.py) — that class of crash kills the
#    whole process and cannot be caught by any Python try/except, so the
#    only real mitigation is an external process that notices this one died
#    and restarts it. This script cooperates with that supervisor by:
#      - writing a per-day state file (locked codes) so a restart doesn't
#        repeat the warmup or pick a different 25 mid-day
#      - touching a heartbeat file regularly so the supervisor can detect a
#        hang (process alive but stuck) as well as an outright crash
#      - writing a distinct "done" marker on any INTENTIONAL stop (market
#        closed, or the user closed the window / Ctrl+C'd) so the
#        supervisor knows not to restart — anything else (no marker present
#        when the process exits) is treated as unexpected and triggers a
#        restart.
#    This script does still keep its own internal reconnect-oriented
#    defenses (staleness self-check, try/except around every callback) as a
#    first line of defense — the supervisor is the backstop for when those
#    aren't enough, not a replacement for them.

UNDERLYING_STOCK = "2330"   # TSMC
TOP_N = 25

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
TODAY = datetime.now().strftime("%Y%m%d")

STATE_PATH = os.path.join(DATA_DIR, f"orderbook_state_{TODAY}.json")
HEARTBEAT_PATH = os.path.join(DATA_DIR, "orderbook_heartbeat.txt")
DONE_MARKER_PATH = os.path.join(DATA_DIR, f"orderbook_done_{TODAY}.marker")
DEBUG_LOG_PATH = os.path.join(DATA_DIR, "warrant_orderbook_debug.log")

DEPTH_CSV_PATH = os.path.join(DATA_DIR, f"warrant_depth_{TODAY}.csv")
TRADES_CSV_PATH = os.path.join(DATA_DIR, f"warrant_trades_{TODAY}.csv")

WARMUP_POLL_DELAY_S = 0.035   # same rate as HYBRID/POLLING: ~29 req/s
# 3x a measured single full-sweep time (~50-53s over ~1100 codes) so the
# ranking reflects multiple sweeps' worth of volume, not just whichever
# codes happened to be early in the first pass — a code polled twice within
# one sweep gets a noisy two-point rate; three sweeps' worth smooths that out.
WARMUP_DURATION_S = 180

MARKET_CLOSE_TIME = dtime(13, 30)
MARKET_OPEN_TIME = dtime(9, 0)
# If no depth/match message arrives from ANY of the 25 locked codes for this
# long while the market should be open, treat the connection as silently
# dead (no OnGetStatus disconnect event necessarily fires for every failure
# mode) and self-exit non-zero so the supervisor restarts the process. 25
# codes were chosen specifically for liquidity, so total silence across all
# of them for this long during trading hours is not normal market behavior.
STALE_THRESHOLD_S = 300

HEARTBEAT_INTERVAL_S = 15


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


def to_number(clr_decimal):
    # pythonnet's CLR Decimal doesn't support Python's int()/float() directly
    # (confirmed the hard way in HYBRID: int(pkg.Total_Qty) raises TypeError,
    # "not 'Decimal'") — route through str() first, like every numeric pkg
    # field elsewhere in this project already does.
    return float(str(clr_decimal))


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


# ── Warmup activity tracking: code -> {first_qty, first_t, last_qty, last_t} ─
activity_lock = threading.Lock()
activity = {}


def record_activity(code, cum_qty, now=None):
    now = now or time.time()
    with activity_lock:
        entry = activity.setdefault(code, {"first_qty": cum_qty, "first_t": now,
                                            "last_qty": cum_qty, "last_t": now})
        if cum_qty >= entry["last_qty"]:
            entry["last_qty"] = cum_qty
            entry["last_t"] = now
        # a decrease means a stale/out-of-order response; ignore rather than
        # let it corrupt the running total, same defensive stance as HYBRID


def rank_codes_by_activity(codes):
    with activity_lock:
        snapshot = dict(activity)
    scored = []
    for code in codes:
        e = snapshot.get(code)
        if e and e["last_t"] > e["first_t"]:
            rate = (e["last_qty"] - e["first_qty"]) / (e["last_t"] - e["first_t"])
        else:
            rate = 0.0
        scored.append((code, rate))
    scored.sort(key=lambda x: -x[1])
    return scored


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
        name = dt_name(int(pkg.DT))

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
            # Only fires for locked codes — nothing is push-subscribed during
            # warmup (that phase only issues RetriveLastPriceStock queries),
            # so a MATCH push for a non-locked code can't happen here.
            code = str(pkg.StockNo).strip()
            if code not in locked_codes:
                return
            price = str(pkg.Match_Price)
            qty = str(pkg.Match_Qty)
            t_fmt = fmt_time(pkg.Match_Time)
            write_trade_row(t_fmt, code, price, qty)
            gui_queue.put({"type": "trade", "code": code, "price": price,
                            "qty": qty, "time": t_fmt})

        elif name == "QUOTE_LAST_PRICE_STOCK":
            # Warmup-phase RetriveLastPriceStock responses
            code = str(pkg.StockNo).strip()
            try:
                record_activity(code, to_number(pkg.TotalMatchQty))
            except Exception:
                pass

        elif name == "LOGIN":
            qnum = getattr(pkg, "Qnum", None)
            log_debug(f"[LOGIN MSG] Qnum (registrable quote codes) = {qnum}")
            gui_queue.put({"type": "qnum", "qnum": qnum})

    except Exception:
        log_debug("[MSG] callback error:\n" + traceback.format_exc())


def warmup_poll_loop(all_codes, stop_flag):
    log_debug(f"[WARMUP] polling {len(all_codes)} codes for {WARMUP_DURATION_S}s "
              f"to rank by trading activity...")
    start = time.time()
    sweep = 0
    while time.time() - start < WARMUP_DURATION_S and not stop_flag.is_set():
        sweep += 1
        for code in all_codes:
            if stop_flag.is_set() or time.time() - start >= WARMUP_DURATION_S:
                break
            try:
                quoteCom.RetriveLastPriceStock(code)
            except Exception:
                log_debug(f"[WARMUP] RetriveLastPriceStock({code}) failed:\n"
                          + traceback.format_exc())
            time.sleep(WARMUP_POLL_DELAY_S)
        log_debug(f"[WARMUP] sweep #{sweep} complete, "
                  f"{time.time()-start:.0f}s/{WARMUP_DURATION_S}s elapsed")
        gui_queue.put({"type": "status",
                        "text": f"Warming up: sweep #{sweep} complete "
                                f"({time.time()-start:.0f}s/{WARMUP_DURATION_S}s)"})


def choose_top_n(all_codes):
    ranked = rank_codes_by_activity(all_codes)
    nonzero = [c for c, r in ranked if r > 0]
    if len(nonzero) < TOP_N:
        # Degenerate case: not enough real trading activity to differentiate
        # (e.g. off-hours, or a very quiet session). Fall back to the first
        # TOP_N resolved codes so the script still does something useful
        # rather than hang or crash — but this is NOT a real liquidity
        # ranking and gets logged loudly so it's never mistaken for one.
        log_debug(f"[WARMUP] only {len(nonzero)} codes showed any trading "
                  f"activity (<{TOP_N}) — falling back to first {TOP_N} "
                  f"resolved codes by list order. This is NOT a liquidity "
                  f"ranking; rerun during active market hours for a real one.")
        chosen = all_codes[:TOP_N]
    else:
        chosen = [c for c, r in ranked[:TOP_N]]
    for i, (code, rate) in enumerate(ranked[:TOP_N]):
        log_debug(f"[WARMUP] rank {i+1}: {code} rate={rate:.3f}/s")
    return chosen


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
            continue  # still in warmup, nothing to be stale yet
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
        quoteCom.RetriveProductTSE()
        quoteCom.RetriveProductOTC()
    except Exception:
        log_debug("RetriveProductTSE/OTC failed:\n" + traceback.format_exc())
    time.sleep(5)

    try:
        quoteCom.RetriveWarrantInfo()
        quoteCom.RetriveWarrantPrice()
    except Exception:
        log_debug("RetriveWarrantInfo/Price failed:\n" + traceback.format_exc())
    time.sleep(5)

    try:
        results = list(quoteCom.GetWarrantTargetStock(UNDERLYING_STOCK))
        all_codes = [str(w.WarrantID).strip() for w in results]
    except Exception:
        log_debug("GetWarrantTargetStock failed:\n" + traceback.format_exc())
        all_codes = []

    log_debug(f"Resolved {len(all_codes)} warrant codes for {UNDERLYING_STOCK}")
    if not all_codes:
        log_debug("SETUP FAILED: no warrant codes resolved")
        os._exit(1)

    state = load_state()
    if state and state.get("locked_codes"):
        locked_codes[:] = state["locked_codes"]
        log_debug(f"[RESUME] found existing state for {TODAY}, resuming with "
                  f"already-locked {len(locked_codes)} codes (no re-warmup)")
        gui_queue.put({"type": "locked", "codes": list(locked_codes)})
    else:
        gui_queue.put({"type": "warmup_start", "codes": list(all_codes)})
        warmup_poll_loop(all_codes, stop_event)
        if stop_event.is_set():
            return
        chosen = choose_top_n(all_codes)
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
    # setup_and_run (and the warmup polling loop inside it) runs on its own
    # thread and calls quoteCom.RetriveLastPriceStock in a tight loop during
    # warmup — join it first so it has actually stopped calling into
    # quoteCom before Dispose() runs below. Calling Dispose() concurrently
    # with an in-flight call on another thread is exactly the kind of
    # pythonnet native-interop hazard that has already caused a hard crash
    # elsewhere in this project (see test.py's AccessViolationException).
    # By this point setup_and_run has almost always already finished its
    # one-time setup and returned, so this join is a no-op in the common
    # case — it only actually waits during the narrow window of a
    # mid-warmup shutdown.
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
root.title(f"TSMC ({UNDERLYING_STOCK}) Top-{TOP_N} Warrant Orderbook Recorder")
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
    tree.column(col, width=105 if col != "code" else 80, anchor="center")

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

            if etype == "warmup_start":
                status_var.set(f"Warming up: ranking {len(event['codes'])} codes "
                                f"by trading activity ({WARMUP_DURATION_S}s)...")

            elif etype == "locked":
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
