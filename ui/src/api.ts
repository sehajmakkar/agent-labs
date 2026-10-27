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
  eval: EvalSummary | null;
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

export type RunDetail = { run: RunSummary; spans: Span[] };

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

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `${response.status} ${response.statusText}`);
  }
  return response.json();
}

export const api = {
  runs: (params: { status?: string; agent?: string } = {}) => {
    const query = new URLSearchParams({ limit: "200" });
    if (params.status) query.set("status", params.status);
    if (params.agent) query.set("agent", params.agent);
    return get<RunSummary[]>(`/api/runs?${query}`);
  },
  run: (id: string) => get<RunDetail>(`/api/runs/${id}`),
  recordings: (spanId: string) => get<Recording[]>(`/api/spans/${spanId}/recordings`),
  evals: () => get<EvalRun[]>("/api/evals"),
  eval: (id: string) => get<EvalDetail>(`/api/evals/${id}`),
  failureCategories: () => get<Record<string, string>>("/api/failure-categories"),
};
