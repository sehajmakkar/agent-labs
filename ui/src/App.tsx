import { ConfigProvider, DemoKey, useConfig } from "./lib/config";
import { useRoute } from "./lib/hooks";
import { BlameBench, BlameView } from "./pages/BlameView";
import { DiffView } from "./pages/DiffView";
import { EvalView, Evals } from "./pages/Evals";
import { ForkView } from "./pages/ForkView";
import { Home } from "./pages/Home";
import { RunView } from "./pages/RunView";
import { Runs } from "./pages/Runs";

export function App() {
  return (
    <ConfigProvider>
      <Shell />
    </ConfigProvider>
  );
}

function Shell() {
  const route = useRoute();
  const config = useConfig();
  const section =
    route.page === "home"
      ? "home"
      : route.page === "evals" || route.page === "eval"
        ? "evals"
        : route.page === "blame-bench"
          ? "bench"
          : "runs";
  const link = (href: string, name: string, id: string) => (
    <a href={href} className={section === id ? "active" : undefined}>
      {name}
    </a>
  );
  return (
    <div className="app">
      <nav className="nav">
        <a href="#/" className="brand">
          Agent Reliability Lab
        </a>
        {link("#/", "Overview", "home")}
        {link("#/runs", "Runs", "runs")}
        {link("#/evals", "Evals", "evals")}
        {link("#/blame-bench", "Blame accuracy", "bench")}
        <span className="nav-right">
          {config.public && <span className="pill">{config.static ? "read-only demo" : "public demo"}</span>}
          <DemoKey />
          <a href={config.repo}>GitHub</a>
        </span>
      </nav>
      <main>
        {route.page === "home" && <Home />}
        {route.page === "runs" && <Runs />}
        {route.page === "run" && <RunView id={route.id} spanId={route.span} openFork={route.fork} />}
        {route.page === "evals" && <Evals />}
        {route.page === "eval" && <EvalView id={route.id} />}
        {route.page === "fork" && <ForkView id={route.id} />}
        {route.page === "diff" && <DiffView a={route.a} b={route.b} />}
        {route.page === "blame" && <BlameView id={route.id} />}
        {route.page === "blame-bench" && <BlameBench />}
      </main>
    </div>
  );
}
