"""The read-only demo: the API's answers saved as JSON files, so the UI runs with no server (D-057).

`lab export-static` asks the real API, in-process through FastAPI's test client, for everything
the UI can show, and writes each answer where the static build of the UI looks for it:

    /api/runs/<id>              ->  <out>/runs/<id>.json
    /api/runs/<id>/family       ->  <out>/runs/<id>/family.json
    /api/diff?a=<a>&b=<b>       ->  <out>/diff/<a>/<b>.json
    /api/runs?...               ->  <out>/runs.json      (every run; the UI filters it)

Nothing new is computed for the export: each file is the JSON `lab ui` would have served. What
would start work (fork, blame, replay, lock-in) is off in the static build, with one exception:
**preset forks**, forks run ahead of time and listed in `deploy/presets.json`. The fork dialog
offers them in place of a live fork and says they were run beforehand.

A diff exists for every pair of runs, so only the pairs the UI links to are exported: each run
against its source, and the original runs of the same task against each other. `diffs.json`
lists them, so "Compare with" offers only those.

The files are packed into one archive, `ui/static-data.tar.gz`, which is what git keeps (D-058):
thousands of small JSON files would make every refresh a commit touching thousands of files. The
static build (`npm run build:static`) unpacks it before building.
"""

import gzip
import io
import json
import shutil
import tarfile
import warnings
from dataclasses import dataclass, field
from itertools import permutations
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

with warnings.catch_warnings():  # Starlette nags about httpx on import; it works fine here
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

from agentlab.hosting import SECRET_PATTERN, public_config
from agentlab.server import create_app
from agentlab.store import Store

PRESETS_FILE = Path("deploy/presets.json")
ARCHIVE = Path("ui/static-data.tar.gz")


@dataclass
class ExportStats:
    files: int = 0
    bytes: int = 0
    runs: int = 0
    diffs: int = 0
    presets: int = 0
    missing: list[str] = field(default_factory=list)  # links the UI has that the API can't answer


def static_config() -> dict[str, Any]:
    """The config the static build serves: nothing runs, forks come from the presets."""
    config = public_config()
    config["public"] = True
    config["static"] = True
    config["actions"] = {"replay": False, "fork": "preset", "blame": False, "lock_in": False}
    config["max_n"] = 0
    return config


def export_static(
    store: Store, out: str | Path, *, presets_file: str | Path | None = PRESETS_FILE
) -> ExportStats:
    """Write every page's data under `out`, replacing what was there. Refuses to write secrets."""
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    client = TestClient(create_app(store, ui_dist=None))
    stats = ExportStats()

    def get(path: str, optional: bool = False) -> Any:
        response = client.get(path)
        if response.status_code != 200:
            if not optional:
                stats.missing.append(path)
            return None
        return response.json()

    def write(name: str, data: Any) -> None:
        if data is None:  # the API had no answer; `missing` says which
            return
        text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
        if SECRET_PATTERN.search(text):
            raise ValueError(f"Refusing to export {name}: it looks like it holds an API key")
        path = out / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        stats.files += 1
        stats.bytes += len(text.encode())

    # Runs: the list, each run's page and family, and the recordings of its model and tool calls.
    runs = get("/api/runs?limit=1000000") or []
    write("runs", runs)
    stats.runs = len(runs)
    fork_ids: set[str] = set()
    blame_ids: set[str] = set()
    for run in runs:
        detail = get(f"/api/runs/{run['id']}")
        if detail is None:
            continue
        write(f"runs/{run['id']}", detail)
        write(f"runs/{run['id']}/family", get(f"/api/runs/{run['id']}/family"))
        for span in detail["spans"]:
            if span["kind"] in ("llm", "tool"):
                write(f"spans/{span['id']}/recordings", get(f"/api/spans/{span['id']}/recordings"))
        fork_ids.update(f["id"] for f in detail["forks"])
        blame_ids.update(b["id"] for b in detail["blames"])
        if run["fork_id"]:
            fork_ids.add(run["fork_id"])

    # The blame accuracy page links to the blame of every verified case.
    bench = get("/api/benchmarks/blame", optional=True)  # only once `lab blame-bench` has run
    if bench is not None:
        write("benchmarks/blame", bench)
        verification = bench["results"].get("verification") or {}
        blame_ids.update(c["blame_id"] for c in verification.get("cases_detail", []))

    for blame_id in sorted(blame_ids):
        detail = get(f"/api/blames/{blame_id}")
        if detail is None:
            continue
        write(f"blames/{blame_id}", detail)
        for candidate in (detail["blame"]["report"] or {}).get("candidates", []):
            check = candidate.get("verification") or {}
            fork_ids.update(f for f in (check.get("fork_id"), check.get("later_fork_id")) if f)

    for fork_id in sorted(fork_ids):
        detail = get(f"/api/forks/{fork_id}")
        if detail is not None:
            write(f"forks/{fork_id}", detail)

    evals = get("/api/evals") or []
    write("evals", evals)
    for eval_run in evals:
        write(f"evals/{eval_run['id']}", get(f"/api/evals/{eval_run['id']}"))

    showcase = get("/api/showcase")
    write("showcase", showcase)
    write("failure-categories", get("/api/failure-categories"))
    write("models", get("/api/models"))
    write("config", static_config())

    pairs = _diff_pairs(runs, showcase)
    for a, b in sorted(pairs):
        result = get("/api/diff?" + urlencode({"a": a, "b": b}))
        if result is not None:
            write(f"diff/{a}/{b}", result)
            stats.diffs += 1
    write("diffs", sorted(f"{a}/{b}" for a, b in pairs))

    presets = _presets(store, presets_file)
    write("presets", presets)
    stats.presets = len(presets)
    return stats


