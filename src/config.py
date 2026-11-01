"""Runtime configuration, read from environment variables.

The agent talks to any OpenAI-compatible chat-completions endpoint, so the
provider is fully configurable. Defaults target Google's Gemini free tier.
"""
import os

BASE_URL = os.getenv(
    "LLM_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai/",
)
API_KEY = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("LLM_MODEL", "gemini-3.8-flash")
TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.4"))
MAX_TOOL_ROUNDS = int(os.getenv("AGENT_MAX_TOOL_ROUNDS", "8"))
SESSIONS_DIR = os.getenv("AGENT_SESSIONS_DIR", ".sessions")
