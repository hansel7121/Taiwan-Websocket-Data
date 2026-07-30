import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
import os
import re
import time
import queue
import threading
import traceback
from datetime import datetime

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

# ── Config ────────────────────────────────────────────────────────────────
UNDERLYING_STOCK = "2330"   # TSMC

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEBUG_LOG_PATH = os.path.join(SCRIPT_DIR, "warrant_liveprices_debug.log")
MAX_LOG_LINES_IN_GUI = 500
COVERAGE_SNAPSHOT_INTERVAL_MS = 60_000  # log a coverage snapshot every 60s

# ── STRATEGY switch ──────────────────────────────────────────────────────────
# "FULL_BATCH" (default, active): subscribe every resolved warrant code in one
#   SubQuotesMatch/SubQuotesDepth call, all at once. Push-based; a code only
#   updates when a real trade/book change happens. Untested against the
#   account's real Qnum cap until market hours.
#
# "ROTATION" (backup #1): asymmetric event-driven rotation (RotationManager
#   below). Only ROTATION_SLOTS_DEFAULT codes are ever subscribed at once; the
#   moment one receives a book (Depth) update, it's swapped out for the next
#   not-yet-visited code and requeued at the back of the line. Turnover speed
#   is adaptive per code, not fixed-interval.
#   Verified offline (rotation_sim_test.py, not part of this file) against a
#   simulated 4h45m TWSE session with 1116 codes and a 5% chance per code of
#   NEVER ticking all session:
#     - WITH the ROTATION_TIMEOUT_S force-advance: all 1116/1116 codes got
#       visited at least once (21-22 visits each over the session).
#     - WITHOUT it: only 649/1116 (58%) ever got visited — "dead" codes that
#       never tick permanently occupy a slot, and this accumulates until the
#       whole rotation stalls. The timeout is load-bearing, not optional.
#   Unverifiable until market hours: whether the server enforces any cooldown
#   on rapid Sub/UnSub churn, and the real tick-arrival distribution (the
#   simulation's delay distribution is a guess, not measured data).
#
# "POLLING" (backup #2): round-robins RetriveLastPriceStock across every
#   warrant code, forever. RetriveLastPriceStock is a one-shot QUERY, not a
#   subscription (see its place under KGI's own "報價查詢" doc section,
#   separate from the registration section) — verified today to reflect real
#   intraday movement, not a stale/cached value, and its response includes
#   BUY_DEPTH/SELL_DEPTH (bid/ask) alongside LastMatchPrice. It very likely
#   does NOT consume a Qnum slot at all, so there's no 25-code ceiling — the
#   only constraint is raw request rate, which is unmeasured.
#   POLL_DELAY_BETWEEN_CALLS_S below is a deliberately conservative starting
#   guess, NOT a measured safe rate: at 1116 codes, a 5s full-sweep target
#   (which was floated as an option) implies ~223 requests/second sustained —
#   with zero documented rate limit, that is a big, untested ask to lead with.
#   The default here instead targets a ~35-45s full sweep (~25-30 req/s) and
#   logs real per-call round-trip latency, so tomorrow's numbers can justify
#   speeding this up rather than guessing 5s cold.
STRATEGY = "FULL_BATCH"   # one of: "FULL_BATCH", "ROTATION", "POLLING"

ROTATION_SLOTS_DEFAULT = 25       # overridden at runtime by the observed Qnum, if received
ROTATION_TIMEOUT_S = 30           # force-advance a code that never ticks within this long

POLL_DELAY_BETWEEN_CALLS_S = 0.035   # ~35ms -> ~29 req/s -> ~39s per full 1116-code sweep

# Numeric DT -> symbolic name, for readable debug logs (DT enum members are the
# all-caps class attributes; everything else on the class is inherited Enum/
# Object machinery like CompareTo/GetHashCode, so isupper() cleanly separates them).
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


# ── Debug log file (always written, independent of the GUI) ────────────────
_log_file_lock = threading.Lock()


def log_debug(msg):
    line = f"{datetime.now().isoformat(timespec='milliseconds')} {msg}"
    with _log_file_lock:
        try:
            with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass  # a logging fault must never break the app
    print(line, flush=True)


