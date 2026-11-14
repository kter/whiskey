#!/usr/bin/env python3
"""Manage one loopback-only moto process; state and logs live in ignored .cache/."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".cache" / "moto"
PID = STATE / "server.pid"
LOG = STATE / "server.log"


def identity(pid: int) -> str:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart=", "-o", "args="],
        capture_output=True, text=True, check=False,
    )
    return result.stdout.strip()


def ready() -> bool:
    try:
        with urlopen("http://127.0.0.1:5000/moto-api/", timeout=1) as response:
            return response.status == 200
    except OSError:
        return False


def main() -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / "server.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(PID.read_text()) if PID.exists() else None
        owned = state and identity(state["pid"]) == state["identity"]
        if sys.argv[1] == "stop":
            if owned:
                os.kill(state["pid"], signal.SIGTERM)
                for _ in range(100):
                    if identity(state["pid"]) != state["identity"] or not ready():
                        break
                    time.sleep(0.1)
                else:
                    raise RuntimeError("moto did not stop; inspect " + str(LOG))
            PID.unlink(missing_ok=True)
            print("moto stopped (in-memory data is discarded)")
            return
        if owned:
            if not ready():
                raise RuntimeError("tracked moto is not responding; inspect " + str(LOG))
            print("moto already running at http://127.0.0.1:5000")
            return
        # Refuse to reuse or terminate a service that we did not start.
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", 5000))
        with LOG.open("ab") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "moto.server", "-H", "127.0.0.1", "-p", "5000"],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                start_new_session=True,
            )
        PID.write_text(json.dumps({"pid": process.pid, "identity": identity(process.pid)}))
        for _ in range(300):
            if process.poll() is not None:
                PID.unlink(missing_ok=True)
                raise RuntimeError("moto exited; inspect " + str(LOG))
            if ready():
                print("moto ready at http://127.0.0.1:5000")
                return
            time.sleep(0.1)
        process.terminate()
        process.wait(timeout=5)
        PID.unlink(missing_ok=True)
        raise RuntimeError("moto startup timed out; inspect " + str(LOG))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        sys.exit(f"ERROR: {exc}")
