import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
import csv
import json
import threading
import time
import traceback
import urllib.request
from datetime import datetime

import clr
assembly_path = r"C:\Users\user\OneDrive\Desktop\websocket\Taiwan-Websocket-Data\QuoteComExamplePy"
sys.path.append(assembly_path)
clr.AddReference("Package")
clr.AddReference("PushClient")
clr.AddReference("QuoteCom")
from Intelligence import QuoteCom, COM_STATUS, DT

from kgi_config import TOKEN, SID, USER_ID, PASSWORD

# ── What this measures ───────────────────────────────────────────────────────
# Compares two ways of getting close-to-live prices for a TSMC (2330) stock
# option ("CDO" on TAIFEX):
#   - KGI: native push subscription via the SAME SubQuotesMatch/SubQuotesDepth
#     calls this project already uses for stocks/warrants. Confirmed live
#     (2026-08-01, off-hours) that the account has TAIFEX entitlement and
#     that these calls accept a real CDO symbol and return status 0 (success)
#     — see memory note warrant_orderbook_collector-adjacent research.
#   - TAIFEX_REST: TAIFEX's OWN public market-info site
#     (mis.taifex.com.tw/futures) turns out to expose a plain, anonymous,
#     no-login JSON API for the exact same data (bid/ask/last/volume/time)
#     that its own live-updating options-chain page displays. Confirmed
#     working via a direct unauthenticated fetch from a fresh browser
#     session (no cookies, no disclaimer acceptance needed). This is the
#     "unconventional" source — coming straight from the exchange itself,
#     not a third-party vendor.
# Both are logged with wall-clock arrival time AND whatever exchange-reported
# time field is available (KGI's Match_Time; TAIFEX's CTime), so latency can
# be computed the same way test_cmoney_vs_kgi.py did for warrants: compare
# first-detected time of a given price/quote change against when it actually
# happened.
#
# KGI's exact push message DT type for a TAIFEX option is UNVERIFIED — no
# live options ticks exist off-hours to observe one. This script assumes it
# reuses QUOTE_STOCK_MATCH1/2 and QUOTE_STOCK_DEPTH1/2 (same as stocks and
# warrants), which is plausible since the wire protocol likely doesn't
# distinguish instrument class at the DT level, only by symbol — but ALSO
# logs the full field dump of any OTHER DT type received for this symbol, so
# if that assumption is wrong, Monday's log immediately reveals the real DT
# name/fields instead of silently dropping the data.

UNDERLYING_COMID = "CDO"   # TSMC (2330) stock options on TAIFEX
TAIFEX_POLL_INTERVAL_S = 3   # how often to hit TAIFEX's public REST endpoint.
                              # Conservative first guess for an anonymous public
                              # API with no documented rate limit — tune after
                              # seeing Monday's real response times/any errors.
TEST_DURATION_S = None   # None = run until Ctrl+C; set a number to auto-stop

LOG_PATH = "taifex_vs_kgi_options_test.csv"
log_lock = threading.Lock()

TAIFEX_BASE = "https://mis.taifex.com.tw/futures/api"
_HEADERS = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}


def log_row(source, symbol, bid, ask, last, volume, exch_time, extra=""):
    now = datetime.now().isoformat(timespec="milliseconds")
    with log_lock:
        with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([now, source, symbol, bid, ask, last, volume, exch_time, extra])
    print(f"{now} [{source}] {symbol} bid={bid} ask={ask} last={last} "
          f"vol={volume} exch_time={exch_time} {extra}", flush=True)


