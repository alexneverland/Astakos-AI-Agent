from langchain_core.tools import tool
import math

@tool
def my_tool(value: str) -> str:
    """Uppercase text."""
    return value.upper()
