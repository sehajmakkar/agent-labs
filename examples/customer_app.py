"""A customer's own agent, traced by adding three lines of the lab's SDK.

Nothing here uses the lab's agent loop: it is a plain loop over the `google-genai` SDK, the way a
team might write it themselves. The lines marked 1, 2 and 3 are the whole integration. Every run
then shows up in `lab runs` and the web UI like any other.

    uv run python examples/customer_app.py "Do I need an umbrella in Pune today?"
    uv run lab replay <run-id> --entry examples/customer_app.py:answer   # offline, from this code
"""

import os
import sys

from dotenv import load_dotenv
from google import genai
from google.genai import types

import agentlab as lab

load_dotenv()
MODEL = os.environ.get("AGENTLAB_FLASH_LITE_MODEL", "gemini-3.5-flash-lite")

lab.init(".agentlab/lab.db")  # 1. start recording runs
client = lab.wrap(genai.Client(api_key=os.environ["GEMINI_API_KEY"]))  # 2. trace model calls

FORECASTS = {
    "pune": {"condition": "heavy rain from 3pm", "high_c": 27, "rain_chance": 0.9},
    "delhi": {"condition": "hazy sunshine", "high_c": 31, "rain_chance": 0.05},
}


@lab.tool(kind="read")  # 3. trace tool calls
def get_forecast(city: str) -> dict:
    """Today's forecast for a city: condition, high temperature in °C and chance of rain."""
    if city.lower() not in FORECASTS:
        raise LookupError(f"No forecast for {city}")
    return {"city": city, **FORECASTS[city.lower()]}


TOOLS = {get_forecast.name: get_forecast}


@lab.agent("weather-bot")
def answer(question: str) -> str:
    config = types.GenerateContentConfig(
        # `lab.now()`, not `datetime.now()`: the date is recorded, so `lab replay` still matches
        # tomorrow, when the real date (and so this prompt) would have changed.
        system_instruction=f"Today is {lab.now():%A %d %B %Y}. Answer weather questions in one "
        "or two sentences using the tools.",
        tools=[
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name=t.name,
                        description=t.description,
                        parameters_json_schema=t.parameters_schema,
                    )
                    for t in TOOLS.values()
                ]
            )
        ],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=question)])]
    for _ in range(5):
        response = client.models.generate_content(model=MODEL, contents=contents, config=config)
        content = response.candidates[0].content
        calls = [p.function_call for p in content.parts or [] if p.function_call]
        if not calls:
            return response.text or ""
        contents.append(content)
        results = []
        for call in calls:
            try:
                output = TOOLS[call.name].invoke(dict(call.args or {}), call_id=call.id)
            except Exception as e:
                output = {"error": str(e)}
            results.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        id=call.id, name=call.name, response=output
                    )
                )
            )
        contents.append(types.Content(role="user", parts=results))
    return "Sorry, I couldn't work that out."


if __name__ == "__main__":
    print(answer(sys.argv[1] if len(sys.argv) > 1 else "Do I need an umbrella in Pune today?"))