def taifex_post(action, body):
    req = urllib.request.Request(
        f"{TAIFEX_BASE}/{action}",
        data=json.dumps(body).encode("utf-8"),
        headers=_HEADERS,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_cdo_months():
    data = taifex_post("getCmdyMonthDDLItemByKind", {"CID": UNDERLYING_COMID, "MarketType": "0"})
    items = data.get("RtData", {}).get("Items", []) if data.get("RtCode") == "0" else []
    return [it["item"] for it in items if it["item"] and it["item"] != "現貨"]


def get_cdo_quotes(month):
    data = taifex_post("getQuoteListOption",
                        {"CID": UNDERLYING_COMID, "MarketType": "0", "ExpireMonth": month})
    if data.get("RtCode") != "0":
        return []
    return data.get("RtData", {}).get("QuoteList", []) or []


def find_liquid_contract():
    """Pick a CDO contract to test against. Prefers one with real observed
    volume or a live bid/ask; falls back to the first contract found at all
    (with a loud warning) so the script is still exercisable off-hours."""
    months = get_cdo_months()
    print(f"Available CDO expiry months: {months}")
    all_candidates = []
    for month in months:
        try:
            quotes = get_cdo_quotes(month)
        except Exception:
            print(f"get_cdo_quotes({month}) failed:\n" + traceback.format_exc())
            continue
        for q in quotes:
            all_candidates.append((month, q))
        time.sleep(0.2)   # be polite to a public anonymous endpoint

    print(f"Total contracts across all months: {len(all_candidates)}")

    def has_quote(q):
        return bool(q.get("CBidPrice1")) or bool(q.get("CAskPrice1"))

    def volume_of(q):
        try:
            return int(q.get("CTotalVolume") or 0)
        except ValueError:
            return 0

    with_volume = [(m, q) for m, q in all_candidates if volume_of(q) > 0]
    with_quote = [(m, q) for m, q in all_candidates if has_quote(q)]

    if with_volume:
        with_volume.sort(key=lambda mq: -volume_of(mq[1]))
        month, chosen = with_volume[0]
        print(f"Picked by highest observed volume: {chosen['SymbolID']} (vol={volume_of(chosen)})")
    elif with_quote:
        month, chosen = with_quote[0]
        print(f"No volume anywhere; picked first contract with a live bid/ask: {chosen['SymbolID']}")
    elif all_candidates:
        month, chosen = all_candidates[0]
        print(f"WARNING: no contract shows any volume or bid/ask (market likely closed) — "
              f"falling back to the first resolved contract: {chosen['SymbolID']}. "
              f"This is NOT evidence of liquidity; rerun during market hours for a real pick.")
    else:
        raise RuntimeError("No CDO contracts resolved at all — check month/CID params")

    return month, chosen


def taifex_poll_loop(month, symbol_id, stop_event):
    while not stop_event.is_set():
        try:
            quotes = get_cdo_quotes(month)
            match = next((q for q in quotes if q.get("SymbolID") == symbol_id), None)
            if match is None:
                log_row("TAIFEX_REST", symbol_id, "ERROR", "", "", "", "", "symbol not found in month list")
            else:
                log_row("TAIFEX_REST", symbol_id,
                        match.get("CBidPrice1", ""), match.get("CAskPrice1", ""),
                        match.get("CLastPrice", ""), match.get("CTotalVolume", ""),
                        match.get("CTime", ""))
        except Exception as e:
            log_row("TAIFEX_REST", symbol_id, "ERROR", "", "", "", "", str(e))
        stop_event.wait(TAIFEX_POLL_INTERVAL_S)


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


quoteCom = None
login_ready = threading.Event()
kgi_symbol = None   # set once we know which contract we're testing


def on_status(sender, status, msg):
    if status in (COM_STATUS.LOGIN_READY, COM_STATUS.LOGIN_FAIL):
        login_ready.set()


def on_message(sender, pkg):
    try:
        dtv = int(pkg.DT)
        name = dt_name(dtv)

        if name in ("QUOTE_STOCK_MATCH1", "QUOTE_STOCK_MATCH2"):
            code = str(pkg.StockNo).strip()
            if code != kgi_symbol:
                return
            log_row("KGI_PUSH", code, "", "", str(pkg.Match_Price), str(pkg.Match_Qty),
                     fmt_time(pkg.Match_Time), "match")

        elif name in ("QUOTE_STOCK_DEPTH1", "QUOTE_STOCK_DEPTH2"):
            code = str(pkg.StockNo).strip()
            if code != kgi_symbol:
                return
            bid = str(pkg.BUY_DEPTH[0].PRICE)
            ask = str(pkg.SELL_DEPTH[0].PRICE)
            log_row("KGI_PUSH", code, bid, ask, "", "", fmt_time(pkg.Match_Time), "depth")

        else:
            # Unrecognized DT for our subscribed symbol — dump everything so
            # Monday's real traffic reveals what options actually arrive as,
            # in case the QUOTE_STOCK_* assumption above is wrong.
            try:
                fields = {f.Name: str(f.GetValue(pkg)) for f in clr.GetClrType(pkg.GetType()).GetFields()}
            except Exception:
                fields = {}
            try:
                stockno = str(getattr(pkg, "StockNo", "")).strip()
            except Exception:
                stockno = ""
            if stockno == kgi_symbol or not stockno:
                print(f"[UNRECOGNIZED DT] {dtv} ({name}) fields={fields}", flush=True)
    except Exception:
        print("on_message error:\n" + traceback.format_exc(), flush=True)


def kgi_loop(stop_event):
    global quoteCom
    quoteCom = QuoteCom("", 443, SID, TOKEN)
    quoteCom.OnGetStatus += on_status
    quoteCom.OnRcvMessage += on_message
    quoteCom.Connect2Quote("quoteapi.kgi.com.tw", 443, USER_ID, PASSWORD, ' ', "")
    if not login_ready.wait(timeout=20):
        print("KGI LOGIN TIMEOUT", flush=True)
        return
    time.sleep(2)

    try:
        s1 = quoteCom.SubQuotesMatch(kgi_symbol)
        s2 = quoteCom.SubQuotesDepth(kgi_symbol)
        print(f"KGI subscribed {kgi_symbol} (match={s1}, depth={s2})", flush=True)
    except Exception:
        print("KGI subscribe failed:\n" + traceback.format_exc(), flush=True)

    stop_event.wait()   # keep the connection alive until told to stop
    try:
        quoteCom.UnSubQuotesMatch(kgi_symbol)
        quoteCom.UnSubQuotesDepth(kgi_symbol)
        quoteCom.Dispose()
    except Exception:
        pass


if __name__ == "__main__":
    with open(LOG_PATH, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["timestamp", "source", "symbol", "bid", "ask", "last",
                                  "volume", "exchange_time", "extra"])

    print(f"Finding a contract to test for underlying comid={UNDERLYING_COMID}...")
    month, chosen = find_liquid_contract()
    symbol_id = chosen["SymbolID"]           # TAIFEX format, e.g. "CDO18600HK-O"
    kgi_symbol = symbol_id.split("-")[0]     # KGI format, e.g. "CDO18600HK"
    print(f"Testing contract: TAIFEX SymbolID={symbol_id}, KGI ComId={kgi_symbol}, "
          f"month={month}, strike={chosen.get('StrikePrice')}, CP={chosen.get('CP')}")

    stop_event = threading.Event()
    threading.Thread(target=taifex_poll_loop, args=(month, symbol_id, stop_event), daemon=True).start()
    threading.Thread(target=kgi_loop, args=(stop_event,), daemon=True).start()

    print(f"Running. Ctrl+C to stop."
          + (f" Auto-stop after {TEST_DURATION_S}s." if TEST_DURATION_S else ""))
    try:
        start = time.time()
        while True:
            if TEST_DURATION_S and time.time() - start > TEST_DURATION_S:
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        time.sleep(1)
        print("Stopped.")
