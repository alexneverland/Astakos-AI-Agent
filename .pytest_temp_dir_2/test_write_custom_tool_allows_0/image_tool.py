from langchain_core.tools import tool
import math

class Image:
    @staticmethod
    def open(value: str) -> str:
        return value

@tool
def image_tool(value: str) -> str:
    """Uses Image.open without using builtin open."""
    return Image.open(value)
