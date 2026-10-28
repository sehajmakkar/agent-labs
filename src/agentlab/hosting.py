"""Hosting the lab for other people to see: which actions are open, and the guards on the rest.

Locally everything is allowed. When `AGENTLAB_PUBLIC=1`:
- reading (runs, trees, evals, diffs, blames, the accuracy chart) is open to everyone;
- **replay** is open too: it calls no model and no tool, so it costs nothing;
- **fork** and **blame** spend the lab's Gemini key, so they need the demo key
  (`AGENTLAB_DEMO_KEY`, sent as the `X-Demo-Key` header), are capped per hour, and N is limited;
- **lock-in** (writes a dataset file) and the **store RPC** (writes runs) are switched off, unless
  `AGENTLAB_TOKEN` is set for a trusted worker.
"""

import gzip
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
from collections import deque
from pathlib import Path

from fastapi import HTTPException, Request

MAX_PUBLIC_N = 3  # runs per fork or blame verification, when hosted


def is_public() -> bool:
    return os.environ.get("AGENTLAB_PUBLIC") == "1"


def demo_key_set() -> bool:
    return bool(os.environ.get("AGENTLAB_DEMO_KEY"))


def public_config() -> dict:
    public = is_public()
    return {
        "public": public,
        "actions": {
            "replay": True,
            "fork": "key" if public else True,
            "blame": "key" if public else True,
            "lock_in": not public,
        },
        "max_n": MAX_PUBLIC_N if public else 20,
        "repo": os.environ.get("AGENTLAB_REPO_URL", "https://github.com/sehajmakkar/agent-labs"),
    }


class HourlyCap:
    """At most `limit` paid jobs (forks or blames) per rolling hour, across all visitors."""

    def __init__(self, limit: int):
        self.limit = limit
        self._times: deque[float] = deque()
        self._lock = threading.Lock()

    def take(self) -> bool:
        with self._lock:
            now = time.monotonic()
            while self._times and now - self._times[0] > 3600:
                self._times.popleft()
            if len(self._times) >= self.limit:
                return False
            self._times.append(now)
            return True


PAID_JOBS = HourlyCap(int(os.environ.get("AGENTLAB_JOBS_PER_HOUR", "6")))


def guard_paid_job(request: Request, n: int) -> None:
    """Raise unless this fork or blame may run here. Locally, always allowed."""
    if not is_public():
        return
    key = os.environ.get("AGENTLAB_DEMO_KEY")
    if not key or request.headers.get("X-Demo-Key") != key:
        raise HTTPException(403, "Forks and blames spend real model calls: they need a demo key")
    if n > MAX_PUBLIC_N:
        raise HTTPException(400, f"On the hosted demo, N is at most {MAX_PUBLIC_N}")
    if not PAID_JOBS.take():
        raise HTTPException(429, "The hourly limit for forks and blames is reached; try later")


def guard_local_only(what: str) -> None:
    if is_public():
        raise HTTPException(403, f"{what} is switched off on the hosted demo: run the lab locally")


SECRET_PATTERN = re.compile(r"AIza[0-9A-Za-z_\-]{20,}|x-goog-api-key")


def snapshot(db_path: str | Path, out: str | Path) -> int:
    """A consistent, gzipped copy of the trace store, to seed a hosted lab. Returns its size.

    `VACUUM INTO` copies the database including what is still in the write-ahead log, while the
    lab may be running. Before writing, the copy is scanned for anything that looks like a Google
    API key: the snapshot is published, so it must hold demo data only.
    """
    out = Path(out)
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "lab.db"
        with sqlite3.connect(db_path) as db:
            db.execute(f"VACUUM INTO '{copy}'")
        with sqlite3.connect(copy) as db:
            for table, column in (
                ("recordings", "request"),
                ("recordings", "response"),
                ("spans", "input"),
                ("spans", "output"),
                ("runs", "input"),
            ):
                for (value,) in db.execute(f"SELECT {column} FROM {table}"):
                    if value and SECRET_PATTERN.search(str(value)):
                        raise ValueError(
                            f"Refusing to snapshot: {table}.{column} looks like it holds an API key"
                        )
        out.parent.mkdir(parents=True, exist_ok=True)
        with copy.open("rb") as src, gzip.open(out, "wb", compresslevel=9) as dst:
            shutil.copyfileobj(src, dst)
    return out.stat().st_size