# ── Cross-thread event queue: QuoteCom callbacks (fired on .NET threads) push
# here; the Tkinter main thread drains it via root.after(). Tkinter widgets
# must only ever be touched from the main thread.
gui_queue = queue.Queue()

# code -> {"got_depth": bool, "got_match": bool, "last_update": epoch}
# The single most useful diagnostic here: if this plateaus at exactly Qnum
# codes covered, that is the smoking gun for the account-wide subscription cap.
coverage = {}
coverage_lock = threading.Lock()
all_codes = []  # populated once GetWarrantTargetStock returns


def mark_coverage(code, kind):
    with coverage_lock:
        entry = coverage.setdefault(code, {"got_depth": False, "got_match": False, "last_update": 0})
        entry[kind] = True
        entry["last_update"] = time.time()


def coverage_summary():
    with coverage_lock:
        total = len(all_codes)
        covered = sum(1 for c in all_codes if c in coverage)
        depth_covered = sum(1 for v in coverage.values() if v["got_depth"])
        match_covered = sum(1 for v in coverage.values() if v["got_match"])
    return total, covered, depth_covered, match_covered


# ── BACKUP PLAN #1 (inactive unless STRATEGY = "ROTATION"): asymmetric
# event-driven rotation. See the comment block near STRATEGY above for what
# was and wasn't verified before this was written.
#
# Swap requests (from onQuoteRcvMessage, which fires on a .NET callback thread)
# are handed off to a dedicated worker thread rather than calling
# Sub/UnSubQuotes* directly inside the callback. Everywhere else in this file,
# .NET-invoked callbacks only ever enqueue and never do real work themselves —
# the earlier testing.py/test.py crashes showed that letting a Python
# exception escape inside one of these callbacks corrupts the pythonnet/GIL
# state badly enough to segfault the whole process (AccessViolationException
# at PyGILState_Ensure). Calling back INTO the QuoteCom API from within its own
# event-dispatch thread is untested territory on top of that, so it gets the
# same isolation treatment as a precaution, not just the same try/except.
class RotationManager:
    def __init__(self, slots, timeout_s):
        self.slots = slots
        self.timeout_s = timeout_s
        self.lock = threading.Lock()
        self.pending = None   # collections.deque, set in start()
        self.active = {}      # code -> subscribed_at (epoch)
        self.swap_queue = queue.Queue()
        self._worker = None
        self._timeout_checker_stop = threading.Event()

    def start(self, codes):
        import collections
        with self.lock:
            self.pending = collections.deque(codes)
            self.active = {}
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
        threading.Thread(target=self._timeout_loop, daemon=True).start()

        initial = []
        with self.lock:
            for _ in range(min(self.slots, len(self.pending))):
                code = self.pending.popleft()
                self.active[code] = time.time()
                initial.append(code)
        for code in initial:
            self._subscribe_one(code)
        log_debug(f"[ROTATION] started: {len(initial)} initial slots "
                  f"(slots={self.slots}, pending={len(self.pending)})")

    def on_tick(self, code):
        """Call this from onQuoteRcvMessage for every Depth message received.
        Cheap and non-blocking: it only enqueues, the worker thread does the
        actual Sub/UnSub swap."""
        with self.lock:
            if code not in self.active:
                return  # not one of ours right now (already swapped out, or duplicate)
        self.swap_queue.put(("tick", code))

    def _timeout_loop(self):
        while not self._timeout_checker_stop.wait(1.0):
            now = time.time()
            with self.lock:
                stale = [c for c, t0 in self.active.items() if now - t0 >= self.timeout_s]
            for code in stale:
                self.swap_queue.put(("timeout", code))

    def _worker_loop(self):
        while True:
            reason, code = self.swap_queue.get()
            if reason == "STOP":
                return
            with self.lock:
                if code not in self.active:
                    continue  # already swapped by a race with the timeout check
                del self.active[code]
                next_code = self.pending.popleft() if self.pending else None
                if next_code is not None:
                    self.active[next_code] = time.time()
                self.pending.append(code)  # requeue: it'll come back around later

            self._unsubscribe_one(code)
            if next_code is not None:
                self._subscribe_one(next_code)

            msg = f"Received tick from {code}, removing and adding {next_code}" \
                if reason == "tick" else \
                f"No tick from {code} within {self.timeout_s}s, removing and adding {next_code}"
            log_debug(f"[ROTATION] {msg}")
            gui_queue.put({"type": "rotation", "text": msg})

    def _subscribe_one(self, code):
        try:
            s1 = quoteCom.SubQuotesMatch(code)
            s2 = quoteCom.SubQuotesDepth(code)
            log_debug(f"[ROTATION] subscribed {code} (match={s1}, depth={s2})")
        except Exception:
            log_debug(f"[ROTATION] subscribe failed for {code}:\n" + traceback.format_exc())

    def _unsubscribe_one(self, code):
        try:
            quoteCom.UnSubQuotesMatch(code)
            quoteCom.UnSubQuotesDepth(code)
        except Exception:
            log_debug(f"[ROTATION] unsubscribe failed for {code}:\n" + traceback.format_exc())

    def stop(self):
        self._timeout_checker_stop.set()
        with self.lock:
            still_active = list(self.active.keys())
        for code in still_active:
            self._unsubscribe_one(code)
        self.swap_queue.put(("STOP", None))


