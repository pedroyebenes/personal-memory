from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from app.config import format_diagnostics, load_settings
from app.db import connect, init_db
from app.ingest.register import (
    ingest_vault,
    reclassify_entities,
    rebuild_chunk_vectors,
    rebuild_embeddings,
    refresh_concepts,
    reindex_vault,
    status_summary,
)
from app.retrieval.concept_search import (
    CONCEPT_QUALITIES,
    concept_noise_report,
    find_concept,
    get_concept_detail,
    list_concepts,
    semantic_concept_search,
)
from app.retrieval.evaluation import evaluate_retrieval
from app.retrieval.hybrid_search import hybrid_search
from app.retrieval.qa import answer_question
from app.retrieval.query_rewrite import resolve_retrieval_query
from app.web import serve_web


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="personal-memory")
    parser.add_argument("--config", help="Optional JSON config file path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db")
    subparsers.add_parser("status")

    ingest_parser = subparsers.add_parser("ingest")
    ingest_parser.add_argument("--vault", required=False)
    ingest_parser.add_argument("--include", action="append", default=None, help="glob to include (relative to vault)")
    ingest_parser.add_argument("--exclude", action="append", default=None, help="glob to exclude (relative to vault)")

    reindex_parser = subparsers.add_parser("reindex")
    reindex_parser.add_argument("--vault", required=False)
    reindex_parser.add_argument("--include", action="append", default=None, help="glob to include (relative to vault)")
    reindex_parser.add_argument("--exclude", action="append", default=None, help="glob to exclude (relative to vault)")

    embeddings_parser = subparsers.add_parser("embeddings")
    embeddings_sub = embeddings_parser.add_subparsers(dest="embeddings_command", required=True)
    emb_rebuild = embeddings_sub.add_parser("rebuild")
    emb_rebuild.add_argument(
        "--no-breadcrumbs",
        action="store_true",
        help="Embed raw chunk text only (matches USE_BREADCRUMB_EMBEDDINGS=false)",
    )

    vectors_parser = subparsers.add_parser("vectors")
    vectors_sub = vectors_parser.add_subparsers(dest="vectors_command", required=True)
    vectors_sub.add_parser("rebuild")

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--top-k", type=int)
    search_parser.add_argument("--rewrite-query", action="store_true")
    search_parser.add_argument("--rerank", action="store_true")
    search_parser.add_argument("--concept-boost", action="store_true")
    search_parser.add_argument(
        "--debug-scores",
        action="store_true",
        help="Include fusion_weights and refresh score_explanation.final_score after ranking",
    )

    ask_parser = subparsers.add_parser("ask")
    ask_parser.add_argument("--query", required=True)
    ask_parser.add_argument("--top-k", type=int)
    ask_parser.add_argument("--use-llm", action="store_true")
    ask_parser.add_argument("--rewrite-query", action="store_true")
    ask_parser.add_argument("--rerank", action="store_true")
    ask_parser.add_argument("--concept-boost", action="store_true")

    web_parser = subparsers.add_parser("web")
    web_parser.add_argument("--host", default="0.0.0.0")
    web_parser.add_argument("--port", type=int, default=8000)

    concepts_parser = subparsers.add_parser("concepts")
    concepts_sub = concepts_parser.add_subparsers(dest="concepts_command", required=True)

    list_parser = concepts_sub.add_parser("list")
    list_parser.add_argument("--limit", type=int, default=50)
    list_parser.add_argument("--offset", type=int, default=0)
    list_parser.add_argument("--search", default=None)
    list_parser.add_argument("--type", choices=("concept", "structure", "all"), default="concept")
    list_parser.add_argument("--method", default=None)
    list_parser.add_argument("--quality", choices=tuple(sorted(CONCEPT_QUALITIES)), default=None)

    show_parser = concepts_sub.add_parser("show")
    show_group = show_parser.add_mutually_exclusive_group(required=True)
    show_group.add_argument("--id", type=int, dest="concept_id")
    show_group.add_argument("--name", type=str, dest="concept_name")

    concepts_sub.add_parser("refresh")
    concepts_sub.add_parser("reclassify")
    concept_search_parser = concepts_sub.add_parser("search")
    concept_search_parser.add_argument("--query", required=True)
    concept_search_parser.add_argument("--top-k", type=int, default=20)
    noise_parser = concepts_sub.add_parser("noise-report")
    noise_parser.add_argument("--limit", type=int, default=50)

    eval_parser = subparsers.add_parser("eval")
    eval_sub = eval_parser.add_subparsers(dest="eval_command", required=True)
    retrieval_eval = eval_sub.add_parser("retrieval")
    retrieval_eval.add_argument("--cases", default=None, help="JSON file with retrieval evaluation cases")
    retrieval_eval.add_argument("--top-k", type=int)
    retrieval_eval.add_argument("--rerank", action="store_true")
    retrieval_eval.add_argument("--concept-boost", action="store_true")
    return parser


def _resolve_vault_arg(cli_value: str | None, config_value: Path | None) -> Path:
    if cli_value:
        return Path(cli_value).expanduser().resolve()
    if config_value:
        return config_value
    raise SystemExit("Vault path must be provided via --vault, config.json, or VAULT_PATH.")


