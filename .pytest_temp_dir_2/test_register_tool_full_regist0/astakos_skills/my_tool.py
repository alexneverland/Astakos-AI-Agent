from langchain_core.tools import tool
@tool
def my_tool(x: str) -> str: return x