rotation_manager = RotationManager(ROTATION_SLOTS_DEFAULT, ROTATION_TIMEOUT_S) if STRATEGY == "ROTATION" else None


# ── BACKUP PLAN #2 (inactive unless STRATEGY = "POLLING"): round-robin
# RetriveLastPriceStock across every code, forever. No subscribe/unsubscribe
# state at all — just fire the next query, wait a bit, fire the next.
#
# Same isolation discipline as RotationManager: the poll loop runs on its own
# dedicated thread, never inside the .NET callback thread. The response
# (DT=QUOTE_LAST_PRICE_STOCK / PI30026) arrives asynchronously via the normal
# onQuoteRcvMessage callback and is matched back to a request purely by
# pkg.StockNo — there is no request-id round-trip in this SDK, so latency
# logging below assumes responses come back roughly in send order, which is
# an assumption to sanity-check against tomorrow's real timestamps, not a
# guarantee.
class PollingManager:
    def __init__(self, delay_between_calls_s):
        self.delay = delay_between_calls_s
        self._stop = threading.Event()
        self._sent_at_lock = threading.Lock()
        self._sent_at = {}   # code -> epoch time the request was fired
        self.cycle_count = 0

    def start(self, codes):
        self.codes = list(codes)
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        log_debug(f"[POLLING] started: {len(self.codes)} codes, "
                  f"delay={self.delay*1000:.0f}ms/call, "
                  f"est. full-sweep={self.delay*len(self.codes):.1f}s")
        while not self._stop.is_set():
            cycle_start = time.time()
            for code in self.codes:
                if self._stop.is_set():
                    return
                try:
                    with self._sent_at_lock:
                        self._sent_at[code] = time.time()
                    quoteCom.RetriveLastPriceStock(code)
                except Exception:
                    log_debug(f"[POLLING] RetriveLastPriceStock({code}) failed:\n"
                              + traceback.format_exc())
                time.sleep(self.delay)
            self.cycle_count += 1
            elapsed = time.time() - cycle_start
            log_debug(f"[POLLING] full sweep #{self.cycle_count} complete: "
                      f"{len(self.codes)} codes in {elapsed:.1f}s "
                      f"({len(self.codes)/elapsed:.1f} req/s actual)")
            gui_queue.put({
                "type": "status",
                "text": f"Polling sweep #{self.cycle_count} done in {elapsed:.1f}s",
            })

    def on_response(self, code):
        """Call from onQuoteRcvMessage on every QUOTE_LAST_PRICE_STOCK message.
        Returns round-trip latency in seconds, or None if this code wasn't
        one we were tracking (e.g. a stray response after stop())."""
        with self._sent_at_lock:
            sent = self._sent_at.pop(code, None)
        if sent is None:
            return None
        return time.time() - sent

    def stop(self):
        self._stop.set()


