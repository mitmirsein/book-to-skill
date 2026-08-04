#!/usr/bin/env python3
"""Query a generated book catalog without loading the full catalog into output."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from book_to_skill.catalog import (  # noqa: E402
    CatalogError,
    CatalogQuery,
    QueryError,
    load_catalog,
    query_catalog,
)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True, type=Path, help="path to catalog.json")
    parser.add_argument("--tag", action="append", default=[], help="canonical tag id; repeatable")
    parser.add_argument("--term", action="append", default=[], help="tag label or canonical tag id; repeatable")
    parser.add_argument("--scripture", action="append", default=[], help="exact SBL-style scripture id; repeatable")
    parser.add_argument("--locus", action="append", default=[], help="exact locus id; repeatable")
    parser.add_argument("--include-descendants", action="store_true", help="include child locus paths")
    parser.add_argument("--person", action="append", default=[], help="canonical person id or label; repeatable")
    parser.add_argument("--book", help="restrict results to one book id")
    parser.add_argument("--match", choices=("all", "any"), default="all", help="AND or OR semantics")
    parser.add_argument("--include-mentions", action="store_true", help="include relevance=mention occurrences")
    parser.add_argument("--basis", choices=("any", "explicit", "inferred"), default="any")
    parser.add_argument("--limit", type=int, default=20, help="maximum emitted book/chapter result locations (1-200)")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    return parser.parse_args(argv)


def _render_markdown(results):
    lines = ["# Book Catalog Query", "", f"Results: {len(results)}", ""]
    for result in results:
        lines.append(f"## {result['title']} (`{result['book_id']}`)")
        lines.append("")
        lines.append(f"- Skill: [{result['path']}]({result['path']})")
        if result.get("matches"):
            lines.append("- Book matches:")
            for match in result["matches"]:
                lines.append(
                    f"  - {match['condition']} — {match['relevance']}; {match['basis']}"
                )
        if result.get("chapters"):
            lines.append("- Chapters:")
            for chapter in result["chapters"]:
                lines.append(
                    f"  - [{chapter['title']}]({chapter['path']}) "
                    f"(`{chapter['chapter_id']}`; {chapter['match_count']} conditions)"
                )
                for match in chapter["matches"]:
                    lines.append(
                        f"    - {match['condition']} — {match['relevance']}; {match['basis']}"
                    )
        else:
            lines.append("- Chapters: none (book-level match)")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv=None) -> int:
    args = _parse_args(argv)
    query = CatalogQuery(
        tags=args.tag,
        terms=args.term,
        scriptures=args.scripture,
        loci=args.locus,
        persons=args.person,
        book=args.book,
        match=args.match,
        include_descendants=args.include_descendants,
        include_mentions=args.include_mentions,
        basis=args.basis,
        limit=args.limit,
    )
    try:
        catalog = load_catalog(args.catalog)
        results = query_catalog(catalog, query)
    except QueryError as exc:
        print(f"ERROR invalid book catalog query: {exc}", file=sys.stderr)
        return 2
    except CatalogError as exc:
        print(f"ERROR book catalog query failed: {exc}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps({"schema_version": 1, "results": results}, ensure_ascii=False, indent=2))
    else:
        print(_render_markdown(results), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
