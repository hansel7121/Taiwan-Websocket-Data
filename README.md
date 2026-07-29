# Taiwan-Websocket-Data

Python scripts for live Taiwan market data (stocks, warrants) via KGI's QuoteCom API, plus order execution via TradeCom.

## Scripts

- `testing.py` / `test.py` — live tick + candle plot for a single stock. Method: `SubQuotesMatch`.
- `tradetest.py` — places real buy/sell orders. Method: `TradeCom.SendOrder`.
- `warrant-liveprices.py` — live bid/ask table + tick log for every warrant on an underlying stock. Three interchangeable strategies (`STRATEGY` switch in the file):
  - `FULL_BATCH` — `SubQuotesMatch` + `SubQuotesDepth` on every code at once.
  - `ROTATION` — event-driven rotation across a fixed number of subscription slots.
  - `POLLING` — round-robin `RetriveLastPriceStock` queries, no subscription limit.