polling_manager = PollingManager(POLL_DELAY_BETWEEN_CALLS_S) if STRATEGY == "POLLING" else None


# ── QuoteCom callbacks ───────────────────────────────────────────────────────
# Every callback body is wrapped in try/except: an unhandled Python exception
# raised inside a .NET-invoked callback previously corrupted the pythonnet/GIL
# state and segfaulted the whole process (AccessViolationException at
# PyGILState_Ensure) — see the earlier testing.py/test.py crashes. A caught
# exception here just gets logged instead of taking the app down.

def onQuoteGetStatus(sender, status, msg):
    try:
        log_debug(f"[STATUS] {status}")
        gui_queue.put({"type": "status", "text": f"Status: {status}"})
        if status == COM_STATUS.LOGIN_FAIL:
            log_debug("[STATUS] LOGIN FAILED")
    except Exception:
        log_debug("[STATUS] callback error:\n" + traceback.format_exc())


def onQuoteRcvMessage(sender, pkg):
    try:
        dtv = int(pkg.DT)
        name = dt_name(dtv)

        if name in ("QUOTE_STOCK_DEPTH1", "QUOTE_STOCK_DEPTH2"):
            code = str(pkg.StockNo).strip()
            bid = str(pkg.BUY_DEPTH[0].PRICE)
            bid_qty = str(pkg.BUY_DEPTH[0].QUANTITY)
            ask = str(pkg.SELL_DEPTH[0].PRICE)
            ask_qty = str(pkg.SELL_DEPTH[0].QUANTITY)
            mark_coverage(code, "got_depth")
            gui_queue.put({
                "type": "depth", "code": code,
                "bid": bid, "bid_qty": bid_qty,
                "ask": ask, "ask_qty": ask_qty,
            })
            if STRATEGY == "ROTATION":
                rotation_manager.on_tick(code)

        elif name in ("QUOTE_STOCK_MATCH1", "QUOTE_STOCK_MATCH2"):
            code = str(pkg.StockNo).strip()
            price = str(pkg.Match_Price)
            qty = str(pkg.Match_Qty)
            raw_t = str(pkg.Match_Time).zfill(9)
            t_fmt = f"{raw_t[0:2]}:{raw_t[2:4]}:{raw_t[4:6]}"
            mark_coverage(code, "got_match")
            gui_queue.put({
                "type": "match", "code": code,
                "price": price, "qty": qty, "time": t_fmt,
            })

        elif name == "QUOTE_LAST_PRICE_STOCK":
            # Response to RetriveLastPriceStock — only fires when STRATEGY ==
            # "POLLING" actually issues those queries. Same PI30026 shape we
            # verified earlier today (LastMatchPrice + BUY_DEPTH/SELL_DEPTH),
            # just arriving as a query response instead of a push.
            code = str(pkg.StockNo).strip()
            bid = str(pkg.BUY_DEPTH[0].PRICE)
            ask = str(pkg.SELL_DEPTH[0].PRICE)
            mark_coverage(code, "got_depth")
            gui_queue.put({"type": "depth", "code": code, "bid": bid, "ask": ask,
                           "bid_qty": str(pkg.BUY_DEPTH[0].QUANTITY),
                           "ask_qty": str(pkg.SELL_DEPTH[0].QUANTITY)})
            if STRATEGY == "POLLING":
                latency = polling_manager.on_response(code)
                if latency is not None:
                    log_debug(f"[POLLING] {code} round-trip={latency*1000:.0f}ms "
                              f"last={pkg.LastMatchPrice} bid={bid} ask={ask}")

        elif name == "LOGIN":
            # Matches KGI's own quotecomPy.py example: the login-response
            # package (P001503) carries Qnum — the account's max number of
            # simultaneously-registerable live-quote codes.
            qnum = getattr(pkg, "Qnum", None)
            log_debug(f"[LOGIN MSG] Qnum (registrable quote codes) = {qnum}")
            gui_queue.put({"type": "qnum", "qnum": qnum})
            if STRATEGY == "ROTATION" and qnum:
                try:
                    rotation_manager.slots = int(qnum)
                    log_debug(f"[ROTATION] slot count set from observed Qnum: {qnum}")
                except (TypeError, ValueError):
                    pass

        else:
            # Anything unexpected (errors, notices, session messages) is
            # logged with its raw field dump rather than silently dropped —
            # this is exactly the kind of thing that would explain a
            # subscription being rejected/truncated.
            try:
                fields = {
                    f.Name: str(f.GetValue(pkg))
                    for f in clr.GetClrType(pkg.GetType()).GetFields()
                }
            except Exception:
                fields = {}
            log_debug(f"[MSG] DT={dtv} ({name}) fields={fields}")

    except Exception:
        log_debug("[MSG] callback error:\n" + traceback.format_exc())


