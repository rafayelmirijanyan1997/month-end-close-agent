"""Which chat model the agent uses. It is set in .env, so changing model needs no code change."""

import os

from dotenv import load_dotenv


def make_llm():
    load_dotenv()
    from langchain_nvidia_ai_endpoints import ChatNVIDIA

    thinking = os.getenv("NVIDIA_THINKING", "off") == "on"
    return ChatNVIDIA(
        model=os.environ["NVIDIA_MODEL"],
        temperature=0,
        max_completion_tokens=4096,
        model_kwargs={"chat_template_kwargs": {"enable_thinking": thinking}},
    )
