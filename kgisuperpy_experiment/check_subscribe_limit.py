import os
from dotenv import load_dotenv
import kgisuperpy

# ── What this does ───────────────────────────────────────────────────────────
# Logs into kgisuperpy and asks its own API what your account's real
# subscription limits are, per exchange, rather than guessing/testing
# empirically. See marketdata/starwave/starwave_api.py in the installed
# package for the underlying calls this uses.
#
# Known ahead of time (read directly from the installed package's source,
# marketdata/starwave/sw_subscription_rule.py — no login needed to see this):
#   TAIFEX  -> whitelist ["TXF*"] only. TSMC options (CDO*) and even index
#              options (TXO*) do NOT match this pattern, so this account (or
#              ANY kgisuperpy account) cannot subscribe to options through
#              this library at all, regardless of tier/entitlement. Only
#              TAIEX index FUTURES (TXF) are reachable here.
#   TWSE/OTC -> whitelist ["*"], fully open. This is where the real open
#              question is: how many TOTAL symbols can this account hold
#              subscribed at once (the equivalent of the Qnum=25 cap
#              observed on the older QuoteCom-based path this project
#              otherwise uses)?
#
# Requires your OWN kgisuperpy credentials in a .env file next to this
# script (see .env.example) — these are your personal login (person_id /
# person_pwd), NOT the same TOKEN/SID pair in the project's kgi_config.py.
# kgisuperpy is a separate product requiring its own KGI application.

load_dotenv()

PERSON_ID = os.environ["KGISUPERPY_PERSON_ID"]
PERSON_PWD = os.environ["KGISUPERPY_PERSON_PWD"]
SIMULATION = os.environ.get("KGISUPERPY_SIMULATION", "true").lower() != "false"

print(f"Logging in (simulation={SIMULATION})...")
api = kgisuperpy.login(PERSON_ID, PERSON_PWD, simulation=SIMULATION)

# The Quote/StarWave adapter is reached via api's quote-related attributes;
# exact attribute name may need adjusting once this actually runs and you
# can inspect `dir(api)` — this project never got past the Smart App
# Control block below to confirm the live object graph.
quote = getattr(api, "Quote", None) or getattr(api, "quote", None)
if quote is None:
    print("Could not find the Quote/StarWave object on the login instance — "
          "run `print(dir(api))` and adjust this script.")
else:
    for exchange in ("TWSE", "OTC", "TAIFEX", "TWSEOdd", "OTCOdd"):
        try:
            limited = quote.is_subscribe_limited()
            has_limit = quote.has_subscribe_limit(exchange)
            limit = quote.get_subscribe_limit(exchange)
            print(f"{exchange}: account_has_any_limit={limited}, "
                  f"this_exchange_has_limit={has_limit}, limit={limit} "
                  f"({'unlimited' if limit == -1 else 'symbols'})")
        except Exception as e:
            print(f"{exchange}: query failed — {e!r}")
