import os
import sys
import time
import traceback
from datetime import datetime

sys.path.append("/app")

import clr  # noqa: E402

clr.AddReference("System.Text.Encoding.CodePages")
from System.Text import Encoding, CodePagesEncodingProvider  # noqa: E402
Encoding.RegisterProvider(CodePagesEncodingProvider.Instance)

clr.AddReference("Package")
clr.AddReference("PushClient")
clr.AddReference("QuoteCom")
clr.AddReference("Interop.KGICGCAPIATLLib")
from Intelligence import PushClient, QuoteCom, COM_STATUS, DT  # noqa: E402

TOKEN = os.environ["KGI_TOKEN"]  # KGI-issued QuoteCom API token, not your login password
SID = os.environ.get("KGI_SID", "API")
USER_ID = os.environ["KGI_USER_ID"]
PASSWORD = os.environ["KGI_PASSWORD"]
HOST = os.environ.get("KGI_QUOTE_HOST", "iquotetest.kgi.com.tw")
PORT = int(os.environ.get("KGI_QUOTE_PORT", "8000"))
STOCK_CODE = os.environ.get("PROBE_STOCK_CODE", "2330")
DURATION_SEC = int(os.environ.get("PROBE_DURATION_SEC", "90"))

status_counts = {}
message_counts = {}


def log(msg):
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


def on_status(sender, status, msg):
    name = str(status)
    status_counts[name] = status_counts.get(name, 0) + 1
    try:
        smsg = bytes(msg).decode("UTF-8", "strict")
    except Exception:
        smsg = repr(msg)
    log(f"STATUS {name}: {smsg}")


def on_message(sender, pkg):
    dt_name = str(pkg.DT)
    message_counts[dt_name] = message_counts.get(dt_name, 0) + 1
    if pkg.DT in (DT.QUOTE_STOCK_MATCH1, DT.QUOTE_STOCK_MATCH2):
        log(f"MATCH {pkg.StockNo}: price={pkg.Match_Price} qty={pkg.Match_Qty} total={pkg.Total_Qty}")
    else:
        log(f"MESSAGE DT={dt_name}")


def main():
    log(f"Connecting: host={HOST} port={PORT} sid={SID} stock={STOCK_CODE} duration={DURATION_SEC}s")

    quote_com = QuoteCom("", 443, SID, TOKEN)
    quote_com.OnRcvMessage += on_message
    quote_com.OnGetStatus += on_status

    quote_com.Connect2Quote(HOST, PORT, USER_ID, PASSWORD, " ", "")

    log("Connect2Quote called, waiting for LOGIN_READY / LOGIN_FAIL...")
    deadline = time.time() + 20
    while time.time() < deadline:
        if "COM_STATUS.LOGIN_READY" in status_counts:
            break
        if "COM_STATUS.LOGIN_FAIL" in status_counts or "COM_STATUS.LOGIN_UNKNOW" in status_counts:
            log("Login failed — aborting probe.")
            quote_com.Dispose()
            sys.exit(1)
        time.sleep(0.5)
    else:
        log("Timed out waiting for login status — aborting probe.")
        quote_com.Dispose()
        sys.exit(1)

    log(f"Subscribing to {STOCK_CODE} (match + depth)...")
    log(f"SubQuotesMatch: {quote_com.SubQuotesMatch(STOCK_CODE)}")
    log(f"SubQuotesDepth: {quote_com.SubQuotesDepth(STOCK_CODE)}")

    log(f"Listening for {DURATION_SEC}s — watching for MATCH/MESSAGE lines above...")
    time.sleep(DURATION_SEC)

    quote_com.UnSubQuotesMatch(STOCK_CODE)
    quote_com.UnSubQuotesDepth(STOCK_CODE)
    quote_com.Logout()
    time.sleep(2)
    quote_com.Dispose()

    log("=== SUMMARY ===")
    log(f"Status events: {status_counts}")
    log(f"Message events: {message_counts}")

    if not message_counts:
        log("NO DATA RECEIVED — login/connect worked but no ticks came through the callback. "
            "This is the specific failure mode to worry about (Mono event marshaling).")
        sys.exit(2)

    log("Ticks were received via the callback — quote path works in this container.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("UNHANDLED EXCEPTION:")
        traceback.print_exc()
        sys.exit(1)
