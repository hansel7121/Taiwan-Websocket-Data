import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
import csv
import http.cookiejar
import json
import re
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime

import clr
assembly_path = r"C:\Users\user\OneDrive\Desktop\websocket\Taiwan-Websocket-Data\QuoteComExamplePy"
sys.path.append(assembly_path)
clr.AddReference("Package")
clr.AddReference("PushClient")
clr.AddReference("QuoteCom")
from Intelligence import QuoteCom, COM_STATUS, DT

import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root, for kgi_config
from kgi_config import TOKEN, SID, USER_ID, PASSWORD

# ── What this measures ───────────────────────────────────────────────────────
# For ONE warrant code, log every price observation from two independent
# sources with a wall-clock timestamp:
#   - CMONEY: hits the same backend endpoint the warrantsquery.aspx page
#     itself calls once on load (GET .../ashx/mainpage.ashx?action=GetWarrantData),
#     polled repeatedly here (the page itself never re-polls it — confirmed by
#     reading its JS: no setInterval anywhere, getData() only fires once).
#   - KGI_POLL: calls RetriveLastPriceStock at the same cadence HybridManager
#     uses for codes NOT in the top-25 push set (~50s), simulating exactly
#     what your app shows for a code outside the subscription list.
# Afterward, compare the first wall-clock timestamp each source shows a given
# price value — whichever timestamp is earlier detected that price change
# first. No shared trade-time field is required for this comparison.

TEST_CODE = "066041"   # actively trading in today's HYBRID test run (rate~0.74/s, highest observed)
KGI_POLL_INTERVAL_S = 50
CMONEY_POLL_INTERVAL_S = 5

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(DATA_DIR, exist_ok=True)
LOG_PATH = os.path.join(DATA_DIR, "cmoney_vs_kgi_test.csv")
log_lock = threading.Lock()


def log_row(source, price, extra=""):
    now = datetime.now().isoformat(timespec="milliseconds")
    with log_lock:
        with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([now, source, price, extra])
    print(f"{now} [{source}] price={price} {extra}", flush=True)


# cmkey rotates (confirmed: yesterday's hardcoded value returned {"Error":-3,
# "Message":"金鑰不正確"} today) — fetch a fresh one from the page itself at
# startup instead of hardcoding it, using a cookiejar-backed opener since the
# key may be tied to the session cookie set on that same page load.
_cookie_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookie_jar))
_HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch_cmkey(code):
    page_url = f"https://www.cmoney.tw/finance/warrantsquery.aspx?warrant={code}"
    req = urllib.request.Request(page_url, headers=_HEADERS)
    with _opener.open(req, timeout=10) as resp:
        html = resp.read().decode("utf-8", errors="ignore")
    m = re.search(r"class='primary-navi-now'>.*?cmkey='([^']+)'", html, re.DOTALL)
    if not m:
        raise RuntimeError("could not find cmkey on warrantsquery.aspx page")
    return m.group(1)


def cmoney_loop(stop_event):
    try:
        cmkey = fetch_cmkey(TEST_CODE)
    except Exception as e:
        log_row("CMONEY", "ERROR", f"fetch_cmkey failed: {e}")
        return
    # cmkey is base64-like (contains +, /, =) and MUST be percent-encoded —
    # an unescaped '+' in a URL query string is interpreted as a literal
    # space by the server, which silently corrupts the key ("金鑰不正確").
    url = (f"https://www.cmoney.tw/finance/ashx/mainpage.ashx"
           f"?action=GetWarrantData&cmkey={urllib.parse.quote(cmkey, safe='')}&commKey={TEST_CODE}")
    headers = dict(_HEADERS, Referer=f"https://www.cmoney.tw/finance/warrantsquery.aspx?warrant={TEST_CODE}")
    while not stop_event.is_set():
        try:
            req = urllib.request.Request(url, headers=headers)
            with _opener.open(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("Error"):
                log_row("CMONEY", "ERROR", data.get("Message"))
                stop_event.wait(CMONEY_POLL_INTERVAL_S)
                continue
            w = data["Warrant"]
            log_row("CMONEY", w["SalePr"], f"trade_time={w['SaleTe']}")
        except Exception as e:
            log_row("CMONEY", "ERROR", str(e))
        stop_event.wait(CMONEY_POLL_INTERVAL_S)


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


def on_status(sender, status, msg):
    try:
        if status in (COM_STATUS.LOGIN_READY, COM_STATUS.LOGIN_FAIL):
            login_ready.set()
    except Exception:
        pass


def on_message(sender, pkg):
    try:
        name = dt_name(int(pkg.DT))
        if name == "QUOTE_LAST_PRICE_STOCK" and str(pkg.StockNo).strip() == TEST_CODE:
            log_row("KGI_POLL", str(pkg.LastMatchPrice))
    except Exception:
        pass


def kgi_loop(stop_event):
    global quoteCom
    quoteCom = QuoteCom("", 443, SID, TOKEN)
    quoteCom.OnGetStatus += on_status
    quoteCom.OnRcvMessage += on_message
    quoteCom.Connect2Quote("quoteapi.kgi.com.tw", 443, USER_ID, PASSWORD, ' ', "")
    if not login_ready.wait(timeout=20):
        log_row("KGI_POLL", "ERROR", "login timeout")
        return
    time.sleep(2)
    while not stop_event.is_set():
        try:
            quoteCom.RetriveLastPriceStock(TEST_CODE)
        except Exception as e:
            log_row("KGI_POLL", "ERROR", str(e))
        stop_event.wait(KGI_POLL_INTERVAL_S)


if __name__ == "__main__":
    with open(LOG_PATH, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["timestamp", "source", "price", "extra"])

    print(f"Testing code {TEST_CODE}: CMONEY every {CMONEY_POLL_INTERVAL_S}s, "
          f"KGI_POLL every {KGI_POLL_INTERVAL_S}s. Ctrl+C to stop.", flush=True)

    stop_event = threading.Event()
    threading.Thread(target=cmoney_loop, args=(stop_event,), daemon=True).start()
    threading.Thread(target=kgi_loop, args=(stop_event,), daemon=True).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_event.set()
        print("Stopped.")
