"""Configuração lida de variáveis de ambiente.

O agente conversa com qualquer endpoint compatível com a API de chat
completions da OpenAI, então o provedor é totalmente configurável. O padrão
aponta para o plano gratuito do Gemini (Google AI Studio).

A chave de API só é lida do ambiente (ou de um .env local, que está no
.gitignore). O projeto nunca imprime nem grava a chave.
"""
import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def _load_dotenv() -> None:
    """Lê um .env local sem dependência extra (formato CHAVE=valor)."""
    path = Path(__file__).resolve().parent.parent / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

BASE_URL = os.getenv(
    "LLM_BASE_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai/",
)
API_KEY = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("LLM_MODEL", "gemini-3.6-flash")
TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.4"))
# Só é enviado se for definido: nem todo modelo/endpoint aceita esse parâmetro.
REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "")
MAX_TOOL_ROUNDS = int(os.getenv("AGENT_MAX_TOOL_ROUNDS", "8"))
MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "4"))
SESSIONS_DIR = os.getenv("AGENT_SESSIONS_DIR", ".sessions")

# Data/hora da loja (Campo Grande/MS). STORE_TODAY=AAAA-MM-DD fixa a data para
# demonstrações reproduzíveis (os pedidos do dataset vão até março/2026).
STORE_TZ = ZoneInfo("America/Campo_Grande")
STORE_TODAY = os.getenv("STORE_TODAY", "").strip()


def store_now() -> datetime:
    now = datetime.now(STORE_TZ)
    if STORE_TODAY:
        fixed = date.fromisoformat(STORE_TODAY)
        now = now.replace(year=fixed.year, month=fixed.month, day=fixed.day)
    return now
