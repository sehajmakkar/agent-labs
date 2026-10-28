import gzip
import sqlite3

import pytest
from fastapi.testclient import TestClient
from test_fork import FIXED_PROMPT, record_source, step_span

from agentlab import hosting
from agentlab.hosting import HourlyCap, snapshot
from agentlab.server import create_app


@pytest.fixture
def public(monkeypatch):
    monkeypatch.setenv("AGENTLAB_PUBLIC", "1")
    monkeypatch.setenv("AGENTLAB_DEMO_KEY", "letmein")
    monkeypatch.setattr(hosting, "PAID_JOBS", HourlyCap(2))


def fork_request(store, source, n=2):
    return {
        "run_id": source,
        "span_id": step_span(store, source, 3).id,
        "override": {"system_prompt": FIXED_PROMPT},
        "n": n,
        "control": True,
    }


def test_locally_everything_is_allowed(store):
    client = TestClient(create_app(store, ui_dist=None))
    config = client.get("/api/config").json()
    assert config["public"] is False and config["actions"]["fork"] is True


def test_hosted_reads_and_replays_are_open_but_paid_jobs_need_the_key(store, public):
    source = record_source()
    client = TestClient(create_app(store, ui_dist=None))

    config = client.get("/api/config").json()
    assert (config["public"], config["actions"]["fork"], config["actions"]["lock_in"]) == (
        True,
        "key",
        False,
    )
    assert client.get(f"/api/runs/{source}").status_code == 200

    no_key = client.post("/api/forks", json=fork_request(store, source))
    assert no_key.status_code == 403
    keyed = client.post(
        "/api/forks", json=fork_request(store, source), headers={"X-Demo-Key": "letmein"}
    )
    assert keyed.status_code == 200
    too_big = client.post(
        "/api/forks", json=fork_request(store, source, n=5), headers={"X-Demo-Key": "letmein"}
    )
    assert too_big.status_code == 400


def test_the_hourly_cap_stops_runaway_spending(store, public):
    source = record_source()
    client = TestClient(create_app(store, ui_dist=None))
    headers = {"X-Demo-Key": "letmein"}
    codes = [
        client.post("/api/forks", json=fork_request(store, source), headers=headers).status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]


def test_writes_that_only_make_sense_locally_are_off(store, public):
    source = record_source()
    client = TestClient(create_app(store, ui_dist=None))
    assert client.post("/api/regressions", json={"run_id": source}).status_code == 403
    assert client.post("/api/store/get_run", json={"run_id": source}).status_code == 403


def test_a_token_still_lets_a_trusted_worker_use_the_store(store, public, monkeypatch):
    monkeypatch.setenv("AGENTLAB_TOKEN", "worker-secret")
    client = TestClient(create_app(store, ui_dist=None))
    ok = client.post(
        "/api/store/get_run",
        json={"run_id": "x"},
        headers={"Authorization": "Bearer worker-secret"},
    )
    assert ok.status_code == 200


def test_snapshot_copies_the_store_and_refuses_secrets(store, tmp_path):
    record_source()
    out = tmp_path / "seed.db.gz"
    assert snapshot(store.engine.url.database, out) > 0
    restored = tmp_path / "restored.db"
    restored.write_bytes(gzip.decompress(out.read_bytes()))
    with sqlite3.connect(restored) as db:
        assert db.execute("SELECT count(*) FROM runs").fetchone()[0] == 1
        db.execute(
            'UPDATE runs SET input = \'{"message": "key AIzaSyA-1234567890abcdefghijklmnop"}\''
        )
    with pytest.raises(ValueError, match="API key"):
        snapshot(restored, tmp_path / "again.db.gz")
