import { useRoute } from "./lib/hooks";
import { DiffView } from "./pages/DiffView";
import { EvalView, Evals } from "./pages/Evals";
import { ForkView } from "./pages/ForkView";
import { RunView } from "./pages/RunView";
import { Runs } from "./pages/Runs";

export function App() {
  const route = useRoute();
  const section = route.page === "evals" || route.page === "eval" ? "evals" : "runs";
  return (
    <div className="app">
      <nav className="nav">
        <a href="#/" className="brand">
          Agent Reliability Lab
        </a>
        <a href="#/" className={section === "runs" ? "active" : undefined}>
          Runs
        </a>
        <a href="#/evals" className={section === "evals" ? "active" : undefined}>
          Evals
        </a>
      </nav>
      <main>
        {route.page === "runs" && <Runs />}
        {route.page === "run" && (
          <RunView id={route.id} spanId={route.span} openFork={route.fork} />
        )}
        {route.page === "evals" && <Evals />}
        {route.page === "eval" && <EvalView id={route.id} />}
        {route.page === "fork" && <ForkView id={route.id} />}
        {route.page === "diff" && <DiffView a={route.a} b={route.b} />}
      </main>
    </div>
  );
}
