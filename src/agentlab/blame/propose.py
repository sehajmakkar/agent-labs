"""Proposing blame: an LLM judge reads a failed run and ranks the steps that may have caused it.

The judge sees the agent's system prompt, the run as numbered steps (calls, results, answers), what
the task expected, and which checks failed. Seeing the prompt matters: when a prompt line caused
the mistake, a correction that doesn't explicitly override it loses to it (learnings.md).

It returns up to three candidate "first wrong steps", most likely first, each with its reasoning
and a *correction*: an instruction that, added to the agent's prompt, should make it act correctly
at that step. Verification then applies that correction in a fork, so a
proposal is a hypothesis that can be tested, not just an opinion.
"""

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from agentlab.cost import cost_usd
from agentlab.diff.steps import StepView
from agentlab.llm.base import LLMClient, Message, Usage
from agentlab.retry import RetryPolicy, call_with_retries

BLAME_RETRY = RetryPolicy(max_attempts=6, max_delay_s=30)
MAX_RESULT_CHARS = 700

SYSTEM_PROMPT = """\
You investigate why an AI agent failed a task. You get the agent's system prompt, the user's
request, what a correct outcome looks like, which checks failed, and the agent's run as numbered
steps.

Find the FIRST WRONG STEP: the earliest step where the agent did something a correct agent would
not have done (called the wrong tool, used wrong arguments, ignored or misread a tool result, took
an action it shouldn't have, or gave a wrong or incomplete answer). Steps before it must have been
reasonable. A step that was fine is not the first wrong step just because the run failed later.

Return up to three candidates, most likely first, each a different step. For each, give your
reasoning first, then the step number, then a correction: one short instruction that, added to the
agent's system prompt, would make it act correctly at that step. Write the correction as a general
rule ("When a payment is a voided authorization, do not treat it as a charge."), never mention step
numbers, and don't just restate the expected outcome. If a line in the system prompt caused the
mistake, say so in your reasoning, and write the correction so that it explicitly overrides that
line (for example "Ignore the earlier rule about X: instead, …"), because a correction that only
adds advice loses to a direct instruction."""


class Candidate(BaseModel):
    reasoning: str = Field(description="Why the run went wrong at this step")
    step: int = Field(description="The step number, as numbered in the run")
    correction: str = Field(description="One instruction for the agent's system prompt")


class Proposal(BaseModel):
    analysis: str = Field(description="Two or three sentences on what went wrong overall")
    candidates: list[Candidate] = Field(description="Up to three, most likely first")


@dataclass
class ProposalResult:
    proposal: Proposal
    usage: Usage
    cost_usd: float | None
    model: str


class BlameJudge:
    def __init__(self, llm: LLMClient, model: str, retry: RetryPolicy = BLAME_RETRY):
        self.llm, self.model, self.retry = llm, model, retry

    def __call__(
        self,
        *,
        request: str,
        expected: str,
        failures: list[str],
        steps: list[StepView],
        system_prompt: str | None = None,
    ) -> ProposalResult:
        prompt = (
            (f"THE AGENT'S SYSTEM PROMPT:\n{system_prompt}\n\n" if system_prompt else "")
            + f"USER REQUEST:\n{request}\n\n"
            f"EXPECTED OUTCOME:\n{expected}\n\n"
            "FAILED CHECKS:\n" + "\n".join(f"- {f}" for f in failures) + "\n\n"
            f"THE RUN:\n{render_steps(steps)}"
        )
        response, _ = call_with_retries(
            lambda: self.llm.generate(
                model=self.model,
                system=SYSTEM_PROMPT,
                messages=[Message.user(prompt)],
                tools=[],
                response_schema=Proposal.model_json_schema(),
            ),
            self.retry,
        )
        proposal = Proposal.model_validate_json(response.message.text or "")
        proposal.candidates = _valid(proposal.candidates, len(steps))
        return ProposalResult(
            proposal, response.usage, cost_usd(self.model, response.usage), self.model
        )


def render_steps(steps: list[StepView]) -> str:
    """The run as numbered steps, the way the judge reads it."""
    lines = []
    for step in steps:
        if step.error:
            lines.append(f"STEP {step.index}: the model call failed: {step.error}")
            continue
        if step.calls:
            lines.append(f"STEP {step.index}: the agent called")
            for call in step.calls:
                lines.append(f"  {call.name}({json.dumps(call.args)})")
                result = f"ERROR {call.error}" if call.error else _clip(call.output)
                lines.append(f"    → {result}")
            if step.text:
                lines.append(f"  and said: {step.text}")
        else:
            lines.append(f"STEP {step.index}: the agent answered:\n  {step.text}")
    return "\n".join(lines)


def _valid(candidates: list[Candidate], step_count: int) -> list[Candidate]:
    """Drop candidates that name a step the run doesn't have, or repeat a step."""
    seen: set[int] = set()
    valid = []
    for c in candidates:
        if 1 <= c.step <= step_count and c.step not in seen:
            seen.add(c.step)
            valid.append(c)
    return valid[:3]


def _clip(value: Any) -> str:
    text = json.dumps(value, default=str)
    return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS] + " …"
