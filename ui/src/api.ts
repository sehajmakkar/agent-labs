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
  blames: BlameInfo[];
};

export type Verification = {
  step: number;
  fork_id: string;
  n: number;
  passed: number;
  control_passed: number;
  p_value: number | null;
  status: "confirmed" | "rejected" | "inconclusive";
  later_fork_id: string | null;
  later_passed: number | null;
  decisive: boolean | null;
};

export type BlameCandidate = {
  rank: number;
  step: number;
  span_id: string;
  reasoning: string;
  correction: string;
  verification: Verification | null;
};

export type BlameReport = {
  judge_model: string;
  judge_cost_usd: number | null;
  analysis: string;
  candidates: BlameCandidate[];
  blamed: BlameCandidate | null;
  confidence: "high" | "medium" | null;
  verdict: string;
};

export type BlameInfo = {
  id: string;
  source_run_id: string;
  judge_model: string;
  n: number;
  max_candidates: number;
  status: "queued" | "running" | "done" | "error";
  worker: string | null;
  created_at: string;
  report: BlameReport | null;
  error: string | null;
};

export type ProposalStats = {
  cases: number;
  top1: number | null;
  top3: number | null;
  within1: number | null;
  last_step_baseline: number | null;
  cost_per_case_usd: number | null;
  by_bug: Record<string, { cases: number; top1: number; top3: number }>;
};

export type BlameBenchmark = {
  id: string;
  created_at: string;
  history: {
    id: string;
    created_at: string;
    judge_sees_prompt: boolean;
    failures: number | null;
    top1: Record<string, number | null>;
    verified_accuracy: number | null;
    precision: number | null;
  }[];
  results: {
    failures: number;
    judge_sees_prompt?: boolean;
    proposals: Record<string, ProposalStats>;
    verification?: {
      cases: number;
      judge_model: string;
      n: number;
      proposed_top1: number | null;
      verified_accuracy: number | null;
      precision: number | null;
      abstained: number | null;
      cases_detail: {
        bug: string;
        guilty_step: number;
        proposed: number | null;
        blamed: number | null;
        decisive: boolean | null;
        confidence: string | null;
        blame_id: string;
      }[];
    };
  };
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

export type LabConfig = {
  public: boolean;
  /** The read-only build: data from exported files, forks from presets (D-057). */
  static?: boolean;
  actions: {
    replay: boolean;
    fork: boolean | "key" | "preset";
    blame: boolean | "key";
    lock_in: boolean;
  };
  max_n: number;
  repo: string;
};

export type Showcase = {
  blame: { id: string; run: RunSummary; step: number; span_id: string; verdict: string } | null;
  fork: {
    id: string;
    label: string;
    passed: number;
    control_passed: number | null;
    n: number;
    p_value: number | null;
  } | null;
  diff: { a: string; b: string } | null;
  eval: { id: string; metrics: Metrics; model: string } | null;
  bench: { failures: number; top1: Record<string, number | null>; precision: number | null } | null;
  replay: { id: string; source: string } | null;
};

/** A fork run ahead of time for the read-only demo, offered in place of a live fork. */
export type Preset = {
  fork_id: string;
  run_id: string;
  span_id: string;
  label: string;
  title: string;
  change: string;
  n: number;
  passed: number | null;
  control_passed: number | null;
  p_value: number | null;
  verdict: string;
  created_at: string;
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

// On the hosted demo, forks and blames need a demo key; it is kept in this browser only.
export const DEMO_KEY_STORAGE = "agentlab.demoKey";

function demoKey(): string | null {
  try {
    return window.localStorage.getItem(DEMO_KEY_STORAGE);
  } catch {
    return null;
  }
}

/**
 * The read-only demo (D-057): `npm run build:static` calls no API. It reads the JSON files
 * `lab export-static` saved, the same answers `lab ui` would give.
 */
export const STATIC = import.meta.env.MODE === "static";

export const READ_ONLY =
  "This is a read-only copy of the lab: clone the repo and run `lab ui` to try this live";

/** Where the static build finds an API answer: /api/runs/x → /data/runs/x.json. */
export function staticUrl(path: string): string {
  const [route, query = ""] = path.replace(/^\/api\//, "").split("?");
  if (route === "diff") {
    const params = new URLSearchParams(query);
    return `/data/diff/${params.get("a")}/${params.get("b")}.json`;
  }
  return `/data/${route}.json`;
}

async function getStatic<T>(path: string, init?: RequestInit): Promise<T> {
  if (init?.method === "POST") throw new Error(READ_ONLY);
  const response = await fetch(staticUrl(path));
  // A missing file can come back as the site's index page, so check it really is JSON.
  if (!response.ok || !response.headers.get("content-type")?.includes("json")) {
    throw new Error("Not included in this read-only demo");
  }
  return response.json();
}

async function get<T>(path: string, init?: RequestInit): Promise<T> {
  if (STATIC) return getStatic<T>(path, init);
  const key = demoKey();
  if (key && init?.method === "POST") {
    init = { ...init, headers: { ...(init.headers ?? {}), "X-Demo-Key": key } };
  }
  const response = await fetch(path, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `${response.status} ${response.statusText}`);
  }
  return response.json();
}

export const api = {
  runs: async (params: { status?: string; agent?: string; task_id?: string } = {}) => {
    if (STATIC) {
      // One exported list of every run; filter it here the way the API would.
      const all = await get<RunSummary[]>("/api/runs");
      return all.filter(
        (r) =>
          (!params.status || r.status === params.status) &&
          (!params.agent || r.agent_name === params.agent) &&
          (!params.task_id || r.task_id === params.task_id),
      );
    }
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
  config: () => get<LabConfig>("/api/config"),
  showcase: () => get<Showcase>("/api/showcase"),
  createBlame: (runId: string, n = 5) =>
    get<BlameInfo>("/api/blames", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runId, n }),
    }),
  blame: (id: string) => get<{ blame: BlameInfo; source: RunSummary }>(`/api/blames/${id}`),
  blameBenchmark: () => get<BlameBenchmark>("/api/benchmarks/blame"),
  lockIn: (runId: string) =>
    get<{ task_id: string; created: boolean }>("/api/regressions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runId }),
    }),
  diff: (a: string, b: string) =>
    get<DiffResult>(`/api/diff?${new URLSearchParams({ a, b })}`),
  recordings: (spanId: string) => get<Recording[]>(`/api/spans/${spanId}/recordings`),
  evals: () => get<EvalRun[]>("/api/evals"),
  eval: (id: string) => get<EvalDetail>(`/api/evals/${id}`),
  failureCategories: () => get<Record<string, string>>("/api/failure-categories"),
  // Only in the static build: the preset forks, and which run pairs have an exported diff.
  presets: () => (STATIC ? get<Preset[]>("/api/presets") : Promise.resolve([])),
  diffPairs: () => get<string[]>("/api/diffs"),
};
