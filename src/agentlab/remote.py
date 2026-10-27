"""`RemoteStore`: the trace store, reached over HTTP. It is how traces get to a lab server.

It has the same method names as `Store`, for the methods that tracing, replay, forks, scoring and
the worker use. So `lab.init("http://lab:8000")` sends a customer's runs to a lab server, and a
`lab worker --server http://lab:8000` started in the customer's repo can claim fork jobs and send
the fork runs back. Nothing else in the code knows the store is remote.

Each call is one POST to `/api/store/<method>` with JSON arguments. Rows travel as JSON
(`model_dump(mode="json")`) and are validated back into rows on the other side. If the server sets
`AGENTLAB_TOKEN`, every request must carry it as a bearer token.
"""

import os
from typing import Any

import httpx

from agentlab.store import EvalResultRow, ForkRow, RecordingRow, RunRow, SpanRow


class RemoteStore:
    def __init__(self, url: str, *, token: str | None = None, client: httpx.Client | None = None):
        token = token or os.environ.get("AGENTLAB_TOKEN")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.client = client or httpx.Client(base_url=url.rstrip("/"), timeout=30)
        self.client.headers.update(headers)

    def _call(self, method: str, **args: Any) -> Any:
        response = self.client.post(f"/api/store/{method}", json=args)
        response.raise_for_status()
        return response.json()

    # Writes made while tracing a run

    def create_run(self, **fields: Any) -> str:
        return self._call("create_run", **fields)

    def finish_run(self, run_id: str, *, status: str, output: Any, error: str | None) -> None:
        self._call("finish_run", run_id=run_id, status=status, output=output, error=error)

    def save_span(self, span: SpanRow, recordings: list[RecordingRow]) -> None:
        self._call(
            "save_span",
            span=span.model_dump(mode="json"),
            recordings=[r.model_dump(mode="json") for r in recordings],
        )

    def set_replay_report(self, run_id: str, report: Any) -> None:
        self._call("set_replay_report", run_id=run_id, report=report)

    def save_eval_result(self, result: EvalResultRow) -> None:
        self._call("save_eval_result", result=result.model_dump(mode="json"))

    # Reads a replay or fork needs

    def get_run(self, run_id: str) -> RunRow | None:
        row = self._call("get_run", run_id=run_id)
        return RunRow.model_validate(row) if row else None

    def spans(self, run_id: str) -> list[SpanRow]:
        return [SpanRow.model_validate(r) for r in self._call("spans", run_id=run_id)]

    def run_recordings(self, run_id: str) -> list[RecordingRow]:
        return [RecordingRow.model_validate(r) for r in self._call("run_recordings", run_id=run_id)]

    # The fork job queue

    def claim_fork(self, agent_names: list[str], worker: str) -> ForkRow | None:
        row = self._call("claim_fork", agent_names=agent_names, worker=worker)
        return ForkRow.model_validate(row) if row else None

    def get_fork(self, fork_id: str) -> ForkRow | None:
        row = self._call("get_fork", fork_id=fork_id)
        return ForkRow.model_validate(row) if row else None

    def finish_fork(self, fork_id: str, *, summary: Any = None, error: str | None = None) -> None:
        self._call("finish_fork", fork_id=fork_id, summary=summary, error=error)
