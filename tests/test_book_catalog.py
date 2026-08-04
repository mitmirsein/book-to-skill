"""Contract tests for deterministic cross-book tagging and indexing."""

import json
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from book_to_skill.catalog import (  # noqa: E402
    CatalogQuery,
    ManifestError,
    build_catalog,
    discover_manifests,
    load_manifest,
    normalize_alias,
    query_catalog,
    validate_manifest,
    write_outputs_atomic,
)


def _ref(identifier, labels=None, relevance="primary", basis="explicit"):
    result = {"id": identifier, "relevance": relevance, "basis": basis}
    if labels is not None:
        result["labels"] = labels
    return result


def _manifest(book_id, title, chapters, *, book_tag=None):
    return {
        "schema_version": 1,
        "book": {
            "id": book_id,
            "title": title,
            "authors": [title + " Author"],
            "lens": "theology",
            "tags": [
                _ref(
                    book_tag[0],
                    book_tag[1],
                    book_tag[2] if len(book_tag) > 2 else "primary",
                    book_tag[3] if len(book_tag) > 3 else "explicit",
                )
            ]
            if book_tag
            else [],
            "facets": {
                "disciplines": [_ref("theology/systematic-theology", relevance="supporting", basis="inferred")],
                "loci": [_ref("dogmatics/christology", relevance="supporting", basis="inferred")],
                "traditions": [_ref("reformed", relevance="supporting", basis="explicit")],
            },
        },
        "chapters": chapters,
    }


def _chapter(book_root, number, slug, tags=None, *, scriptures=None, persons=None, loci=None):
    chapter_id = f"ch{number:02d}"
    (book_root / "chapters").mkdir(parents=True, exist_ok=True)
    (book_root / "chapters" / f"{chapter_id}-{slug}.md").write_text(
        f"# Chapter {number}: {slug}\n",
        encoding="utf-8",
    )
    return {
        "id": chapter_id,
        "number": number,
        "slug": slug,
        "title": slug.replace("-", " ").title(),
        "path": f"chapters/{chapter_id}-{slug}.md",
        "tags": tags or [],
        "facets": {
            "loci": loci or [],
            "scriptures": scriptures or [],
            "persons": persons or [],
        },
    }


