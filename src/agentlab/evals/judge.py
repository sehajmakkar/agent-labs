"""LLM-as-judge: a second model call that grades a run against a written description of success.

Programmatic checks are exact and free but can only test what you can write as code ("called
get_payments", "answer mentions 2499"). A judge can grade meaning ("didn't promise a refund it
can't give"), at the cost of money, time and its own mistakes. See learnings.md for its biases.

The judge answers with structured output: JSON matching `Verdict`, so the reply is parsed and
validated rather than scraped from free text.
"""

from dataclasses import dataclass

from pydantic import BaseModel, Field

from agentlab.cost import cost_usd
from agentlab.evals.categories import DESCRIPTIONS, FailureCategory
from agentlab.llm.base import LLMClient, Message, Usage
from agentlab.retry import RetryPolicy, call_with_retries

JUDGE_RETRY = RetryPolicy(max_attempts=6, max_delay_s=30)

SYSTEM_PROMPT = """\
You grade the work of an AI agent. You get the user's request, a description of what a correct
outcome looks like, and the transcript of what the agent did: its tool calls, their results and
its final answer.

Judge only against the expected outcome and the tool results in the transcript. The tool results
are the ground truth: an answer that states something they don't support is a false claim, even if
it sounds plausible. Don't reward length or politeness. Small wording differences are fine.

If the agent failed, pick the one category that best describes the failure:
{categories}"""


class Verdict(BaseModel):
    # `reasoning` comes first so the model writes its reasons before committing to a verdict.
    reasoning: str = Field(description="Two or three sentences comparing the run to the expected")
    passed: bool = Field(description="True if the run meets the expected outcome")
    failure_category: FailureCategory | None = Field(
        description="The category of failure, or null if the run passed"
    )


@dataclass
class Judgement:
    verdict: Verdict
    usage: Usage
    cost_usd: float | None


class LLMJudge:
    def __init__(self, llm: LLMClient, model: str, retry: RetryPolicy = JUDGE_RETRY):
        self.llm = llm
        self.model = model
        self.retry = retry
        categories = "\n".join(
            f"- {name}: {text}" for name, text in DESCRIPTIONS.items() if name != "eval_error"
        )
        self.system = SYSTEM_PROMPT.format(categories=categories)

    def __call__(self, *, request: str, expected: str, transcript: str) -> Judgement:
        prompt = (
            f"USER REQUEST:\n{request}\n\n"
            f"EXPECTED OUTCOME:\n{expected}\n\n"
            f"TRANSCRIPT:\n{transcript}"
        )
        response, _ = call_with_retries(
            lambda: self.llm.generate(
                model=self.model,
                system=self.system,
                messages=[Message.user(prompt)],
                tools=[],
                response_schema=Verdict.model_json_schema(),
            ),
            self.retry,
        )
        verdict = Verdict.model_validate_json(response.message.text or "")
        if verdict.passed:
            verdict.failure_category = None
        return Judgement(verdict, response.usage, cost_usd(self.model, response.usage))
