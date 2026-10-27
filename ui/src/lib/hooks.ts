import { useCallback, useEffect, useState } from "react";

// A tiny hash router: "#/runs/abc" → { page: "run", id: "abc" }. Hash URLs need no server
// routing, so the FastAPI app only has to serve index.html.
export type Route =
  | { page: "runs" }
  | { page: "run"; id: string; span?: string }
  | { page: "evals" }
  | { page: "eval"; id: string };

function parse(hash: string): Route {
  const [path, query = ""] = hash.replace(/^#/, "").split("?");
  const parts = path.split("/").filter(Boolean);
  if (parts[0] === "runs" && parts[1]) {
    const span = new URLSearchParams(query).get("span") ?? undefined;
    return { page: "run", id: parts[1], span };
  }
  if (parts[0] === "evals" && parts[1]) return { page: "eval", id: parts[1] };
  if (parts[0] === "evals") return { page: "evals" };
  return { page: "runs" };
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
