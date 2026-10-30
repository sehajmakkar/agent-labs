import { describe, expect, it } from "vitest";

import { staticUrl } from "../api";

describe("staticUrl", () => {
  it("maps an API path to its exported file", () => {
    expect(staticUrl("/api/runs/abc")).toBe("/data/runs/abc.json");
    expect(staticUrl("/api/runs/abc/family")).toBe("/data/runs/abc/family.json");
    expect(staticUrl("/api/benchmarks/blame")).toBe("/data/benchmarks/blame.json");
  });

  it("drops the run list's filters: the UI filters the one exported list", () => {
    expect(staticUrl("/api/runs?limit=200&task_id=t1")).toBe("/data/runs.json");
  });

  it("puts a diff under both run IDs", () => {
    expect(staticUrl("/api/diff?a=r1&b=r2")).toBe("/data/diff/r1/r2.json");
  });
});
