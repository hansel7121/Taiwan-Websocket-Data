import os
import signal
import subprocess
import sys
import time
from datetime import datetime, time as dtime

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# ── What this is ─────────────────────────────────────────────────────────────
# Same design as warrant_orderbook_supervisor.py — see that file's header
# comment for the full rationale. In short: options_orderbook_collector.py
# uses pythonnet, which has a confirmed hard native crash mode
# (AccessViolationException, seen in this project's own test.py) that no
# Python try/except can catch. This supervisor never imports clr/pythonnet,
# so it can watch the collector from outside and restart it no matter how it
# dies, including that crash class. It also detects hangs via a heartbeat
# file, not just crashes.

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COLLECTOR_SCRIPT = os.path.join(SCRIPT_DIR, "options_orderbook_collector.py")
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
TODAY = datetime.now().strftime("%Y%m%d")

# Must match the collector's own DATA_DIR paths exactly — this is how the
# supervisor observes the collector's heartbeat/done-marker from outside.
HEARTBEAT_PATH = os.path.join(DATA_DIR, "options_heartbeat.txt")
DONE_MARKER_PATH = os.path.join(DATA_DIR, f"options_done_{TODAY}.marker")
SUPERVISOR_LOG_PATH = os.path.join(DATA_DIR, f"options_supervisor_{TODAY}.log")

HEARTBEAT_STALE_AFTER_S = 60     # collector heartbeats every 15s; 4x margin
POLL_INTERVAL_S = 5              # how often the supervisor checks in
MAX_RESTARTS_PER_DAY = 20
RESTART_BACKOFF_SCHEDULE_S = [5, 10, 20, 30, 60, 120]   # caps at the last value
# TAIFEX stock-options day session closes 13:45 (not TWSE's 13:30) — give an
# hour's buffer past that, same margin the warrant supervisor uses.
HARD_STOP_AFTER = dtime(14, 45)


def log(msg):
    line = f"{datetime.now().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    try:
        with open(SUPERVISOR_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def heartbeat_age_s():
    try:
        return time.time() - os.path.getmtime(HEARTBEAT_PATH)
    except OSError:
        return None   # heartbeat file doesn't exist yet (e.g. just started)


def done_for_today():
    return os.path.exists(DONE_MARKER_PATH)


def read_done_reason():
    try:
        with open(DONE_MARKER_PATH, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "(marker present, reason unreadable)"


def launch_collector():
    log(f"Launching collector: py -u {COLLECTOR_SCRIPT}")
    # New process group so a forced kill takes any children with it too, and
    # so Ctrl+C on this supervisor doesn't also directly interrupt the child
    # before we get a chance to decide what to do about it.
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    return subprocess.Popen(
        ["py", "-u", COLLECTOR_SCRIPT],
        cwd=SCRIPT_DIR,
        creationflags=creationflags,
    )


def kill_process(proc):
    try:
        proc.kill()
        proc.wait(timeout=10)
    except Exception:
        log("kill_process: failed to confirm termination, continuing anyway")


def graceful_stop(proc):
    """Ask the collector to shut down cleanly (so it writes its own 'done'
    marker and unsubscribes/disposes properly) rather than yanking it. Used
    when the SUPERVISOR itself is being asked to stop (Ctrl+C) — without
    this, interrupting the supervisor would leave an orphaned collector
    process running in the background with nothing left to manage it."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.terminate()
        proc.wait(timeout=15)
        log("Collector shut down gracefully")
    except Exception:
        log("Collector didn't respond to graceful stop in time — killing it")
        kill_process(proc)


def supervise_one_run():
    """Launch the collector and watch it until it exits or is killed for
    being stuck. Returns True if it's done for the day (stop supervising),
    False if it should be restarted. Propagates KeyboardInterrupt after
    gracefully stopping the child, so the caller knows to stop entirely."""
    proc = launch_collector()
    start = time.time()

    try:
        while True:
            exit_code = proc.poll()
            if exit_code is not None:
                log(f"Collector exited on its own (code={exit_code}) after {time.time()-start:.0f}s")
                break

            if done_for_today():
                # Collector may still be tearing down (writing the marker
                # happens slightly before process exit) — give it a moment,
                # then move on regardless; either it exits cleanly or we
                # treat it as done and stop caring about its exit code.
                log("Done-for-today marker appeared while collector still running "
                    "— waiting briefly for it to finish exiting on its own")
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    log("Collector didn't exit on its own after marker appeared — killing it")
                    kill_process(proc)
                return True

            age = heartbeat_age_s()
            if age is not None and age > HEARTBEAT_STALE_AFTER_S:
                log(f"Heartbeat stale ({age:.0f}s > {HEARTBEAT_STALE_AFTER_S}s) "
                    f"while process still running — treating as hung, killing it")
                kill_process(proc)
                break

            if datetime.now().time() > HARD_STOP_AFTER:
                log(f"Past hard-stop time ({HARD_STOP_AFTER}) with no done marker — "
                    f"killing collector and giving up for today regardless")
                kill_process(proc)
                return True

            time.sleep(POLL_INTERVAL_S)
    except KeyboardInterrupt:
        log("Supervisor interrupted (Ctrl+C) — asking collector to stop gracefully")
        graceful_stop(proc)
        raise

    if done_for_today():
        log(f"Done marker present: {read_done_reason()}")
        return True
    return False


def main():
    log("=" * 70)
    log(f"Supervisor starting for {TODAY}")
    log("=" * 70)

    if done_for_today():
        log(f"Already marked done for today ({read_done_reason()}) — nothing to do.")
        return

    restarts = 0
    while True:
        done = supervise_one_run()
        if done:
            log("Collector finished for the day. Supervisor exiting.")
            return

        restarts += 1
        if restarts > MAX_RESTARTS_PER_DAY:
            log(f"Hit MAX_RESTARTS_PER_DAY ({MAX_RESTARTS_PER_DAY}) without the "
                f"collector ever completing cleanly — giving up. Something is "
                f"persistently broken (check {SUPERVISOR_LOG_PATH} and "
                f"data/options_orderbook_debug.log) and needs a human, not another "
                f"automatic restart.")
            return

        backoff = RESTART_BACKOFF_SCHEDULE_S[min(restarts - 1, len(RESTART_BACKOFF_SCHEDULE_S) - 1)]
        log(f"Restart #{restarts}/{MAX_RESTARTS_PER_DAY} — waiting {backoff}s before relaunching")
        time.sleep(backoff)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Supervisor interrupted by user (Ctrl+C) — exiting without restarting collector")
        sys.exit(0)
