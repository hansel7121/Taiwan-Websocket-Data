import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
import os
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
#
# "HYBRID" (active): stop treating every code equally. Use the scarce
#   Qnum push slots on whichever codes are CURRENTLY trading fastest (true
#   real-time where it matters), and background-poll everything else via
#   RetriveLastPriceStock (best-effort freshness, no fixed target — just
#   faster than a website refresh). HybridManager below.
#   Ranking signal: both push MATCH packages (Total_Qty) and poll
#   LAST_PRICE_STOCK responses (TotalMatchQty) carry a cumulative day-volume
#   field KGI's own quotecomPy.py sample labels "總量" on both — verified by
#   inspection to be the same quantity, not verified side-by-side live. A
#   raw delta between two observations of that counter, divided by the time
#   between them, gives a volume/sec rate that's comparable regardless of
#   whether the two observations came from push or poll — this is what
#   makes ranking possible despite push and poll arriving at wildly
#   different frequencies. Smoothed with an EWMA (HYBRID_RATE_EWMA_ALPHA) so
#   one anomalous delta can't cause a one-shot promotion.
#   Every HYBRID_RERANK_INTERVAL_S, the top `slots` codes by that rate get
#   push-subscribed; a currently-subscribed code is only demoted once its
#   rank falls below `slots + HYBRID_DEMOTE_MARGIN` (hysteresis), not the
#   instant it drops below `slots` — otherwise a code sitting right at the
#   boundary would swap in and out every single tick. Unverified: whether
#   this margin is the right size, and whether the server tolerates this
#   swap rate any better/worse than ROTATION's own churn.
#   Cold start: no code has any rate data at t=0, so promotion is skipped
#   entirely (pure polling) until at least one code has two observations.
#   A rate needs a first AND second sighting of the same code, so the
#   earliest that can happen is one full poll sweep in — given the ~39s
#   sweep time measured under POLLING, that's up to ~78s worst-case for a
#   code polled late in the first sweep. Derived from measured data, not a
#   fresh guess.
STRATEGY = "HYBRID"   # one of: "FULL_BATCH", "ROTATION", "POLLING", "HYBRID"

ROTATION_SLOTS_DEFAULT = 25       # overridden at runtime by the observed Qnum, if received
ROTATION_TIMEOUT_S = 30           # force-advance a code that never ticks within this long

POLL_DELAY_BETWEEN_CALLS_S = 0.035   # ~35ms -> ~29 req/s -> ~39s per full 1116-code sweep

HYBRID_RERANK_INTERVAL_S = 5      # how often to re-rank and possibly swap push slots.
                                   # Assumed, not measured: balances slot freshness against
                                   # avoiding Sub/UnSub churn (server-side churn cooldown is
                                   # unverified, per the ROTATION notes above). Tune after
                                   # observing real swap frequency in the debug log.
HYBRID_DEMOTE_MARGIN = 5          # an active code is only demoted once its rank falls below
                                   # (slots + this), not just below slots. Assumed (20% of a
                                   # 25-slot budget): stops boundary codes from swapping in
                                   # and out every rerank tick. Pure guess until real
                                   # activity-rate data exists to tune it against.
HYBRID_RATE_EWMA_ALPHA = 0.3      # smoothing factor for the volume/sec activity score.
                                   # Assumed: reacts to a code going hot within ~2-3
                                   # observations without one anomalous delta causing a
                                   # one-shot promotion. Not measured against real intraday
                                   # volume-burst shapes.
HYBRID_POLL_DELAY_BETWEEN_CALLS_S = 0.035   # same reasoning as POLL_DELAY_BETWEEN_CALLS_S;
                                   # kept separate since HYBRID's poll list is ~`slots`
                                   # codes shorter each cycle (active codes excluded), so
                                   # this may be safely tunable independent of pure POLLING
                                   # mode once real numbers exist.

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


# ── HYBRID activity tracking: code -> cumulative-volume rate (contracts/sec),
# fed by both push MATCH ticks (Total_Qty) and poll LAST_PRICE_STOCK responses
# (TotalMatchQty). Kept unconditional on STRATEGY (cheap dict update, same
# cost class as mark_coverage above) so the data structure is harmless dead
# weight in other modes rather than needing its own strategy guard at every
# call site.
activity_lock = threading.Lock()
activity = {}  # code -> {"last_cum_qty": int|None, "last_obs_t": float|None, "rate_ewma": float}


