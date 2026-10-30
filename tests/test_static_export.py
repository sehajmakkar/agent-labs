import json
import tarfile

import pytest
from test_fork import AGENT, FIXED_PROMPT, TASK, record_source, smart_genai, step_span

from agentlab.fork.runner import execute_fork
from agentlab.static_export import export_static, pack


def read(out, name):
    return json.loads((out / f"{name}.json").read_text())


def finished_fork(store, source) -> str:
    fork_id = store.create_fork(
        source_run_id=source,
        span_id=step_span(store, source, 3).id,
        label="step 3",
        override={"system_prompt": FIXED_PROMPT},
        n=2,
        control=True,
    )
    llm, _ = smart_genai()
    summary = execute_fork(
        store, store.get_fork(fork_id), llm=llm, agents={"shop": AGENT}, tasks={TASK.id: TASK}
    )
    store.finish_fork(fork_id, summary=summary)  # what the worker does after running it
    return fork_id


def test_every_page_the_ui_links_to_is_exported(store, tmp_path):
    source = record_source()
    fork_id = finished_fork(store, source)
    out = tmp_path / "data"

    stats = export_static(store, out, presets_file=None)

    assert stats.missing == []
    runs = read(out, "runs")
    assert source in {r["id"] for r in runs} and len(runs) == 5  # the source, 2 forks, 2 controls
    detail = read(out, f"runs/{source}")
    assert detail["run"]["id"] == source and detail["forks"][0]["id"] == fork_id
    assert read(out, f"forks/{fork_id}")["fork"]["summary"]["fork"]["passed"] == 2
    model_call = next(s for s in detail["spans"] if s["kind"] == "llm")
    assert read(out, f"spans/{model_call['id']}/recordings")[0]["kind"] == "llm"
    assert read(out, f"runs/{source}/family")["run"]["id"] == source


def test_diffs_are_exported_for_the_pairs_the_ui_links_and_listed(store, tmp_path):
    source = record_source()
    fork_id = finished_fork(store, source)
    out = tmp_path / "data"

    export_static(store, out, presets_file=None)

    child = store.fork_runs(fork_id)[0].id
    pairs = set(read(out, "diffs"))
    assert {f"{source}/{child}", f"{child}/{source}"} <= pairs  # each run and its source, both ways
    assert read(out, f"diff/{source}/{child}")["a"]["run_id"] == source


def test_the_static_config_runs_nothing_and_offers_presets(store, tmp_path):
    source = record_source()
    fork_id = finished_fork(store, source)
    presets = tmp_path / "presets.json"
    entry = {"fork_id": fork_id[:8], "title": "Fix", "change": "Adds a rule"}
    presets.write_text(json.dumps([entry]))
    out = tmp_path / "data"

    export_static(store, out, presets_file=presets)

    config = read(out, "config")
    assert config["static"] is True
    nothing_runs = {"replay": False, "fork": "preset", "blame": False, "lock_in": False}
    assert config["actions"] == nothing_runs
    (preset,) = read(out, "presets")
    assert (preset["fork_id"], preset["run_id"], preset["passed"], preset["label"]) == (
        fork_id,
        source,
        2,
        "step 3",
    )


def test_an_unfinished_preset_is_refused(store, tmp_path):
    source = record_source()
    fork_id = store.create_fork(
        source_run_id=source,
        span_id=step_span(store, source, 3).id,
        label="step 3",
        override={"system_prompt": FIXED_PROMPT},
        n=2,
        control=True,
    )
    presets = tmp_path / "presets.json"
    presets.write_text(json.dumps([{"fork_id": fork_id, "title": "Fix", "change": "Adds a rule"}]))

    with pytest.raises(ValueError, match="hasn't finished"):
        export_static(store, tmp_path / "data", presets_file=presets)


def test_export_refuses_anything_that_looks_like_a_key(store, tmp_path):
    record_source()
    with store.engine.begin() as db:
        db.exec_driver_sql(
            'UPDATE runs SET input = \'{"message": "key AIzaSyA-1234567890abcdefghijklmnop"}\''
        )

    with pytest.raises(ValueError, match="API key"):
        export_static(store, tmp_path / "data", presets_file=None)


def test_the_export_packs_into_one_reproducible_archive(store, tmp_path):
    record_source()
    out = tmp_path / "data"
    export_static(store, out, presets_file=None)

    first = pack(out, tmp_path / "a.tar.gz")
    second = pack(out, tmp_path / "b.tar.gz")

    assert first == second
    assert (tmp_path / "a.tar.gz").read_bytes() == (tmp_path / "b.tar.gz").read_bytes()
    with tarfile.open(tmp_path / "a.tar.gz") as tar:
        names = tar.getnames()
    assert "data/runs.json" in names and "data/config.json" in names