# ── Background setup thread: connect, login, download product/warrant master
# data, resolve the TSMC warrant list, then subscribe to ALL of it in one shot
# (per explicit instruction, to empirically test the Qnum=25 cap tomorrow
# rather than assume it and pre-emptively chunk).
quoteCom = None
login_ready = threading.Event()


def setup_and_subscribe():
    global quoteCom, all_codes
    log_debug("=" * 70)
    log_debug("SETUP: starting")
    log_debug("=" * 70)

    quoteCom = QuoteCom("", 443, SID, TOKEN)
    quoteCom.OnGetStatus += onQuoteGetStatus
    quoteCom.OnRcvMessage += onQuoteRcvMessage

    log_debug("Connecting...")
    quoteCom.Connect2Quote("quoteapi.kgi.com.tw", 443, USER_ID, PASSWORD, ' ', "")

    if not login_ready.wait(timeout=20):
        log_debug("SETUP FAILED: timed out waiting for login")
        gui_queue.put({"type": "status", "text": "SETUP FAILED: login timeout"})
        return
    time.sleep(2)

    try:
        rc1 = quoteCom.RetriveProductTSE()
        rc2 = quoteCom.RetriveProductOTC()
        log_debug(f"RetriveProductTSE()={rc1} RetriveProductOTC()={rc2}")
    except Exception:
        log_debug("RetriveProductTSE/OTC failed:\n" + traceback.format_exc())
    time.sleep(5)

    try:
        rc3 = quoteCom.RetriveWarrantInfo()
        rc4 = quoteCom.RetriveWarrantPrice()
        log_debug(f"RetriveWarrantInfo()={rc3} RetriveWarrantPrice()={rc4}")
    except Exception:
        log_debug("RetriveWarrantInfo/Price failed:\n" + traceback.format_exc())
    time.sleep(5)

    try:
        results = list(quoteCom.GetWarrantTargetStock(UNDERLYING_STOCK))
        raw_codes = [str(w.WarrantID).strip() for w in results]
    except Exception:
        log_debug("GetWarrantTargetStock failed:\n" + traceback.format_exc())
        raw_codes = []

    all_codes = [c for c in raw_codes if re.fullmatch(r"\d{6}", c)]
    invalid_codes = [c for c in raw_codes if c not in all_codes]
    if invalid_codes:
        log_debug(f"Discarded {len(invalid_codes)} non-6-digit warrant codes, "
                  f"e.g. {invalid_codes[:10]}")

    log_debug(f"Resolved {len(all_codes)} warrant codes for underlying {UNDERLYING_STOCK}")
    gui_queue.put({"type": "populate", "codes": list(all_codes)})

    if not all_codes:
        log_debug("SETUP FAILED: no warrant codes resolved, nothing to subscribe")
        return

    if STRATEGY == "ROTATION":
        log_debug(f"Using ROTATION backup plan: {rotation_manager.slots} slots, "
                  f"{len(all_codes)} total codes, timeout={rotation_manager.timeout_s}s")
        rotation_manager.start(all_codes)
        gui_queue.put({
            "type": "status",
            "text": f"Rotation backup active: {rotation_manager.slots} slots "
                    f"cycling through {len(all_codes)} codes",
        })
        log_debug("SETUP: done (rotation mode). Now waiting for live messages...")
        return

    if STRATEGY == "POLLING":
        log_debug(f"Using POLLING backup plan: {len(all_codes)} codes, "
                  f"{POLL_DELAY_BETWEEN_CALLS_S*1000:.0f}ms between calls")
        polling_manager.start(all_codes)
        gui_queue.put({
            "type": "status",
            "text": f"Polling backup active: round-robin over {len(all_codes)} codes",
        })
        log_debug("SETUP: done (polling mode). Now waiting for live messages...")
        return

    joined = "|".join(all_codes)
    log_debug(f"Subscribing to ALL {len(all_codes)} codes in a single call "
              f"(string length={len(joined)} chars)")

    try:
        status_match = quoteCom.SubQuotesMatch(joined)
        log_debug(f"SubQuotesMatch(ALL {len(all_codes)} codes) -> status={status_match}")
    except Exception:
        log_debug("SubQuotesMatch(ALL) raised:\n" + traceback.format_exc())
        status_match = None

    try:
        status_depth = quoteCom.SubQuotesDepth(joined)
        log_debug(f"SubQuotesDepth(ALL {len(all_codes)} codes) -> status={status_depth}")
    except Exception:
        log_debug("SubQuotesDepth(ALL) raised:\n" + traceback.format_exc())
        status_depth = None

    gui_queue.put({
        "type": "status",
        "text": f"Subscribed all {len(all_codes)} codes "
                f"(Match status={status_match}, Depth status={status_depth})",
    })
    log_debug("SETUP: done. Now waiting for live messages...")


