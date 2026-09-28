"""Launch the terminal UI, or run one question without a terminal session."""
import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

from src.sample import ensure_sample
from src.storage import ROOT, Store
from src.workflow import ask


def main():
    load_dotenv(ROOT / '.env')
    parser = argparse.ArgumentParser(description='Ask Your Data — local terminal chatbot')
    parser.add_argument('--ai', action='store_true', help='Use configured OpenAI API (may incur API charges)')
    parser.add_argument('--ask', help='Ask one question and print JSON evidence')
    parser.add_argument('--home', type=Path, help='Local storage folder (default: data/private)')
    parser.add_argument('--chat', help='Saved chat ID for --ask; otherwise create a new chat')
    parser.add_argument('--check-ai', action='store_true', help='Run a live API/tool check with disposable test data (uses API credits)')
    args = parser.parse_args()
    if args.check_ai:
        from src.config import AIConfig
        from src.connection import check_connection
        result = asyncio.run(check_connection(AIConfig.from_env()))
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result['ok'] else 1)
    store = Store(args.home) if args.home else Store()
    if args.ask:
        sample = ensure_sample(store)
        chat = args.chat or store.new_chat(sample)
        result = asyncio.run(ask(store, chat, args.ask, use_ai=args.ai))
        print(json.dumps({'chat_id': chat, **result}, indent=2))
    else:
        from src.tui import DataChatApp
        DataChatApp(store, use_ai=args.ai).run()


if __name__ == '__main__':
    main()
