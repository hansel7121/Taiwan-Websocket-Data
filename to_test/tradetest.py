import time
import sys
import os
sys.path.append(r"C:\Users\user\OneDrive\Desktop\websocket\Taiwan-Websocket-Data\TradeComExamplePy")  # adjust to where tradecomPy.py is
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root, for kgi_config
import tradecomPy
import threading
from System import UInt16

from kgi_config import BROKER_ID, ACCOUNT

STOCK_ID  = "5880"
QTY       = 1
BUY_PRICE = "0"          # set a limit price e.g. "22.85", or use pflag=4 for market
SELL_PRICE = "0"         # same as above

def buy():
    print(f"[BUY] Sending order: {QTY} shares of {STOCK_ID}...")
    result = tradecomPy.SendOrder(
        brokerid = BROKER_ID,
        account  = ACCOUNT,
        stockid  = STOCK_ID,
        otype    = "O",   # new order
        oLot     = "0",   # round lot
        oclass   = "0",   # 現股
        pflag    = "4",   # market price
        bs       = "B",   # buy
        qty      = QTY,
        prz      = "0",   # price (ignored for market order)
        agend    = " ",
        orderno  = " ",
        tif      = "R"    # ROD
    )
    if result:
        print(f"[BUY] Order sent successfully for {QTY} shares of {STOCK_ID}")
    else:
        print(f"[BUY] Order failed!")
    return result

def sell():
    print(f"[SELL] Sending order: {QTY} shares of {STOCK_ID}...")
    result = tradecomPy.SendOrder(
        brokerid = BROKER_ID,
        account  = ACCOUNT,
        stockid  = STOCK_ID,
        otype    = "O",   # new order
        oLot     = "0",   # round lot
        oclass   = "0",   # 現股
        pflag    = "4",   # market price
        bs       = "S",   # sell
        qty      = QTY,
        prz      = "0",
        agend    = " ",
        orderno  = " ",
        tif      = "R"
    )
    if result:
        print(f"[SELL] Order sent successfully for {QTY} shares of {STOCK_ID}")
    else:
        print(f"[SELL] Order failed!")
    return result

# ── Patch onTradeRcvMessage to print fill info ────────────────────
original_handler = tradecomPy.onTradeRcvMessage

def patched_handler(sender, pkg):
    from Intelligence import DT
    if pkg.DT == int(DT.SECU_ORDER_ACK) or pkg.DT == int(DT.SECU_ORDER_ACK_N):
        print(f"[ACK] Order acknowledged - CNT={pkg.CNT}, RequestId={pkg.RequestId}")
    elif pkg.DT == int(DT.SECU_ORDER_RPT):
        if pkg.ErrCode != 0:
            print(f"[RPT] ❌ Order REJECTED - ErrCode={pkg.ErrCode}, ErrMsg={pkg.ErrMsg}")
        else:
            print(f"[RPT] ✅ Order accepted - OrderNo={pkg.OrderNo}, Side={pkg.Side}, Qty={pkg.AfterQty}, Price={pkg.Price}")
    elif pkg.DT == int(DT.SECU_DEAL_RPT):
        side = "BOUGHT" if str(pkg.Side) == "B" else "SOLD"
        print(f"[FILL] ✅ {side} {pkg.DealQty} shares of {pkg.StockID} @ {pkg.Price}")
    else:
        print(f"[MSG] DT={pkg.DT}")
    original_handler(sender, pkg)

# ── Main ──────────────────────────────────────────────────────────
tradecomPy.initialize()
tradecomPy.tradeCom.OnRcvMessage -= tradecomPy.onTradeRcvMessage
tradecomPy.tradeCom.OnRcvMessage += patched_handler

print("[INIT] Connecting...")
from System import UInt16
tradecomPy.tradeCom.Connect("itrade.kgi.com.tw", UInt16(8000), 5000)
time.sleep(3)

from kgi_config import USER_ID, PASSWORD
tradecomPy.tradeCom.AutoSubReportSecurity = True
tradecomPy.tradeCom.AutoRecoverReportSecurity = True
tradecomPy.tradeCom.Login(USER_ID, PASSWORD, ' ')
time.sleep(3)

print("[MAIN] Starting buy...")
if buy():
    print(f"[MAIN] Waiting 5 minutes before selling...")
    for remaining in range(300, 0, -1):
        mins, secs = divmod(remaining, 60)
        print(f"[WAIT] Selling in {mins:01d}:{secs:02d}...", end="\r")
        time.sleep(1)
    print()
    print(f"[MAIN] 5 minutes elapsed, selling now...")
    sell()
print("[MAIN] Done. Press Ctrl+C to exit.")
input()
tradecomPy.tradeCom.Dispose()