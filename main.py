"""Chat no terminal com o agente da Empório da Música.

Uso:
    python main.py                 # nova conversa
    python main.py --session ana   # sessão nomeada, salva em .sessions/
    python main.py --debug         # mostra também o resultado de cada ferramenta
"""
import argparse
import json
from pathlib import Path

from src import config
from src.agent import Agent, describe_api_error


def main() -> None:
    parser = argparse.ArgumentParser(description="Empório da Música - agente de atendimento")
    parser.add_argument("--session", default=None, help="Nome da sessão para manter o histórico")
    parser.add_argument("--debug", action="store_true", help="Mostra o resultado das ferramentas")
    args = parser.parse_args()

    if not config.API_KEY:
        print("Defina LLM_API_KEY no ambiente ou no arquivo .env (veja .env.example).")
        return

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
        try:
            result = agent.chat(user_input)
        except Exception as exc:  # erro do provedor (cota, rede): avisa e segue a conversa
            print(f"\n[erro ao falar com o modelo: {describe_api_error(exc)}]")
            continue
        for call in result["tool_calls"]:
            print(f"  [consulta: {call['tool']}({call['arguments']})]")
            if args.debug:
                print(f"    -> {json.dumps(call['result'], ensure_ascii=False)[:300]}")
        print(f"\nAgente: {result['reply']}")
        if session_path:
            agent.save(session_path)


if __name__ == "__main__":
    main()
