# kgisuperpy experiment (isolated — does not affect the rest of this repo)

Investigates `kgisuperpy` (the official KGI Securities Python package, separate from the
raw pythonnet + QuoteCom/TradeCom .NET DLL approach the rest of this project uses) to
answer: does it support TSMC options, and what's the real subscription limit for stocks?

## Setup

- Needs Python 3.9–3.13 (64-bit). The rest of this repo is pinned to 3.7, so this folder
  has its own venv: `py -3.11 -m venv venv`, installed via `venv\Scripts\python.exe -m pip install kgisuperpy`.
- `kgisuperpy 2.1.0` (latest on PyPI as of 2026-08-04) pulls in `pandas`, `numba`, and its
  own bundled compiled (Cython) modules.
- Copy `.env.example` to `.env` and fill in your **kgisuperpy** credentials
  (`person_id`/`person_pwd` — your personal KGI login, requires its own separate API
  application/CA cert per KGI's docs). This is NOT the same as the project's
  `kgi_config.py` (that's for the older QuoteCom/TradeCom system).

## Status as of 2026-08-04: blocked by Windows Smart App Control, not by anything fixable in code

This machine has **Smart App Control** enabled (confirmed via
`HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy` → `VerifiedAndReputablePolicyState = 1`,
i.e. enforcement mode). It blocks any native DLL/PYD that doesn't have an established
reputation with Microsoft. This hit three separate times while just trying to `import
kgisuperpy`:

1. `pandas`'s compiled Cython extensions (brand-new `pandas 3.0.5` at time of testing) —
   worked around by pinning `pandas==2.2.3`, an older/more-established release.
2. `numba`'s compiled extension (a dependency of kgisuperpy's *backtest* module, which
   loads unconditionally even though we only care about live quotes) — worked around by
   pinning `numba==0.59.1` + `numpy<2.1`.
3. `kgisuperpy`'s **own bundled compiled module** (`data/_data.pyx` → `_data_url`) — **not
   fixable by picking a different version**, since this is the package's own code, not a
   swappable dependency. This is where investigation stopped.

Smart App Control has no per-file "allow" exception for regular users (unlike enterprise
WDAC) — the only ways past it are: wait for Microsoft's reputation system to pick the file
up on its own, or turn Smart App Control off entirely, which Microsoft deliberately makes
irreversible without a clean Windows reinstall. **Neither of those is something to do
without you deciding first** — this is a security-relevant, hard-to-reverse system change,
not a coding fix.

## What was still learned without ever logging in (from reading the installed source directly)

- `kgisuperpy` is built on the **same underlying KGI infrastructure** this project already
  uses in places — `pushClient/pyTradeCom.py` and `CA.py`'s `TradeCom` class confirm the
  *trading* side reuses the legacy TradeCom .NET plumbing. The *quote* side, though, uses a
  newer, separate native library called **"StarWave"** (`marketdata/starwave/`), accessed
  via `ctypes`, not pythonnet.
- **`marketdata/starwave/sw_subscription_rule.py` is a hardcoded client-side symbol
  whitelist, readable with zero login required:**
  ```python
  subscription_rules = {
      "TAIFEX":  {"mode": "whitelist", "whitelist": ["TXF*"]},   # index FUTURES only
      "ES":      {"mode": "whitelist", "whitelist": ["*"]},
      "TWSE":    {"mode": "whitelist", "whitelist": ["*"]},
      "OTC":     {"mode": "whitelist", "whitelist": ["*"]},
      "TWSEOdd": {"mode": "whitelist", "whitelist": ["*"]},
      "OTCOdd":  {"mode": "whitelist", "whitelist": ["*"]},
  }
  ```
  **This settles the options question definitively**: `CDO*` (TSMC options) and even
  `TXO*` (index options) don't match `TXF*`. kgisuperpy cannot subscribe to ANY options
  contract, on any account/tier — this is a hard client-side filter, not an entitlement
  you could unlock. Matches what the official docs already implied (only 台股/美股/國內期貨
  listed, options never mentioned) — now confirmed at the code level.
- For stocks/warrants (TWSE/OTC), there's no symbol restriction (`"*"` wildcard). The real
  open question — your account's actual numeric subscription cap — is answered by a
  different, genuinely live API: `starwave_api.py` exposes `is_subscribe_limited()`,
  `has_subscribe_limit(exchange)`, and `get_subscribe_limit(exchange)` (returns an int, or
  `-1` for unlimited) on the quote adapter object. **This requires an actual successful
  login** — it's account-specific, not something visible from static source. `check_subscribe_limit.py`
  in this folder is written to call it, but has never actually run given the blocker above.
- KGI's public documentation (separately, at `superpy.kgieworld.com.tw/kgipythonapi/faq`)
  lists three account tiers with very different caps than the `Qnum=25` this project has
  been designing around: 新星 (2 connections × 30 symbols), 菁英 (3 × 50), 尊爵 (7 × 100).
  Whether any of those apply to this specific account is unconfirmed — could be a genuinely
  higher cap, or could be its own separate 0/unregistered state since kgisuperpy needs its
  own application process.

## Next steps if this is worth pursuing further

1. Decide whether you want to touch Smart App Control at all (reinstall-to-re-enable cost
   is real) — or just run `check_subscribe_limit.py` from a different machine/VM without it
   enabled.
2. You'll need real kgisuperpy credentials (`person_id`/`person_pwd`) — check whether you
   already went through KGI's separate SuperPy API application process; if not, that's a
   prerequisite regardless of the Smart App Control issue.
3. Once logged in successfully, `dir(api)` will reveal the exact attribute path to the
   Quote/StarWave object (`check_subscribe_limit.py` guesses `api.Quote`/`api.quote` — this
   was never confirmed live) — adjust the script accordingly, then it'll print your real
   TWSE/OTC subscription limit directly.
