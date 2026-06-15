from langchain_core.tools import tool

@tool
def my_tool(value: str) -> str:
    """Echo text."""
    return value
