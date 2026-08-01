# Taiwan-Websocket-Data

Python scripts for live Taiwan market data (stocks, warrants, TAIFEX options) via KGI's QuoteCom API, plus order execution via TradeCom.

## Layout

```
.
├── kgi_config.py                       shared credential loader (all scripts import this)
├── warrant-liveprices.py               live bid/ask + tick log GUI for every warrant on an underlying
├── warrant_orderbook_collector.py      tick-by-tick 5-level depth + trades recorder, top-25 liquid warrants
├── warrant_orderbook_supervisor.py     crash/hang-resistant launcher for the warrant collector — run this, not the collector directly
├── options_orderbook_collector.py      same as the warrant collector, for TSMC (CDO) stock options
├── options_orderbook_supervisor.py     launcher for the options collector — run this, not the collector directly
├── data/                               all CSV/log/state output lands here (gitignored heartbeat/marker files aside)
├── to_test/                            one-off / exploratory / not-yet-production-verified scripts (see below)
├── QuoteComExamplePy/                  vendor SDK + docs (quotes)
└── TradeComExamplePy/                  vendor SDK + docs (order execution)
```

## Production scripts (root)

- **`warrant-liveprices.py`** — live bid/ask table + tick log for every warrant on an underlying stock. Three interchangeable strategies (`STRATEGY` switch in the file):
  - `FULL_BATCH` — `SubQuotesMatch` + `SubQuotesDepth` on every code at once.
  - `ROTATION` — event-driven rotation across a fixed number of subscription slots.
  - `POLLING` — round-robin `RetriveLastPriceStock` queries, no subscription limit.
  - `HYBRID` (active) — push-subscribes the Qnum=25 codes currently trading fastest, polls the rest.
- **`warrant_orderbook_collector.py` / `_supervisor.py`** — records full 5-level order book depth + every trade for the day's 25 most liquid TSMC warrants (ranked via a live warm-up, since KGI's warrant master data has no volume field) to `data/warrant_depth_<date>.csv` / `data/warrant_trades_<date>.csv`, written incrementally so a crash never loses data. Run the supervisor; it restarts the collector on crash/hang and won't restart once the collector reports done for the day.
- **`options_orderbook_collector.py` / `_supervisor.py`** — same idea for TSMC stock options (TAIFEX comid `CDO`), to `data/options_depth_<date>.csv` / `data/options_trades_<date>.csv`. Ranks the day's top 25 by real volume from TAIFEX's own public REST API (no live warm-up needed, unlike warrants). TAIFEX day-session hours (08:45–13:45), not TWSE's.

## `to_test/` — scripts that are NOT production-verified

These either place real orders, answer a one-off research question, or predate the current architecture. Review before running:

- `test.py` / `testing.py` — early single-stock tick + candle plot scripts (`SubQuotesMatch`).
- `tradetest.py` — **places real buy/sell orders** via `TradeCom.SendOrder`. Treat any change to it, or any request to run it, as live-trading-risk.
- `test_cmoney_vs_kgi.py` — compares cmoney.tw's public warrant-quote endpoint against KGI's poll-tier latency.
- `test_taifex_vs_kgi_options.py` — compares TAIFEX's own public options-quote REST API against KGI's native push, for one auto-picked liquid CDO contract. Not yet run during real market hours.
- `finmind.py` — unrelated one-off: pulls historical TSMC tick data from the FinMind API.

Scripts in this folder import `kgi_config` from the project root via an explicit `sys.path` fixup, and write any CSV output to `../data/`.

## `data/`

Everything the scripts read or write at runtime: debug logs, per-day state/CSV output from the collectors, and test-script results. Two large historical order-book captures (`orderbook_0050_...csv`, `orderbook_2317_...csv`) live here too.