def _write_book(root, book_id, title, chapters, *, book_tag=None):
    book_root = root / book_id
    book_root.mkdir(parents=True, exist_ok=True)
    (book_root / "SKILL.md").write_text(
        f"---\nname: {book_id}\ndescription: {title}\n---\n\n# {title}\n",
        encoding="utf-8",
    )
    manifest = _manifest(book_id, title, chapters, book_tag=book_tag)
    (book_root / "book-index.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return book_root / "book-index.json"


def _make_fixture(tmp_path):
    root = tmp_path / "books"
    root.mkdir()
    incarnation = lambda relevance="primary", basis="explicit": _ref(
        "concept/incarnation", ["Incarnation", "성육신"], relevance, basis
    )
    karl = _ref("karl-barth", ["Karl Barth", "카를 바르트"], "supporting", "explicit")
    book_a_chapters = [
        _chapter(
            root / "book-a",
            1,
            "incarnation-and-word",
            [incarnation()],
            scriptures=[_ref("John 1:14", relevance="primary", basis="explicit")],
            loci=[_ref("dogmatics/christology/incarnation", relevance="primary", basis="inferred")],
        ),
        _chapter(root / "book-a", 2, "incarnation-and-faith", [incarnation("supporting")]),
    ]
    book_b_chapters = [
        _chapter(root / "book-b", 3, "barth-on-incarnation", [incarnation()], persons=[karl]),
    ]
    book_c_chapters = [
        _chapter(
            root / "book-c",
            1,
            "creation",
            [_ref("concept/creation", ["Creation", "창조"])],
            scriptures=[_ref("Gen 1:1-2:4a")],
        )
    ]
    # _chapter creates the chapter directories; create the master files before
    # writing manifests.
    for book_id, title in (("book-a", "Book A"), ("book-b", "Book B"), ("book-c", "Book C")):
        book_root = root / book_id
        book_root.mkdir(exist_ok=True)
        (book_root / "SKILL.md").write_text(
            f"---\nname: {book_id}\ndescription: {title}\n---\n",
            encoding="utf-8",
        )
    # _chapter already wrote the files; write the manifests now.
    paths = [
        _write_book(root, "book-a", "Book A", book_a_chapters, book_tag=("concept/incarnation", ["Incarnation", "성육신"])),
        _write_book(root, "book-b", "Book B", book_b_chapters),
        _write_book(root, "book-c", "Book C", book_c_chapters),
    ]
    return root, paths


def test_normalize_alias_nfkc_whitespace_and_casefold():
    assert normalize_alias("  Ｉncarnation\t    성육신 ") == "incarnation 성육신"


def test_fixture_build_and_query_contract(tmp_path):
    root, paths = _make_fixture(tmp_path)
    manifests = [(path, load_manifest(path)) for path in reversed(paths)]
    catalog = build_catalog(manifests, root)

    term_results = query_catalog(catalog, CatalogQuery(terms=["성육신"]))
    assert [result["book_id"] for result in term_results] == ["book-a", "book-b"]
    assert [chapter["chapter_id"] for chapter in term_results[0]["chapters"]] == ["ch01", "ch02"]
    assert [chapter["chapter_id"] for chapter in term_results[1]["chapters"]] == ["ch03"]

    scripture_results = query_catalog(catalog, CatalogQuery(scriptures=["John 1:14"]))
    assert [(result["book_id"], result["chapters"][0]["chapter_id"]) for result in scripture_results] == [
        ("book-a", "ch01")
    ]

    and_results = query_catalog(
        catalog,
        CatalogQuery(terms=["성육신"], scriptures=["John 1:14"]),
    )
    assert [(result["book_id"], [c["chapter_id"] for c in result["chapters"]]) for result in and_results] == [
        ("book-a", ["ch01"])
    ]

    person_results = query_catalog(
        catalog,
        CatalogQuery(terms=["성육신"], persons=["Karl Barth"]),
    )
    assert [(result["book_id"], result["chapters"][0]["chapter_id"]) for result in person_results] == [
        ("book-b", "ch03")
    ]

    any_results = query_catalog(
        catalog,
        CatalogQuery(tags=["concept/creation", "concept/incarnation"], match="any"),
    )
    assert {result["book_id"] for result in any_results} == {"book-a", "book-b", "book-c"}


def test_book_level_only_match_does_not_fan_out_to_every_chapter(tmp_path):
    root = tmp_path / "books"
    root.mkdir()
    book_root = root / "book-only"
    book_root.mkdir()
    (book_root / "chapters").mkdir()
    (book_root / "SKILL.md").write_text(
        "---\nname: book-only\ndescription: Book\n---\n", encoding="utf-8"
    )
    (book_root / "chapters/ch01.md").write_text("# Chapter\n", encoding="utf-8")
    manifest = _manifest(
        "book-only",
        "Book Only",
        [_chapter(book_root, 1, "chapter", [])],
        book_tag=("concept/incarnation", ["Incarnation"]),
    )
    path = book_root / "book-index.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    catalog = build_catalog([(path, load_manifest(path))], root)

    results = query_catalog(catalog, CatalogQuery(tags=["concept/incarnation"]))
    assert len(results) == 1
    assert results[0]["matches"][0]["scope"] == "book"
    assert results[0]["chapters"] == []


def test_locus_descendants_and_mention_filter(tmp_path):
    root, paths = _make_fixture(tmp_path)
    catalog = build_catalog([(path, load_manifest(path)) for path in paths], root)

    exact = query_catalog(catalog, CatalogQuery(loci=["dogmatics/christology"]))
    assert {result["book_id"] for result in exact} == {"book-a", "book-b", "book-c"}
    assert all(result["chapters"] == [] for result in exact)
    descendants = query_catalog(
        catalog,
        CatalogQuery(loci=["dogmatics/christology"], include_descendants=True),
    )
    assert descendants[0]["chapters"][0]["chapter_id"] == "ch01"

    mention_root = tmp_path / "mention-books"
    mention_root.mkdir()
    chapter = _chapter(mention_root / "mention-book", 1, "mention", [_ref(
        "concept/mention-only", ["Mention only"], "mention", "explicit"
    )])
    mention_path = _write_book(mention_root, "mention-book", "Mention Book", [chapter])
    mention_catalog = build_catalog([(mention_path, load_manifest(mention_path))], mention_root)
    assert query_catalog(mention_catalog, CatalogQuery(terms=["Mention only"])) == []
    assert query_catalog(mention_catalog, CatalogQuery(terms=["Mention only"], include_mentions=True))


def test_limit_bounds_nested_result_locations(tmp_path):
    root, paths = _make_fixture(tmp_path)
    catalog = build_catalog([(path, load_manifest(path)) for path in paths], root)

    results = query_catalog(catalog, CatalogQuery(terms=["성육신"], limit=1))

    assert sum(len(result["chapters"]) or 1 for result in results) <= 1


def test_manifest_validation_reports_unknown_and_invalid_fields(tmp_path):
    root = tmp_path / "books"
    root.mkdir()
    book = root / "bad-book"
    book.mkdir()
    (book / "SKILL.md").write_text("---\nname: bad-book\ndescription: bad\n---\n", encoding="utf-8")
    data = _manifest(
        "bad-book",
        "Bad",
        [],
    )
    data["book"]["unexpected"] = True
    data["book"]["tags"] = [_ref("#Incarnation", ["Incarnation"])]
    errors = validate_manifest(data, book)
    assert any("unknown field 'unexpected'" in error for error in errors)
    assert any("must not start with '#'" in error for error in errors)


def test_discover_requires_manifest_for_skill_directory(tmp_path):
    root = tmp_path / "books"
    root.mkdir()
    book = root / "needs-migration"
    book.mkdir()
    (book / "SKILL.md").write_text(
        "---\nname: needs-migration\ndescription: missing manifest\n---\n",
        encoding="utf-8",
    )
    with pytest.raises(Exception, match="migration required"):
        discover_manifests(root)


def test_outputs_are_deterministic_and_stale_terms_disappear(tmp_path):
    root, paths = _make_fixture(tmp_path)
    catalog = build_catalog([(path, load_manifest(path)) for path in paths], root)
    write_outputs_atomic(catalog, root)
    first_catalog = (root / "catalog.json").read_bytes()
    first_index = (root / "INDEX.md").read_bytes()
    write_outputs_atomic(catalog, root)
    assert (root / "catalog.json").read_bytes() == first_catalog
    assert (root / "INDEX.md").read_bytes() == first_index

    book_c = root / "book-c/book-index.json"
    data = load_manifest(book_c)
    data["chapters"][0]["tags"] = []
    book_c.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    updated = build_catalog(
        [(path, load_manifest(path)) for path in discover_manifests(root)], root
    )
    assert "concept/creation" not in updated["terms"]


def test_load_manifest_rejects_missing_chapter_file(tmp_path):
    root = tmp_path / "books"
    root.mkdir()
    book = root / "missing-book"
    book.mkdir()
    (book / "SKILL.md").write_text("---\nname: missing-book\ndescription: bad\n---\n", encoding="utf-8")
    data = _manifest(
        "missing-book",
        "Missing",
        [_chapter(book, 1, "missing", [])],
    )
    chapter_path = book / data["chapters"][0]["path"]
    chapter_path.unlink()
    manifest_path = book / "book-index.json"
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ManifestError, match="chapter file does not exist"):
        load_manifest(manifest_path)