def _apply_scope_overrides(settings, args) -> None:
    if getattr(args, "include", None):
        settings.ingest_include = tuple(args.include)
    if getattr(args, "exclude", None):
        settings.ingest_exclude = tuple(args.exclude)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = load_settings(args.config)
    config_diagnostics = settings.validate()
    connection = connect(settings.database_path)

    if args.command == "init-db":
        init_db(connection)
        print(
            json.dumps(
                {
                    "database_path": str(settings.database_path),
                    "status": "initialized",
                    "config_diagnostics": config_diagnostics,
                },
                indent=2,
            )
        )
        return

    init_db(connection)

    if args.command == "status":
        payload = status_summary(connection)
        payload["config_diagnostics"] = config_diagnostics
        print(json.dumps(payload, indent=2))
        return

    if args.command == "ingest":
        vault_path = _resolve_vault_arg(args.vault, settings.vault_path)
        _apply_scope_overrides(settings, args)
        summary = ingest_vault(connection, vault_path, settings)
        print(json.dumps(summary, indent=2))
        if summary.get("failed"):
            sys.exit(2)
        return

    if args.command == "reindex":
        vault_path = _resolve_vault_arg(args.vault, settings.vault_path)
        _apply_scope_overrides(settings, args)
        summary = reindex_vault(connection, vault_path, settings)
        print(json.dumps(summary, indent=2))
        if summary.get("failed"):
            sys.exit(2)
        return

    if args.command == "embeddings":
        if args.embeddings_command == "rebuild":
            use_bc = False if args.no_breadcrumbs else None
            print(json.dumps(rebuild_embeddings(connection, settings, use_breadcrumbs=use_bc), indent=2))
            return
        raise SystemExit(f"Unknown embeddings subcommand: {args.embeddings_command}")

    if args.command == "vectors":
        if args.vectors_command == "rebuild":
            print(json.dumps(rebuild_chunk_vectors(connection), indent=2))
            return
        raise SystemExit(f"Unknown vectors subcommand: {args.vectors_command}")

    if args.command == "search":
        retrieval_query, warnings = resolve_retrieval_query(
            args.query,
            settings,
            use_query_rewrite=args.rewrite_query or None,
        )
        results = hybrid_search(
            connection,
            retrieval_query,
            settings,
            top_k=args.top_k or settings.top_k,
            use_rerank=args.rerank or None,
            use_concept_boost=args.concept_boost or None,
            debug_scores=args.debug_scores,
        )
        print(
            json.dumps(
                {
                    "query": args.query,
                    "retrieval_query": retrieval_query,
                    "warnings": warnings,
                    "results": [asdict(result) for result in results],
                },
                indent=2,
            )
        )
        return

    if args.command == "ask":
        response = answer_question(
            connection,
            args.query,
            settings,
            top_k=args.top_k or settings.top_k,
            use_llm=args.use_llm or None,
            use_query_rewrite=args.rewrite_query or None,
            use_rerank=args.rerank or None,
            use_concept_boost=args.concept_boost or None,
        )
        print(json.dumps(response, indent=2))
        return

    if args.command == "concepts":
        if args.concepts_command == "list":
            entity_type = None if args.type == "all" else args.type
            concepts = list_concepts(
                connection,
                search=args.search,
                entity_type=entity_type,
                method=args.method,
                quality=args.quality,
                limit=args.limit,
                offset=args.offset,
            )
            print(json.dumps({"concepts": concepts, "count": len(concepts)}, indent=2))
            return
        if args.concepts_command == "show":
            if args.concept_id is not None:
                detail = get_concept_detail(connection, args.concept_id)
            else:
                concept = find_concept(connection, name=args.concept_name)
                detail = get_concept_detail(connection, int(concept["id"])) if concept else None
            if detail is None:
                print(json.dumps({"error": "concept_not_found"}, indent=2))
                sys.exit(1)
            print(json.dumps(detail, indent=2))
            return
        if args.concepts_command == "refresh":
            print(json.dumps(refresh_concepts(connection, settings), indent=2))
            return
        if args.concepts_command == "reclassify":
            print(json.dumps(reclassify_entities(connection, settings), indent=2))
            return
        if args.concepts_command == "search":
            print(
                json.dumps(
                    {
                        "concepts": semantic_concept_search(
                            connection,
                            args.query,
                            settings,
                            top_k=args.top_k,
                        )
                    },
                    indent=2,
                )
            )
            return
        if args.concepts_command == "noise-report":
            print(json.dumps(concept_noise_report(connection, limit=args.limit), indent=2))
            return
        raise SystemExit(f"Unknown concepts subcommand: {args.concepts_command}")

    if args.command == "eval":
        if args.eval_command == "retrieval":
            cases_path = Path(args.cases).expanduser().resolve() if args.cases else None
            payload = evaluate_retrieval(
                connection,
                settings,
                cases_path=cases_path,
                top_k=args.top_k,
                use_rerank=args.rerank or None,
                use_concept_boost=args.concept_boost or None,
            )
            print(json.dumps(payload, indent=2))
            if payload["status"] == "failed":
                sys.exit(2)
            return
        raise SystemExit(f"Unknown eval subcommand: {args.eval_command}")

    if args.command == "web":
        connection.close()
        if config_diagnostics:
            for message in format_diagnostics(config_diagnostics):
                print(f"Configuration warning: {message}", file=sys.stderr)
        serve_web(settings, host=args.host, port=args.port)
        return

    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
