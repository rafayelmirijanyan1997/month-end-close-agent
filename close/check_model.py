"""Check the NVIDIA setup: list the models that can call tools, then test one.

python -m close.check_model            # list models that support tool calling
python -m close.check_model MODEL_ID   # check that MODEL_ID really calls a tool
"""

import sys

from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_nvidia_ai_endpoints import ChatNVIDIA


@tool
def add(a: int, b: int) -> int:
    """Add two whole numbers."""
    return a + b


def main():
    load_dotenv()
    if len(sys.argv) < 2:
        models = sorted(
            m.id for m in ChatNVIDIA.get_available_models() if m.supports_tools
        )
        print(f"{len(models)} models can call tools:")
        print("\n".join(models))
        return
    model = sys.argv[1]
    reply = (
        ChatNVIDIA(model=model, temperature=0)
        .bind_tools([add])
        .invoke("What is 2417 + 3586? Use the add tool.")
    )
    print("tool calls:", reply.tool_calls)
    print("tokens:", reply.usage_metadata)


if __name__ == "__main__":
    main()
