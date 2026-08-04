#!/usr/bin/env python3
"""Build the deterministic cross-book catalog from book-index.json files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from book_to_skill.catalog import (  # noqa: E402
    CatalogError,
    build_catalog,
    discover_manifests,
    load_manifest,
    manifest_warnings,
    write_outputs_atomic,
)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--books-root",
        required=True,
        type=Path,
        help="absolute or relative root containing one directory per generated book",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate and build the model without writing catalog.json or INDEX.md",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    try:
        manifest_paths = discover_manifests(args.books_root)
        manifests = []
        warnings = []
        for path in manifest_paths:
            manifest = load_manifest(path)
            manifests.append((path, manifest))
            warning_path = path.resolve().relative_to(args.books_root.resolve())
            warnings.extend(manifest_warnings(manifest, warning_path))
        catalog = build_catalog(manifests, args.books_root)
        if not args.check:
            write_outputs_atomic(catalog, args.books_root)
    except (CatalogError, OSError) as exc:
        print(f"ERROR book catalog build failed: {exc}", file=sys.stderr)
        return 1

    books = len(catalog["books"])
    chapters = sum(len(book["chapters"]) for book in catalog["books"].values())
    terms = len(catalog["terms"])
    mode = "check passed" if args.check else "built"
    for warning in warnings:
        print(f"WARN {warning}", file=sys.stderr)
    print(
        f"Book catalog {mode}: books={books}, chapters={chapters}, terms={terms}; "
        "outputs=INDEX.md,catalog.json"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
