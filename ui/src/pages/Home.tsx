import { api, type Showcase } from "../api";
import { useConfig } from "../lib/config";
import { percent } from "../lib/format";
import { useLoad } from "../lib/hooks";

/** The front door: what the lab does, in the order of the loop, each step linked to a real example. */
export function Home() {
  const showcase = useLoad(api.showcase, "showcase");
  const config = useConfig();
  const s = showcase.data;

  return (
    <div className="page home">
      <section className="hero">
        <h1>Find the step where your AI agent went wrong, and prove the fix.</h1>
        <p className="lead">
          Agent Reliability Lab records every model and tool call your agent makes, replays any run
          exactly, and on a failure names the step at fault, then proves it by re-running that step
          with a correction against a control. Everything below is a real run from this lab.
        </p>
        {s && <Numbers s={s} />}
      </section>

      <ol className="loop">
        <Step
          n={1}
          title="Record"
          text="Three lines in your code. Every decision becomes a tree you can click through."
          link={s?.blame ? `#/runs/${s.blame.run.id}` : "#/runs"}
          cta="Open a recorded run"
        />
        <Step
          n={2}
          title="Evaluate"
          text="Run a dataset of tasks; code checks and an LLM judge score each one, with a reason."
          link={s?.eval ? `#/evals/${s.eval.id}` : "#/evals"}
          cta={s?.eval ? `Eval: ${s.eval.metrics.passed}/${s.eval.metrics.tasks} passed` : "Open evals"}
        />
        <Step
          n={3}
          title="Blame"
          text="A judge proposes the first wrong step; forks against a control confirm it."
          link={s?.blame ? `#/blames/${s.blame.id}` : "#/blame-bench"}
          cta={s?.blame ? `Step ${s.blame.step} is at fault, verified` : "Blame accuracy"}
          highlight
        />
        <Step
          n={4}
          title="Fork"
          text="Re-run from any step with one change, N times, next to N runs without it."
          link={s?.fork ? `#/forks/${s.fork.id}` : "#/runs"}
          cta={
            s?.fork
              ? `${s.fork.passed}/${s.fork.n} with the fix vs ${s.fork.control_passed}/${s.fork.n} without`
              : "Fork any run"
          }
        />
        <Step
          n={5}
          title="Diff"
          text="Line two runs up step by step: where they diverged, and what it changed."
          link={s?.diff ? `#/diff/${s.diff.a}/${s.diff.b}` : "#/runs"}
          cta="Original vs fixed"
        />
        <Step
          n={6}
          title="Lock it in"
          text="Save the failure as a regression test; a CI gate keeps it from coming back."
          link={s?.blame ? `#/blames/${s.blame.id}` : "#/runs"}
          cta="lab eval --gate 0.9"
        />
      </ol>

      {s?.blame && (
        <section className="panel story">
          <div className="eyebrow">The example</div>
          <p>
            A support agent refunded a duplicate charge correctly, then forgot to give the customer
            the refund ID. One click on <strong>Blame</strong>:
          </p>
          <blockquote>{s.blame.verdict}</blockquote>
          <p className="muted">
            Steps 1–2 were replayed from the recording (no cost, no side effects); only step 3 ran
            live, with and without the correction.
          </p>
        </section>
      )}

      <section className="panel">
        <h2>Plugs into your agent</h2>
        <pre className="code">{`import agentlab as lab

lab.init("https://your-lab.example.com")      # where runs go
client = lab.wrap(genai.Client())             # every model call recorded

@lab.tool(kind="write")                        # every tool call recorded
def refund_payment(payment_id: str): ...`}</pre>
        <p className="muted">
          Your agent keeps running in your code; forks and blames run in a worker inside your repo.{" "}
          <a href={config.repo}>Source on GitHub</a>
        </p>
      </section>
    </div>
  );
}

function Numbers({ s }: { s: Showcase }) {
  const items: [string, string][] = [];
  if (s.eval) items.push([percent(s.eval.metrics.success_rate), `of ${s.eval.metrics.tasks} eval tasks pass`]);
  if (s.fork) items.push([`${s.fork.passed}/${s.fork.n} vs ${s.fork.control_passed}/${s.fork.n}`, "fix proved by forking"]);
  if (s.bench) {
    const best = Math.max(...Object.values(s.bench.top1).map((v) => v ?? 0));
    items.push([percent(best), `blame top-1 on ${s.bench.failures} planted bugs`]);
  }
  if (s.replay) items.push(["$0", "to replay any run exactly, offline"]);
  return (
    <div className="numbers">
      {items.map(([value, label]) => (
        <div key={label}>
          <div className="number">{value}</div>
          <div className="muted">{label}</div>
        </div>
      ))}
    </div>
  );
}

function Step({
  n,
  title,
  text,
  link,
  cta,
  highlight = false,
}: {
  n: number;
  title: string;
  text: string;
  link: string;
  cta: string;
  highlight?: boolean;
}) {
  return (
    <li className={`loop-step ${highlight ? "loop-highlight" : ""}`}>
      <div className="loop-n">{n}</div>
      <h3>{title}</h3>
      <p>{text}</p>
      <a href={link}>{cta} →</a>
    </li>
  );
}