def onQuoteGetStatus_login_hook(sender, status, msg):
    # Chained onto the same event separately from onQuoteGetStatus above so the
    # login_ready Event is set regardless of what onQuoteGetStatus itself does.
    try:
        if status == COM_STATUS.LOGIN_READY:
            login_ready.set()
        elif status == COM_STATUS.LOGIN_FAIL:
            login_ready.set()
    except Exception:
        log_debug("[STATUS hook] error:\n" + traceback.format_exc())


# ── Tkinter GUI ──────────────────────────────────────────────────────────────
root = tk.Tk()
root.title(f"TSMC ({UNDERLYING_STOCK}) Warrant Live Prices")
root.geometry("900x700")

top = ttk.Frame(root, padding=8)
top.pack(fill="x")

status_var = tk.StringVar(value="Connecting...")
qnum_var = tk.StringVar(value="Qnum: (unknown yet)")
coverage_var = tk.StringVar(value="Live data received: 0 / 0 warrant codes")

ttk.Label(top, textvariable=status_var, font=("Segoe UI", 10, "bold")).pack(anchor="w")
ttk.Label(top, textvariable=qnum_var).pack(anchor="w")
ttk.Label(top, textvariable=coverage_var, font=("Segoe UI", 10, "bold")).pack(anchor="w")

tree_frame = ttk.Frame(root)
tree_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

tree = ttk.Treeview(tree_frame, columns=("code", "bid", "ask"), show="headings")
tree.heading("code", text="Code")
tree.heading("bid", text="Bid")
tree.heading("ask", text="Ask")
tree.column("code", width=100, anchor="center")
tree.column("bid", width=100, anchor="center")
tree.column("ask", width=100, anchor="center")

tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
tree.configure(yscrollcommand=tree_scroll.set)
tree.pack(side="left", fill="both", expand=True)
tree_scroll.pack(side="right", fill="y")

log_frame = ttk.LabelFrame(root, text="Tick log", padding=4)
log_frame.pack(fill="both", expand=False, padx=8, pady=(0, 8))
log_widget = scrolledtext.ScrolledText(log_frame, height=10, state="disabled", wrap="word")
log_widget.pack(fill="both", expand=True)

_log_line_count = 0


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


