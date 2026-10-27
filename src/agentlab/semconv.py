"""Span attribute names.

`gen_ai.*` names follow the OpenTelemetry GenAI semantic conventions, pinned to the version below
(decisions.md D-006). They are still in Development status, so check them again before building the
OTLP exporter. Names under `agentlab.*` are our own, for things the conventions don't cover.
"""

SEMCONV_VERSION = "1.41.0"

OPERATION_NAME = "gen_ai.operation.name"  # "chat" | "execute_tool" | "invoke_agent"
PROVIDER_NAME = "gen_ai.provider.name"
PROVIDER_GEMINI = "gcp.gemini"  # the Gemini Developer API (generativelanguage.googleapis.com)
REQUEST_MODEL = "gen_ai.request.model"
RESPONSE_MODEL = "gen_ai.response.model"
RESPONSE_FINISH_REASONS = "gen_ai.response.finish_reasons"
USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"  # includes reasoning tokens, per the spec
USAGE_REASONING_OUTPUT_TOKENS = "gen_ai.usage.reasoning.output_tokens"
TOOL_NAME = "gen_ai.tool.name"
TOOL_CALL_ID = "gen_ai.tool.call.id"
AGENT_NAME = "gen_ai.agent.name"

TOOL_KIND = "agentlab.tool.kind"  # "read" | "write"
STEP_INDEX = "agentlab.step.index"
LLM_ATTEMPTS = "agentlab.llm.attempts"  # 1 means no retries were needed
RUN_STATUS = "agentlab.run.status"
RATE_LIMIT_WAIT_S = "agentlab.rate_limit.wait_s"  # time a run spent waiting for our rate limiter
