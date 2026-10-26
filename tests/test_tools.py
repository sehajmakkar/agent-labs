import pytest
from pydantic import ValidationError

from agentlab.tools import tool


@tool(kind="read")
def lookup(order_id: str, limit: int = 5) -> dict:
    """Find an order."""
    return {"order_id": order_id, "limit": limit}


def test_schema_comes_from_type_hints():
    schema = lookup.parameters_schema
    assert schema["properties"]["order_id"]["type"] == "string"
    assert schema["properties"]["limit"]["type"] == "integer"
    assert schema["required"] == ["order_id"]


def test_metadata():
    assert lookup.name == "lookup"
    assert lookup.description == "Find an order."
    assert lookup.kind == "read"


def test_invoke_validates_and_applies_defaults():
    assert lookup.invoke({"order_id": "4417"}) == {"order_id": "4417", "limit": 5}


def test_invoke_rejects_missing_arguments():
    with pytest.raises(ValidationError):
        lookup.invoke({})


def test_tool_is_still_callable_directly():
    assert lookup("1", limit=2) == {"order_id": "1", "limit": 2}
