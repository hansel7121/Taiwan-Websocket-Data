import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
import csv
import os
import signal
import threading
import time
import traceback
from datetime import datetime

import clr
assembly_path = r"C:\Users\user\OneDrive\Desktop\websocket\Taiwan-Websocket-Data\QuoteComExamplePy"
sys.path.append(assembly_path)
clr.AddReference("Package")
clr.AddReference("PushClient")
clr.AddReference("QuoteCom")
from Intelligence import QuoteCom, COM_STATUS, DT

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root, for kgi_config
from kgi_config import TOKEN, SID, USER_ID, PASSWORD

# ── What this measures ───────────────────────────────────────────────────────
# The open question: does this account really only get truly LIVE (push)
# updates for ~25 codes at a time (Qnum), with everything else either dead or
# silently rotated in/out by the server, or can far more than 25 codes be
# genuinely concurrently live?
#
# Why "eventually every subscribed code got >=1 update" (seen in old
# warrant-liveprices.py FULL_BATCH runs) does NOT settle this: that's
# consistent with BOTH "no cap" and "a real 25-at-a-time cap where the
# server silently rotates which 25 are active, invisible to the client,
# and 35+ minutes was enough time to cycle through everyone once." Both
# produce the same "100% coverage eventually" result.
#
# What DOES distinguish them: how many DISTINCT codes show real activity
# within a SHORT time window. If it's ever clearly more than ~25 within a
# tight window (a handful of seconds), that's real evidence against a hard
# concurrent cap. If it's consistently capped around 25 no matter how long
# you watch, that supports the rotating-cap theory.
#
# Method: bulk-subscribe to EVERY resolved warrant code at once (same as
# FULL_BATCH) to maximize how many codes COULD show activity, then for every
# DEPTH/MATCH message received, log (wall-clock time, code, type). A
# background thread recomputes, every few seconds, how many DISTINCT codes
# appeared in the last 5s / 15s / 30s / 60s, and tracks the running max for
# each window size across the whole session — that running max IS the
# answer to "what's the real concurrency ceiling."
#
# Run with: py -u to_test/test_subscription_concurrency.py
# (the -u matters -- without it, stdout buffers and looks like a hang)
# Let it run as long as possible during market hours, then Ctrl+C. Results
# are both logged live and written to data/subscription_concurrency_<date>.csv
# for offline re-analysis with any window size you want afterward.

UNDERLYING_STOCK = "2330"   # TSMC
WINDOW_SIZES_S = [5, 15, 30, 60]
SUMMARY_INTERVAL_S = 10

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # project root
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
TODAY = datetime.now().strftime("%Y%m%d")
LOG_PATH = os.path.join(DATA_DIR, f"subscription_concurrency_{TODAY}.csv")

log_lock = threading.Lock()
with open(LOG_PATH, "w", newline="", encoding="utf-8") as f:
    csv.writer(f).writerow(["timestamp", "code", "msg_type"])


def log_row(code, msg_type):
    now = time.time()
    with log_lock:
        with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([datetime.fromtimestamp(now).isoformat(timespec="milliseconds"), code, msg_type])
    return now


def log_debug(msg):
    line = f"{datetime.now().isoformat(timespec='milliseconds')} {msg}"
    print(line, flush=True)


# ── In-memory event log for the rolling-window analysis: list of (epoch, code) ─
events_lock = threading.Lock()
events = []   # (epoch_time, code) for every depth/match message, any code
running_max = {w: 0 for w in WINDOW_SIZES_S}


def record_event(code):
    now = time.time()
    with events_lock:
        events.append((now, code))


def summary_loop(stop_event):
    while not stop_event.wait(SUMMARY_INTERVAL_S):
        now = time.time()
        with events_lock:
            snapshot = list(events)
        parts = []
        for w in WINDOW_SIZES_S:
            cutoff = now - w
            distinct = len({code for t, code in snapshot if t >= cutoff})
            if distinct > running_max[w]:
                running_max[w] = distinct
            parts.append(f"{w}s:{distinct}(max={running_max[w]})")
        log_debug(f"[CONCURRENCY] distinct codes in last window -> {', '.join(parts)} "
                  f"| total events so far: {len(snapshot)}")


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


