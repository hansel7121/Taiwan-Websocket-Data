# Running the live KGI connection test in Docker

This checks whether the KGI QuoteCom SDK works the same way inside a Linux
Docker container (what production on Hetzner will look like) as it does
running directly on your machine. You'll need your real KGI credentials for
this — nothing here places trades, it only subscribes to live quotes.

Do this during trading hours: TWSE 09:00–13:30, TAIFEX 08:45–13:45,
Asia/Taipei time.

## 1. Install Docker Desktop

- Go to https://www.docker.com/products/docker-desktop/ and download it for
  your OS (Mac or Windows).
- Install it, then open the Docker Desktop app and wait until it says it's
  running (whale icon in the menu bar / system tray, no longer animating).
- No account needed for what we're doing here.

## 2. Get the test files

You should have (or will receive from Ian) a `docker/linux-test/` folder
containing:
- `Dockerfile.coreclr`
- `probe.py`
- `live_probe.py`

Drop this folder into your existing local clone of `Taiwan-Websocket-Data`,
at the repo root, so the layout looks like:

```
Taiwan-Websocket-Data/
├── docker/
│   └── linux-test/
│       ├── Dockerfile.coreclr
│       ├── probe.py
│       └── live_probe.py
├── QuoteComExamplePy/
├── TradeComExamplePy/
└── ...
```

## 3. Open a terminal in the repo folder

- **Mac:** open Terminal, then `cd` into the repo folder (drag the folder
  into the Terminal window after typing `cd ` to auto-fill the path).
- **Windows:** open PowerShell, same idea (`cd` into the folder).

## 4. Build the image

Run this once (takes a few minutes the first time):

```
docker build --platform linux/amd64 -f docker/linux-test/Dockerfile.coreclr -t kgi-linux-test .
```

`--platform linux/amd64` matters — it makes the test match the actual Linux
server type this will run on (Hetzner), even if you're on a Mac.

If it ends with `naming to docker.io/library/kgi-linux-test done`, it worked.

## 5. Set your credentials (do NOT commit or share this file)

Create a plain text file named `.env.live-test` in the repo root with:

```
KGI_TOKEN=your_quotecom_api_token
KGI_SID=API
KGI_USER_ID=your_kgi_user_id
KGI_PASSWORD=your_kgi_password
KGI_QUOTE_HOST=iquotetest.kgi.com.tw
KGI_QUOTE_PORT=8000
PROBE_STOCK_CODE=2330
PROBE_DURATION_SEC=90
```

Use the same values you already use in your working local setup's `.env`
file for `KGI_TOKEN` / `KGI_USER_ID` / `KGI_PASSWORD`. Leave the other lines
as-is unless Ian tells you otherwise — `KGI_QUOTE_HOST` in particular should
match whatever host your normal (non-Docker) setup connects to.

## 6. Run the test

```
docker run --rm --platform linux/amd64 --env-file .env.live-test kgi-linux-test python3 live_probe.py
```

This will:
- Connect and log in
- Subscribe to one stock (2330 / TSMC by default)
- Print every tick it receives for 90 seconds
- Print a summary, then exit

## 7. What to look for

**Working correctly** looks like this:

```
[...] Connecting: host=... port=8000 ...
[...] STATUS COM_STATUS.LOGIN_READY: ...
[...] Subscribing to 2330 (match + depth)...
[...] SubQuotesMatch: 0
[...] SubQuotesDepth: 0
[...] Listening for 90s — watching for MATCH/MESSAGE lines above...
[...] MATCH 2330: price=... qty=... total=...
[...] MATCH 2330: price=... qty=... total=...
   (more MATCH/MESSAGE lines as ticks come in)
[...] === SUMMARY ===
[...] Status events: {...}
[...] Message events: {...}
[...] Ticks were received via the callback — quote path works in this container.
```

**Problem signs to send back to Ian, with the full terminal output:**

- `STATUS COM_STATUS.LOGIN_FAIL` or `LOGIN_UNKNOW` — login itself failed
  (could be wrong credentials, or the host/port needs adjusting).
- The process prints `Timed out waiting for login status` — never heard
  back from the server at all (could be a network/firewall issue specific
  to Docker's networking).
- It runs through login and subscribe fine, but **no `MATCH` or `MESSAGE`
  lines ever print**, and the summary says `NO DATA RECEIVED` — this is the
  specific failure we're checking for (whether Docker's networking somehow
  blocks the incoming tick data even though the connection succeeded).
- Any line containing `Traceback` or `UNHANDLED EXCEPTION` or a native
  crash dump (`Native Crash Reporting`, `SIGABRT`) — copy the whole output.

Either way — success or failure — copy everything the terminal printed and
send it back. Even a full success is useful to confirm.

## 8. Clean up afterward

```
docker rm -f $(docker ps -aq --filter ancestor=kgi-linux-test) 2>/dev/null
```

(Harmless if nothing matches — this SDK sometimes leaves a background
thread running after the script finishes, which can keep the container
from exiting on its own.)
