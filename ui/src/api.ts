// Types and fetchers for the lab's API (src/agentlab/server.py). The shapes mirror its pydantic
// response models; FastAPI also documents them at http://127.0.0.1:8000/docs.

export type CheckResult = {
  type: string;
  passed: boolean;
  category: string | null;
  detail: string;
  cost_usd: number | null;
};

export type EvalSummary = {
  eval_run_id: string;
  task_id: string;
  passed: boolean;
  failure_category: string | null;
  checks: CheckResult[];
};

export type RunSummary = {
  id: string;
  agent_name: string;
  model: string | null;
  status: string;
  task_id: string | null;
  started_at: string;
  duration_s: number | null;
  rate_limit_wait_s: number;
  message: string;
  answer: string | null;
  error: string | null;
  tokens: number;
  cost_usd: number | null;
  parent_run_id: string | null;
  mode: "record" | "replay" | "fork";
  fork_id: string | null;
  fork_override: Override | null;
  replay_report: ReplayReport | null;
  eval: EvalSummary | null;
};

export type ReplayReport = {
  identical: boolean;
  spans_compared: number;
  differences: string[];
  unused_recordings: number;
  fallbacks: Record<string, number>;
  error: string | null;
};

export type ReplayResponse = {
  run_id: string;
  identical: boolean;
  summary: string;
  differences: string[];
};

export type SpanKind = "agent" | "step" | "llm" | "tool";

export type Span = {
  id: string;
  parent_span_id: string | null;
  seq: number;
  kind: SpanKind;
  name: string;
  status: "ok" | "error";
  started_at: string;
  duration_ms: number;
  input: unknown;
  output: any;
  error: string | null;
  attributes: Record<string, any>;
  input_tokens: number;
  output_tokens: number;
  thinking_tokens: number;
  cost_usd: number | null;
};

export type RunDetail = {
  run: RunSummary;
  spans: Span[];
  replays: RunSummary[];
  forks: ForkInfo[];
};

export type Override = { system_prompt?: string; model?: string; tool_output?: unknown };

export type ForkRunResult = {
  run_id: string;
  status: string;
  answer: string | null;
  error: string | null;
  passed: boolean | null;
  category: string | null;
};

export type ForkGroup = { n: number; passed: number | null; runs: ForkRunResult[] };

export type ForkSummary = {
  label: string;
  override: Override;
  scored: boolean;
  fork: ForkGroup;
  control: ForkGroup | null;
  p_value: number | null;
  verdict: string;
};

export type ForkInfo = {
  id: string;
  source_run_id: string;
  span_id: string;
  label: string;
  override: Override | null;
  n: number;
  control: boolean;
  status: "queued" | "running" | "done" | "error";
  worker: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  summary: ForkSummary | null;
  error: string | null;
};

export type ForkDetail = { fork: ForkInfo; source: RunSummary; runs: RunSummary[] };

export type FamilyNode = {
  run: RunSummary;
  replays: RunSummary[];
  forks: { fork: ForkInfo; runs: FamilyNode[] }[];
};

export type DiffStep = {
  index: number;
  span_id: string;
  kind: "tools" | "answer" | "error";
  label: string;
  calls: { name: string; args: Record<string, unknown>; output: unknown; error: string | null }[];
  text: string | null;
  error: string | null;
  tokens: number;
  cost_usd: number | null;
  attempts: number;
  replayed: boolean;
};

export type DiffRow = {
  status: "same" | "changed" | "added" | "removed";
  a: DiffStep | null;
  b: DiffStep | null;
  similarity: number;
  notes: string[];
};

export type DiffSide = {
  run_id: string;
  agent: string;
  model: string | null;
  mode: string;
  status: string;
  passed: boolean | null;
  category: string | null;
  steps: number;
  tokens: number;
  cost_usd: number | null;
  duration_s: number | null;
  answer: string | null;
};

export type DiffResult = {
  a: DiffSide;
  b: DiffSide;
  a_run: RunSummary;
  b_run: RunSummary;
  rows: DiffRow[];
  divergence: { row: number; a_step: number | null; b_step: number | null; summary: string } | null;
  answer_diff: { op: "equal" | "insert" | "delete"; text: string }[];
  answer_similarity: number;
  effects: string[];
};

export type ForkRequest = {
  run_id: string;
  span_id: string;
  override: Override;
  n: number;
  control: boolean;
};

export type Recording = { kind: string; request_hash: string; request: any; response: any };

export type Metrics = {
  tasks: number;
  passed: number;
  success_rate: number | null;
  latency_p50_s: number | null;
  latency_p95_s: number | null;
  rate_limit_wait_s?: number;
  cost_per_task_usd: number | null;
  total_cost_usd: number | null;
  judge_cost_usd: number | null;
  tokens_per_task: number | null;
  failure_categories: Record<string, number>;
  by_agent: Record<string, { tasks: number; passed: number }>;
};

export type EvalRun = {
  id: string;
  datasets: string[];
  model: string;
  judge_model: string | null;
  status: string;
  task_count: number;
  started_at: string;
  ended_at: string | null;
  metrics: Metrics | null;
};

export type EvalDetail = { eval: EvalRun; runs: RunSummary[] };

async function get<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `${response.status} ${response.statusText}`);
  }
  return response.json();
}

export const api = {
  runs: (params: { status?: string; agent?: string; task_id?: string } = {}) => {
    const query = new URLSearchParams({ limit: "200" });
    if (params.status) query.set("status", params.status);
    if (params.agent) query.set("agent", params.agent);
    if (params.task_id) query.set("task_id", params.task_id);
    return get<RunSummary[]>(`/api/runs?${query}`);
  },
  run: (id: string) => get<RunDetail>(`/api/runs/${id}`),
  replay: (id: string) => get<ReplayResponse>(`/api/runs/${id}/replay`, { method: "POST" }),
  family: (id: string) => get<FamilyNode>(`/api/runs/${id}/family`),
  fork: (id: string) => get<ForkDetail>(`/api/forks/${id}`),
  createFork: (request: ForkRequest) =>
    get<ForkInfo>("/api/forks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }),
  models: () => get<Record<string, string>>("/api/models"),
  diff: (a: string, b: string) =>
    get<DiffResult>(`/api/diff?${new URLSearchParams({ a, b })}`),
  recordings: (spanId: string) => get<Recording[]>(`/api/spans/${spanId}/recordings`),
  evals: () => get<EvalRun[]>("/api/evals"),
  eval: (id: string) => get<EvalDetail>(`/api/evals/${id}`),
  failureCategories: () => get<Record<string, string>>("/api/failure-categories"),
};
