import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
import threading
import time
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from collections import deque, OrderedDict
from datetime import datetime

# ── Data storage ─────────────────────────────────────────────────
prices  = deque(maxlen=5000)
times   = deque(maxlen=5000)
candles = OrderedDict()
lock    = threading.Lock()
Y_MIN   = 2200
Y_MAX   = 2600

# ── Candle update helper ──────────────────────────────────────────
def update_candle(price, time_str):
    minute = time_str[:5]  # "HH:MM"
    with lock:
        prices.append(price)
        times.append(time_str)
        if minute not in candles:
            candles[minute] = {"open": price, "high": price, "low": price, "close": price}
        else:
            candles[minute]["high"]  = max(candles[minute]["high"], price)
            candles[minute]["low"]   = min(candles[minute]["low"],  price)
            candles[minute]["close"] = price

# ── QuoteCom setup ────────────────────────────────────────────────
import clr
assembly_path = r"C:\Users\user\OneDrive\Desktop\websocket\Taiwan-Websocket-Data\QuoteComExamplePy"
sys.path.append(assembly_path)
clr.AddReference("Package")
clr.AddReference("PushClient")
clr.AddReference("QuoteCom")
from Intelligence import QuoteCom, COM_STATUS, DT

from kgi_config import TOKEN, SID, USER_ID, PASSWORD

def onQuoteGetStatus(sender, status, msg):
    if status == COM_STATUS.LOGIN_READY:
        print("✅ Login successful")
    elif status == COM_STATUS.LOGIN_FAIL:
        print("❌ Login failed")
    elif status == COM_STATUS.CONNECT_READY:
        print("✅ Connected")

def onQuoteRcvMessage(sender, pkg):
    if pkg.DT == int(DT.QUOTE_STOCK_MATCH1) or pkg.DT == int(DT.QUOTE_STOCK_MATCH2):
        if str(pkg.StockNo).strip() == "2317":
            price = float(str(pkg.Match_Price))
            raw_t = str(pkg.Match_Time)
            # parse HHMMSS
            raw_t = str(pkg.Match_Time).zfill(9)  # zfill FIRST
            t_fmt = f"{int(raw_t[0:2])}:{raw_t[2:4]}:{raw_t[4:6]}"
            print(f"[callback] raw Match_Time={repr(t_fmt)}, price={price}")
            update_candle(price, t_fmt)

quoteCom = QuoteCom("", 443, SID, TOKEN)
quoteCom.OnGetStatus += onQuoteGetStatus
quoteCom.OnRcvMessage += onQuoteRcvMessage
print("Connecting to API...")
quoteCom.Connect2Quote("quoteapi.kgi.com.tw", 443, USER_ID, PASSWORD, ' ', "")
time.sleep(3)

quoteCom.SubQuotesMatch("2317")
print("📡 Subscribed to 2317 live data")

# ── Plot setup ────────────────────────────────────────────────────
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 7),
                                gridspec_kw={"height_ratios": [3, 1]})
fig.patch.set_facecolor("#0d1117")
for ax in (ax1, ax2):
    ax.set_facecolor("#0d1117")
    ax.tick_params(colors="#888888", labelsize=7)
    ax.spines[:].set_color("#222222")

def animate(i):
    with lock:
        p = list(prices)
        t = list(times)
        c = dict(candles)

    # ── Top: raw tick line chart ──────────────────────────────────
    ax1.clear()
    ax1.set_facecolor("#0d1117")
    ax1.spines[:].set_color("#222222")
    ax1.tick_params(colors="#888888", labelsize=7)

    if len(p) >= 2:
        padding = max((max(p) - min(p)) * 0.1, 1)
        ax1.set_ylim(min(p) - padding, max(p) + padding)
        color = "#00ff88" if p[-1] >= p[0] else "#ff4444"
        ax1.plot(range(len(p)), p, color=color, linewidth=1.2)
        ax1.fill_between(range(len(p)), p, min(p) - padding, alpha=0.1, color=color)
        ax1.set_title(
            f"2317 TSMC  |  Last: {p[-1]:.1f}  "
            f"{'▲' if p[-1] >= p[0] else '▼'} {abs(p[-1]-p[0]):.1f}",
            color="white", fontsize=13, pad=10
        )
        step = max(1, len(t) // 8)
        ax1.set_xticks(range(0, len(t), step))
        ax1.set_xticklabels(t[::step], rotation=30, ha="right", fontsize=6, color="#888888")
    else:
        ax1.set_title("2317 TSMC  |  Waiting for data...", color="#555555", fontsize=13)

    # ── Bottom: 1-min close line ──────────────────────────────────
    ax2.clear()
    ax2.set_facecolor("#0d1117")
    ax2.spines[:].set_color("#222222")
    ax2.tick_params(colors="#888888", labelsize=7)

    if len(c) >= 2:
        mins    = list(c.keys())
        closes  = [c[m]["close"] for m in mins]
        padding2 = max((max(closes) - min(closes)) * 0.1, 1)
        ax2.set_ylim(min(closes) - padding2, max(closes) + padding2)
        color2  = "#00ff88" if closes[-1] >= closes[0] else "#ff4444"
        ax2.plot(range(len(closes)), closes, color=color2, linewidth=1.2, marker="o", markersize=2)
        ax2.set_title("1-Min Candle Close", color="#666666", fontsize=8, pad=4)
        step2 = max(1, len(mins) // 8)
        ax2.set_xticks(range(0, len(mins), step2))
        ax2.set_xticklabels(mins[::step2], rotation=30, ha="right", fontsize=6, color="#888888")

fig.tight_layout(pad=1.5)
ani = animation.FuncAnimation(fig, animate, interval=100, cache_frame_data=False)
plt.show()