def update_activity(code, cum_qty, now=None):
    if now is None:
        now = time.time()
    with activity_lock:
        entry = activity.setdefault(code, {"last_cum_qty": None, "last_obs_t": None, "rate_ewma": 0.0})
        last_qty = entry["last_cum_qty"]
        last_t = entry["last_obs_t"]
        if last_qty is not None and last_t is not None and now > last_t and cum_qty >= last_qty:
            raw_rate = (cum_qty - last_qty) / (now - last_t)
            entry["rate_ewma"] = HYBRID_RATE_EWMA_ALPHA * raw_rate + (1 - HYBRID_RATE_EWMA_ALPHA) * entry["rate_ewma"]
        # cum_qty < last_qty (counter reset/edge case): skip the rate update,
        # just refresh the observation below so the next delta is still valid.
        entry["last_cum_qty"] = cum_qty
        entry["last_obs_t"] = now


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


# ── HYBRID strategy (active): push-subscribe only the `slots` codes with the
# highest current activity rate (see update_activity above); poll everything
# else via RetriveLastPriceStock. Two dedicated daemon threads, same
# single-writer discipline as RotationManager/PollingManager: only the rerank
# loop ever calls Sub/UnSubQuotes*, and only the poll loop ever calls
# RetriveLastPriceStock — callbacks (onQuoteRcvMessage) only ever feed
# update_activity() and never call back into the QuoteCom API themselves.
class HybridManager:
    def __init__(self, slots, rerank_interval_s, poll_delay_s):
        self.slots = slots
        self.rerank_interval_s = rerank_interval_s
        self.poll_delay_s = poll_delay_s
        self.lock = threading.Lock()
        self.active = {}   # code -> subscribed_at (epoch)
        self.all_codes = []
        self._stop = threading.Event()

    def start(self, codes):
        self.all_codes = list(codes)
        self._code_order = {c: i for i, c in enumerate(self.all_codes)}
        with self.lock:
            self.active = {}
        threading.Thread(target=self._poll_loop, daemon=True).start()
        threading.Thread(target=self._rerank_loop, daemon=True).start()
        log_debug(f"[HYBRID] started: {len(self.all_codes)} codes, "
                  f"{self.slots} push slots, rerank every {self.rerank_interval_s}s")

    def _poll_loop(self):
        cycle_count = 0
        while not self._stop.is_set():
            cycle_start = time.time()
            with self.lock:
                active_now = set(self.active)
            codes_to_poll = [c for c in self.all_codes if c not in active_now]
            for code in codes_to_poll:
                if self._stop.is_set():
                    return
                try:
                    quoteCom.RetriveLastPriceStock(code)
                except Exception:
                    log_debug(f"[HYBRID] RetriveLastPriceStock({code}) failed:\n"
                              + traceback.format_exc())
                time.sleep(self.poll_delay_s)
            cycle_count += 1
            elapsed = time.time() - cycle_start
            log_debug(f"[HYBRID] poll sweep #{cycle_count} complete: "
                      f"{len(codes_to_poll)} codes (excludes {len(active_now)} active) "
                      f"in {elapsed:.1f}s")

    def _rerank_loop(self):
        while not self._stop.wait(self.rerank_interval_s):
            with activity_lock:
                rates = {code: activity[code]["rate_ewma"] for code in activity}
            ranked = sorted(
                self.all_codes,
                key=lambda c: (-rates.get(c, 0.0), self._code_order[c]),
            )
            if not any(rates.get(c, 0.0) > 0 for c in self.all_codes):
                continue  # cold start: no activity data yet, stay in pure-polling mode

            with self.lock:
                active_now = dict(self.active)

            top_n = ranked[:self.slots]
            demote_eligible = set(ranked[:self.slots + HYBRID_DEMOTE_MARGIN])
            to_promote = [c for c in top_n if c not in active_now]  # best-ranked first
            demotable = [c for c in active_now if c not in demote_eligible]
            # rank-order demotable codes worst-first so the least active gets swapped first
            demotable.sort(key=lambda c: rates.get(c, 0.0))

            swaps = []
            for new_code in to_promote:
                if len(active_now) < self.slots:
                    active_now[new_code] = time.time()
                    swaps.append((new_code, None))
                elif demotable:
                    old_code = demotable.pop(0)
                    del active_now[old_code]
                    active_now[new_code] = time.time()
                    swaps.append((new_code, old_code))
                else:
                    break  # no room and nothing eligible to demote this tick

            if not swaps:
                continue

            with self.lock:
                self.active = active_now

            for new_code, old_code in swaps:
                self._subscribe_one(new_code)
                if old_code is not None:
                    self._unsubscribe_one(old_code)
                    msg = (f"promoted {new_code} (rate={rates.get(new_code, 0.0):.2f}/s) "
                           f"-> demoted {old_code} (rate={rates.get(old_code, 0.0):.2f}/s)")
                else:
                    msg = f"promoted {new_code} (rate={rates.get(new_code, 0.0):.2f}/s) into empty slot"
                log_debug(f"[HYBRID] {msg}")
                gui_queue.put({"type": "hybrid", "text": msg})

    def on_match_tick(self, code, total_qty):
        update_activity(code, total_qty)

    def on_poll_response(self, code, total_match_qty):
        update_activity(code, total_match_qty)

    def _subscribe_one(self, code):
        try:
            s1 = quoteCom.SubQuotesMatch(code)
            s2 = quoteCom.SubQuotesDepth(code)
            log_debug(f"[HYBRID] subscribed {code} (match={s1}, depth={s2})")
        except Exception:
            log_debug(f"[HYBRID] subscribe failed for {code}:\n" + traceback.format_exc())

    def _unsubscribe_one(self, code):
        try:
            quoteCom.UnSubQuotesMatch(code)
            quoteCom.UnSubQuotesDepth(code)
        except Exception:
            log_debug(f"[HYBRID] unsubscribe failed for {code}:\n" + traceback.format_exc())

    def stop(self):
        self._stop.set()
        with self.lock:
            still_active = list(self.active.keys())
        for code in still_active:
            self._unsubscribe_one(code)


