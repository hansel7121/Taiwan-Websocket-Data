import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
import threading
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from collections import deque
from datetime import datetime

# ── QuoteCom setup ──────────────────────────────────────────────
import clr
assembly_path = r"C:\Users\user\Desktop\websocket\Taiwan-Websocket-Data\QuoteComExamplePy"
sys.path.append(assembly_path)

clr.AddReference("Package")
clr.AddReference("PushClient")
clr.AddReference("QuoteCom")
from Intelligence import QuoteCom, COM_STATUS, DT

from kgi_config import TOKEN, SID, USER_ID, PASSWORD

# ── Data storage ─────────────────────────────────────────────────
prices = deque(maxlen=200)
times  = deque(maxlen=200)
lock   = threading.Lock()

# ── QuoteCom callbacks ───────────────────────────────────────────
def onQuoteGetStatus(sender, status, msg):
    if status == COM_STATUS.LOGIN_READY:
        print("✅ Login successful")
    elif status == COM_STATUS.LOGIN_FAIL:
        print("❌ Login failed")
    elif status == COM_STATUS.CONNECT_READY:
        print("✅ Connected")

def onQuoteRcvMessage(sender, pkg):
    if pkg.DT in (DT.QUOTE_STOCK_MATCH1, DT.QUOTE_STOCK_MATCH2):
        if str(pkg.StockNo).strip() == "2330":
            with lock:
                prices.append(float(str(pkg.Match_Price)))
                times.append(datetime.now().strftime("%H:%M:%S"))

# ── Initialize QuoteCom ──────────────────────────────────────────
quoteCom = QuoteCom("", 443, SID, TOKEN)
quoteCom.OnRcvMessage += onQuoteRcvMessage
quoteCom.OnGetStatus  += onQuoteGetStatus

# ── Login ────────────────────────────────────────────────────────
print("Connecting...")
quoteCom.Connect2Quote("quoteapi.kgi.com.tw", 443, USER_ID, PASSWORD, ' ', "")
# ── Live plot ────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(12, 5))
fig.patch.set_facecolor("#0d1117")
ax.set_facecolor("#0d1117")

def animate(i):
    with lock:
        p = list(prices)
        t = list(times)

    ax.clear()
    ax.set_facecolor("#0d1117")

    if len(p) >= 2:
        color = "#00ff88" if p[-1] >= p[0] else "#ff4444"
        ax.plot(t, p, color=color, linewidth=1.5)
        ax.fill_between(range(len(p)), p, min(p), alpha=0.15, color=color)
        ax.set_title(f"2330 TSMC  |  Last: {p[-1]:.1f}",
                     color="white", fontsize=14, pad=12)
    else:
        ax.set_title("2330 TSMC  |  Waiting for data...",
                     color="#888888", fontsize=14, pad=12)

    ax.tick_params(colors="#888888", labelsize=7)
    ax.spines[:].set_color("#333333")
    ax.yaxis.label.set_color("white")

    # show every Nth x-label to avoid crowding
    step = max(1, len(t) // 10)
    ax.set_xticks(range(0, len(t), step))
    ax.set_xticklabels(t[::step], rotation=45, ha="right")

    fig.tight_layout()

ani = animation.FuncAnimation(fig, animate, interval=1000)
plt.show()