def drain_queue():
    try:
        while True:
            event = gui_queue.get_nowait()
            etype = event.get("type")

            if etype == "populate":
                codes = event["codes"]
                for code in codes:
                    if not tree.exists(code):
                        tree.insert("", "end", iid=code, values=(code, "-", "-"))
                coverage_var.set(f"Live data received: 0 / {len(codes)} warrant codes")
                status_var.set(f"Loaded {len(codes)} TSMC warrant codes. Subscribing...")

            elif etype == "depth":
                code = event["code"]
                if tree.exists(code):
                    tree.set(code, "bid", event["bid"])
                    tree.set(code, "ask", event["ask"])
                else:
                    tree.insert("", "end", iid=code, values=(code, event["bid"], event["ask"]))

            elif etype == "match":
                append_log_line(
                    f"Warrant {event['code']} traded {event['qty']} units "
                    f"at {event['price']} NTD at time {event['time']}"
                )

            elif etype == "qnum":
                qnum_var.set(f"Qnum (account subscription-slot limit): {event['qnum']}")

            elif etype == "status":
                status_var.set(event["text"])
                append_log_line(f"[STATUS] {event['text']}")

            elif etype == "rotation":
                append_log_line(f"[ROTATION] {event['text']}")

    except queue.Empty:
        pass

    total, covered, depth_covered, match_covered = coverage_summary()
    if total:
        coverage_var.set(
            f"Live data received: {covered} / {total} warrant codes "
            f"(depth={depth_covered}, match={match_covered})"
        )

    root.after(100, drain_queue)


def log_coverage_snapshot():
    total, covered, depth_covered, match_covered = coverage_summary()
    log_debug(
        f"[COVERAGE SNAPSHOT] {covered}/{total} codes have received >=1 message "
        f"(depth={depth_covered}, match={match_covered}). "
        f"If this number stops growing well short of {total}, that is strong "
        f"evidence of an account-wide subscription cap (see Qnum)."
    )
    root.after(COVERAGE_SNAPSHOT_INTERVAL_MS, log_coverage_snapshot)


def on_close():
    log_debug("Shutdown requested by user (window closed)")
    if STRATEGY == "ROTATION":
        try:
            rotation_manager.stop()
        except Exception:
            log_debug("Rotation manager stop failed:\n" + traceback.format_exc())
    if STRATEGY == "POLLING":
        try:
            polling_manager.stop()
        except Exception:
            log_debug("Polling manager stop failed:\n" + traceback.format_exc())
    try:
        if quoteCom is not None and all_codes and STRATEGY == "FULL_BATCH":
            joined = "|".join(all_codes)
            quoteCom.UnSubQuotesMatch(joined)
            quoteCom.UnSubQuotesDepth(joined)
    except Exception:
        log_debug("Unsubscribe on close failed:\n" + traceback.format_exc())
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
        log_debug("Dispose on close failed:\n" + traceback.format_exc())

    total, covered, depth_covered, match_covered = coverage_summary()
    log_debug(
        f"[FINAL COVERAGE] {covered}/{total} codes received >=1 message "
        f"(depth={depth_covered}, match={match_covered})"
    )
    if total and covered < total:
        never_updated = [c for c in all_codes if c not in coverage]
        log_debug(f"[FINAL COVERAGE] {len(never_updated)} codes never received "
                  f"any update. Sample: {never_updated[:50]}")

    root.destroy()


root.protocol("WM_DELETE_WINDOW", on_close)

# ── Wire up the login-ready hook alongside the main status logger, then kick
# off the connect/subscribe sequence on a background thread so it doesn't
# block the Tk mainloop, and start the GUI polling / periodic diagnostics.
quoteCom_started = False


def start_background_setup():
    global quoteCom_started
    if quoteCom_started:
        return
    quoteCom_started = True
    t = threading.Thread(target=_setup_wrapper, daemon=True)
    t.start()


def _setup_wrapper():
    global quoteCom
    setup_and_subscribe()


def _install_login_hook():
    # quoteCom is created inside setup_and_subscribe(); this hook must attach
    # to the same instance. We poll briefly until it exists.
    for _ in range(200):
        if quoteCom is not None:
            quoteCom.OnGetStatus += onQuoteGetStatus_login_hook
            return
        time.sleep(0.05)


threading.Thread(target=_install_login_hook, daemon=True).start()
start_background_setup()

root.after(100, drain_queue)
root.after(COVERAGE_SNAPSHOT_INTERVAL_MS, log_coverage_snapshot)

log_debug(f"Debug log file: {DEBUG_LOG_PATH}")
root.mainloop()
