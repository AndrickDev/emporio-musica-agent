"""Command-line chat with the Empório da Música agent.

Usage:
    python main.py                 # new conversation
    python main.py --session ana   # named session, persisted under .sessions/
"""
import argparse
from pathlib import Path

from src import config
from src.agent import Agent


def main() -> None:
    parser = argparse.ArgumentParser(description="Empório da Música - agente de atendimento")
    parser.add_argument("--session", default=None, help="Nome da sessão para manter o histórico")
    args = parser.parse_args()

    session_path = None
    if args.session:
        session_path = Path(config.SESSIONS_DIR) / f"{args.session}.json"
    agent = Agent.load(session_path) if session_path and session_path.exists() else Agent()

    print("Empório da Música - assistente virtual")
    print("Digite sua mensagem. /sair encerra, /limpar reinicia a conversa.")
    while True:
        try:
            user_input = input("\nCliente: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAté logo!")
            break
        if not user_input:
            continue
        if user_input == "/sair":
            print("Até logo!")
            break
        if user_input == "/limpar":
            agent = Agent()
            print("(conversa reiniciada)")
            continue
        result = agent.chat(user_input)
        for call in result["tool_calls"]:
            print(f"  [consulta: {call['tool']}({call['arguments']})]")
        print(f"\nAgente: {result['reply']}")
        if session_path:
            agent.save(session_path)


if __name__ == "__main__":
    main()