quoteCom = None
login_ready = threading.Event()
stop_event = threading.Event()
all_codes = []


def on_status(sender, status, msg):
    try:
        log_debug(f"[STATUS] {status}")
        if status in (COM_STATUS.LOGIN_READY, COM_STATUS.LOGIN_FAIL):
            login_ready.set()
    except Exception:
        log_debug("[STATUS] callback error:\n" + traceback.format_exc())


def on_message(sender, pkg):
    # Same defensive wrapping as every other callback in this project --
    # an unhandled exception here has previously segfaulted the process
    # (see test.py's AccessViolationException history).
    try:
        name = dt_name(int(pkg.DT))
        if name in ("QUOTE_STOCK_DEPTH1", "QUOTE_STOCK_DEPTH2"):
            code = str(pkg.StockNo).strip()
            record_event(code)
            log_row(code, "depth")
        elif name in ("QUOTE_STOCK_MATCH1", "QUOTE_STOCK_MATCH2"):
            code = str(pkg.StockNo).strip()
            record_event(code)
            log_row(code, "match")
    except Exception:
        log_debug("[MSG] callback error:\n" + traceback.format_exc())


def setup_and_run():
    global quoteCom, all_codes

    quoteCom = QuoteCom("", 443, SID, TOKEN)
    quoteCom.OnGetStatus += on_status
    quoteCom.OnRcvMessage += on_message

    log_debug("Connecting...")
    quoteCom.Connect2Quote("quoteapi.kgi.com.tw", 443, USER_ID, PASSWORD, ' ', "")

    if not login_ready.wait(timeout=20):
        log_debug("SETUP FAILED: login timeout")
        return
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
        return

    joined = "|".join(all_codes)
    try:
        s1 = quoteCom.SubQuotesMatch(joined)
        s2 = quoteCom.SubQuotesDepth(joined)
        log_debug(f"Subscribed ALL {len(all_codes)} codes at once (match={s1}, depth={s2})")
    except Exception:
        log_debug("Bulk subscribe failed:\n" + traceback.format_exc())
        return

    log_debug(f"SETUP done. Watching for concurrency across window sizes {WINDOW_SIZES_S}s. "
              f"Logging every event to {LOG_PATH}. Ctrl+C to stop.")


def shutdown(reason):
    if stop_event.is_set():
        return
    stop_event.set()
    log_debug(f"Shutting down: {reason}")
    try:
        if quoteCom is not None and all_codes:
            joined = "|".join(all_codes)
            quoteCom.UnSubQuotesMatch(joined)
            quoteCom.UnSubQuotesDepth(joined)
    except Exception:
        log_debug("Unsubscribe failed:\n" + traceback.format_exc())
    try:
        if quoteCom is not None:
            quoteCom.Dispose()
    except Exception:
        log_debug("Dispose failed:\n" + traceback.format_exc())

    log_debug("=" * 70)
    log_debug("FINAL RESULT -- max distinct codes seen concurrently, per window size:")
    for w in WINDOW_SIZES_S:
        log_debug(f"  within any {w}s window: {running_max[w]} distinct codes")
    log_debug("If these numbers stay close to 25 no matter the window size, that "
              "supports a real ~25-at-a-time cap (possibly server-rotated). If they "
              "clearly exceed 25 (especially at the shorter window sizes), that's "
              "evidence against a hard concurrent cap.")
    log_debug("=" * 70)


def on_sigint(signum, frame):
    shutdown("user pressed Ctrl+C")


signal.signal(signal.SIGINT, on_sigint)

if __name__ == "__main__":
    threading.Thread(target=summary_loop, args=(stop_event,), daemon=True).start()
    setup_and_run()
    try:
        while not stop_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown("user pressed Ctrl+C")