hybrid_manager = HybridManager(ROTATION_SLOTS_DEFAULT, HYBRID_RERANK_INTERVAL_S,
                                HYBRID_POLL_DELAY_BETWEEN_CALLS_S) if STRATEGY == "HYBRID" else None


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
            # DEPTH packets carry no volume field (bid/ask quantity only), so
            # HYBRID has nothing to extract here — no hook, deliberately.

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
            if STRATEGY == "HYBRID":
                # pkg.Total_Qty is a .NET Decimal; Python's int() can't convert
                # it directly (raises TypeError) — route through str()/float()
                # first, same as every other pkg field in this file already does.
                hybrid_manager.on_match_tick(code, int(float(str(pkg.Total_Qty))))

        elif name == "QUOTE_LAST_PRICE_STOCK":
            # Response to RetriveLastPriceStock — fires when STRATEGY ==
            # "POLLING" or "HYBRID" issues those queries. Same PI30026 shape we
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
            elif STRATEGY == "HYBRID":
                hybrid_manager.on_poll_response(code, int(pkg.TotalMatchQty))

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
            elif STRATEGY == "HYBRID" and qnum:
                try:
                    hybrid_manager.slots = int(qnum)
                    log_debug(f"[HYBRID] slot count set from observed Qnum: {qnum}")
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
        all_codes = [str(w.WarrantID).strip() for w in results]
    except Exception:
        log_debug("GetWarrantTargetStock failed:\n" + traceback.format_exc())
        all_codes = []

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

    if STRATEGY == "HYBRID":
        log_debug(f"Using HYBRID strategy: {hybrid_manager.slots} push slots on the "
                  f"hottest codes, polling the remaining "
                  f"{len(all_codes) - hybrid_manager.slots} codes")
        hybrid_manager.start(all_codes)
        gui_queue.put({
            "type": "status",
            "text": f"Hybrid active: {hybrid_manager.slots} push slots on hottest "
                    f"codes, polling the rest of {len(all_codes)} total",
        })
        log_debug("SETUP: done (hybrid mode). Now waiting for live messages...")
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

            elif etype == "hybrid":
                append_log_line(f"[HYBRID] {event['text']}")

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
    if STRATEGY == "HYBRID":
        try:
            hybrid_manager.stop()
        except Exception:
            log_debug("Hybrid manager stop failed:\n" + traceback.format_exc())
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
