import argparse
import json
import logging
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from .collect import collect, registry
from .editorial import generate, validate_issue
from .models import Bundle, ProjectEvent, RealityAssumptions
from .quality import validate_public
from .reality import methanol
from .store import Store


def load_bundle(path: Path) -> Bundle:
    return Bundle.model_validate_json(path.read_text())


def curated() -> Bundle:
    combined = {k: [] for k in Bundle.model_fields}
    for path in sorted(Path("data/curated").glob("*.json")):
        raw = json.loads(path.read_text())
        for key, records in raw.items():
            if key not in combined:
                raise ValueError(f"Unknown collection: {key}")
            combined[key].extend(records)
    bundle = Bundle.model_validate(combined)
    validate_public(bundle)
    return bundle


def main():
    from .settings import load_environment

    load_environment()
    parser = argparse.ArgumentParser(description="CCU Intelligence editorial pipeline")
    parser.add_argument(
        "--db", type=Path, default=Path(os.getenv("CCU_DB", "data/runtime/intelligence.sqlite"))
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    coll = sub.add_parser("collect")
    coll.add_argument("--since", type=date.fromisoformat, default=date.today() - timedelta(days=14))
    coll.add_argument("--until", type=date.fromisoformat, default=date.today())
    coll.add_argument("--source")
    coll.add_argument("--limit", type=int, default=50)
    coll.add_argument("--query", default="carbon dioxide utilization")
    imp = sub.add_parser("import")
    imp.add_argument("path", type=Path)
    event = sub.add_parser("apply-event")
    event.add_argument("path", type=Path)
    draft = sub.add_parser("draft")
    draft.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(UTC).date())
    draft.add_argument("--output", type=Path, default=Path("src/content/issues"))
    draft.add_argument("--sample", action="store_true")
    draft.add_argument(
        "--ai-article-id", help="Analyze one real collected article; output must be under data/runtime"
    )
    sub.add_parser("validate")
    sub.add_parser("export")
    sub.add_parser("status")
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("path", type=Path, help="Private review bundle; includes unreviewed candidates")
    calc = sub.add_parser("calculate")
    calc.add_argument("--assumptions", type=Path)
    llm = sub.add_parser("analyze")
    llm.add_argument("path", type=Path, help="Untrusted text file for optional LLM analysis")
    llm.add_argument("--task", default="extraction")
    llm.add_argument(
        "--evidence-id", action="append", default=[], help="Explicit evidence ID from the working bundle"
    )
    args = parser.parse_args()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.command == "validate":
        bundle = curated()
        registry()
        for path in Path("src/content/issues").glob("*.md"):
            validate_issue(path, bundle)
        print("Validated curated records, source registry and publication gates")
        return
    if args.command == "calculate":
        assumptions = (
            RealityAssumptions.model_validate_json(args.assumptions.read_text())
            if args.assumptions
            else RealityAssumptions()
        )
        print(json.dumps(methanol(assumptions), indent=2))
        return
    if args.command == "analyze":
        from .llm import run

        analysis_store = Store(args.db)
        try:
            known = {e.evidence_id for e in analysis_store.bundle().evidence}
            if not set(args.evidence_id).issubset(known):
                raise ValueError("Unknown evidence ID")
            result = run(args.task, args.path.read_text(), args.evidence_id)
        finally:
            analysis_store.close()
        print(
            result.model_dump_json(indent=2)
            if result
            else '{"status":"unavailable", "fallback":"Use deterministic collection or manual ingestion"}'
        )
        return
    if args.command == "export":
        bundle = curated()  # only checked-in, reviewed material; NEVER runtime candidates
        target = Path("public/data")
        target.mkdir(parents=True, exist_ok=True)
        (target / "intelligence.json").write_text(bundle.model_dump_json(indent=2))
        print("Exported curated public data (sample flags preserved)")
        return
    store = Store(args.db)
    try:
        if args.command == "init":
            store.import_bundle(curated())
            print("Initialized SQLite with curated reference and sample records")
        elif args.command == "import":
            store.import_bundle(load_bundle(args.path))
            print("Imported validated bundle")
        elif args.command == "apply-event":
            store.apply_event(ProjectEvent.model_validate_json(args.path.read_text()))
            print("Applied event and preserved history")
        elif args.command == "collect":
            print(
                json.dumps(
                    collect(store, args.since, args.until, args.source, args.limit, args.query), indent=2
                )
            )
        elif args.command == "draft":
            if args.ai_article_id:
                from .ai_draft import generate_ai

                if args.sample:
                    raise ValueError("AI drafts require real metadata, not sample fixtures")
                print(generate_ai(store.bundle(), args.as_of, args.output, args.ai_article_id))
            else:
                print(generate(store.bundle(), args.as_of, args.output, args.sample))
        elif args.command == "snapshot":
            args.path.parent.mkdir(parents=True, exist_ok=True)
            args.path.write_text(store.bundle().model_dump_json(indent=2))
            print("Saved working bundle for review; do not publish candidates")
        elif args.command == "status":
            print(
                json.dumps(
                    [
                        dict(zip(["source", "time", "status", "detail"], r))
                        for r in store.db.execute(
                            "SELECT source_id,at,status,detail FROM retrievals ORDER BY id DESC LIMIT 50"
                        )
                    ],
                    indent=2,
                )
            )
    finally:
        store.close()


if __name__ == "__main__":
    main()