def _diff_pairs(runs: list[dict], showcase: dict | None) -> set[tuple[str, str]]:
    """The run pairs the UI links to, both ways round (the diff page has a Swap button)."""
    pairs: set[tuple[str, str]] = set()
    ids = {r["id"] for r in runs}
    for run in runs:
        if run["parent_run_id"] in ids:
            pairs |= {(run["parent_run_id"], run["id"]), (run["id"], run["parent_run_id"])}
    by_task: dict[str, list[str]] = {}
    for run in runs:
        # Original runs of the same task ("Compare with"); seeded-bug runs are hidden in the UI.
        if run["mode"] == "record" and run["task_id"] and "~" not in run["agent_name"]:
            by_task.setdefault(run["task_id"], []).append(run["id"])
    for same_task in by_task.values():
        pairs |= set(permutations(same_task, 2))
    if showcase and showcase.get("diff"):
        a, b = showcase["diff"]["a"], showcase["diff"]["b"]
        pairs |= {(a, b), (b, a)}
    return pairs


def _presets(store: Store, presets_file: str | Path | None) -> list[dict]:
    """The preset forks, with what the fork dialog needs to offer them. Each must be finished."""
    if presets_file is None or not Path(presets_file).exists():
        return []
    presets = []
    for entry in json.loads(Path(presets_file).read_text()):
        fork = store.find_fork(entry["fork_id"])
        if fork.status != "done" or not fork.summary:
            raise ValueError(f"Preset fork {fork.id[:8]} hasn't finished ({fork.status})")
        summary = fork.summary
        presets.append(
            {
                "fork_id": fork.id,
                "run_id": fork.source_run_id,
                "span_id": fork.span_id,
                "label": fork.label,
                "title": entry["title"],
                "change": entry["change"],
                "n": fork.n,
                "passed": summary["fork"]["passed"],
                "control_passed": (summary["control"] or {}).get("passed"),
                "p_value": summary["p_value"],
                "verdict": summary["verdict"],
                "created_at": fork.created_at.isoformat(),
            }
        )
    return presets


def pack(out: str | Path, archive: str | Path = ARCHIVE) -> int:
    """Pack the exported folder into one .tar.gz (as `data/...`). Returns its size.

    The archive is reproducible: files in sorted order with fixed times and owners, and neither a
    time nor a file name in the gzip header. Exporting the same data twice gives the same bytes,
    so git sees no change.
    """
    out, archive = Path(out), Path(archive)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for path in sorted(p for p in out.rglob("*") if p.is_file()):
            info = tarfile.TarInfo(f"data/{path.relative_to(out).as_posix()}")
            data = path.read_bytes()
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            tar.addfile(info, io.BytesIO(data))
    archive.parent.mkdir(parents=True, exist_ok=True)
    with archive.open("wb") as f, gzip.GzipFile(filename="", fileobj=f, mode="wb", mtime=0) as gz:
        gz.write(buffer.getvalue())
    return archive.stat().st_size
