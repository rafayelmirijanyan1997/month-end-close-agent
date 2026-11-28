"""Which chat model the agent uses. It is set in .env, so changing model needs no code change."""

import os

from dotenv import load_dotenv


def make_llm():
    load_dotenv()
    from langchain_nvidia_ai_endpoints import ChatNVIDIA

    return ChatNVIDIA(model=os.environ["NVIDIA_MODEL"], temperature=0, max_tokens=4096)
