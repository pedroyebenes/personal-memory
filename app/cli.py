from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from app.config import load_settings
from app.db import connect, init_db
from app.ingest.register import ingest_vault, reindex_vault, status_summary
from app.retrieval.hybrid_search import hybrid_search
from app.retrieval.qa import answer_question
from app.web import serve_web


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="personal-memory")
    parser.add_argument("--config", help="Optional JSON config file path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db")
    subparsers.add_parser("status")

    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("--vault", required=False)

    reindex_parser = subparsers.add_parser("reindex")
    reindex_parser.add_argument("--vault", required=False)

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--top-k", type=int)

    ask_parser = subparsers.add_parser("ask")
    ask_parser.add_argument("--query", required=True)
    ask_parser.add_argument("--top-k", type=int)
    ask_parser.add_argument("--use-llm", action="store_true")

    web_parser = subparsers.add_parser("web")
    web_parser.add_argument("--host", default="127.0.0.1")
    web_parser.add_argument("--port", type=int, default=8000)
    return parser


def _resolve_vault_arg(cli_value: str | None, config_value: Path | None) -> Path:
    if cli_value:
        return Path(cli_value).expanduser().resolve()
    if config_value:
        return config_value
    raise SystemExit("Vault path must be provided via --vault or VAULT_PATH.")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = load_settings(args.config)
    connection = connect(settings.database_path)

    if args.command == "init-db":
        init_db(connection)
        print(json.dumps({"database_path": str(settings.database_path), "status": "initialized"}, indent=2))
        return

    init_db(connection)

    if args.command == "status":
        print(json.dumps(status_summary(connection), indent=2))
        return

    if args.command == "ingest":
        vault_path = _resolve_vault_arg(args.vault, settings.vault_path)
        print(json.dumps(ingest_vault(connection, vault_path, settings), indent=2))
        return

    if args.command == "reindex":
        vault_path = _resolve_vault_arg(args.vault, settings.vault_path)
        print(json.dumps(reindex_vault(connection, vault_path, settings), indent=2))
        return

    if args.command == "search":
        results = hybrid_search(connection, args.query, settings, top_k=args.top_k or settings.top_k)
        print(json.dumps([asdict(result) for result in results], indent=2))
        return

    if args.command == "ask":
        response = answer_question(
            connection,
            args.query,
            settings,
            top_k=args.top_k or settings.top_k,
            use_llm=args.use_llm or None,
        )
        print(json.dumps(response, indent=2))
        return

    if args.command == "web":
        connection.close()
        serve_web(settings, host=args.host, port=args.port)
        return

    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
