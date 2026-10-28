import { useCallback, useEffect, useState } from "react";

// A tiny hash router: "#/runs/abc" → { page: "run", id: "abc" }. Hash URLs need no server
// routing, so the FastAPI app only has to serve index.html.
export type Route =
  | { page: "home" }
  | { page: "runs" }
  | { page: "run"; id: string; span?: string; fork?: boolean }
  | { page: "evals" }
  | { page: "eval"; id: string }
  | { page: "fork"; id: string }
  | { page: "diff"; a: string; b: string }
  | { page: "blame"; id: string }
  | { page: "blame-bench" };

function parse(hash: string): Route {
  const [path, query = ""] = hash.replace(/^#/, "").split("?");
  const parts = path.split("/").filter(Boolean);
  if (parts[0] === "runs" && parts[1]) {
    const params = new URLSearchParams(query);
    // `?span=<id>&fork=1` opens the fork dialog for that span, so a link can point straight at it.
    return { page: "run", id: parts[1], span: params.get("span") ?? undefined, fork: params.has("fork") };
  }
  if (parts[0] === "evals" && parts[1]) return { page: "eval", id: parts[1] };
  if (parts[0] === "forks" && parts[1]) return { page: "fork", id: parts[1] };
  if (parts[0] === "diff" && parts[1] && parts[2]) return { page: "diff", a: parts[1], b: parts[2] };
  if (parts[0] === "blames" && parts[1]) return { page: "blame", id: parts[1] };
  if (parts[0] === "blame-bench") return { page: "blame-bench" };
  if (parts[0] === "evals") return { page: "evals" };
  if (parts[0] === "runs") return { page: "runs" };
  return { page: "home" };
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parse(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export function navigate(hash: string, replace = false) {
  if (replace) window.history.replaceState(null, "", hash);
  else window.location.hash = hash;
  if (replace) window.dispatchEvent(new HashChangeEvent("hashchange"));
}

export type Loadable<T> = { data?: T; error?: string; loading: boolean; reload: () => void };

/** Fetch on mount and whenever `key` changes. Stale responses are ignored. */
export function useLoad<T>(load: () => Promise<T>, key: string): Loadable<T> {
  const [state, setState] = useState<{ data?: T; error?: string; loading: boolean }>({
    loading: true,
  });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let current = true;
    setState((s) => ({ ...s, loading: true }));
    load().then(
      (data) => current && setState({ data, loading: false }),
      (e: Error) => current && setState({ error: e.message, loading: false }),
    );
    return () => {
      current = false;
    };
    // `load` is recreated every render; `key` says when it actually changes.
  }, [key, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, reload };
}
