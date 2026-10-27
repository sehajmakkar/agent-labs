export function money(usd: number | null | undefined): string {
  if (usd == null) return "–";
  return usd < 0.01 ? `$${usd.toFixed(5)}` : `$${usd.toFixed(3)}`;
}

export function seconds(value: number | null | undefined): string {
  return value == null ? "–" : `${value.toFixed(2)}s`;
}

export function tokens(n: number): string {
  return n.toLocaleString("en-US");
}

export function percent(rate: number | null | undefined): string {
  return rate == null ? "–" : `${Math.round(rate * 100)}%`;
}

export function truncate(text: string, max = 80): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length <= max ? flat : `${flat.slice(0, max - 1)}…`;
}

export function compact(value: unknown, max = 80): string {
  return truncate(JSON.stringify(value) ?? "", max);
}

export function localTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** How long the agent itself took: wall time minus waiting for our rate limiter. */
export function activeSeconds(run: { duration_s: number | null; rate_limit_wait_s: number }) {
  return run.duration_s == null ? null : run.duration_s - run.rate_limit_wait_s;
}
