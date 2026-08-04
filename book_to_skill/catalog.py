"""Deterministic book metadata catalog and cross-book query helpers.

The generated ``book-index.json`` file is the source of truth for this module.
Markdown frontmatter is deliberately not parsed here: it is a human/Obsidian
projection and a malformed projection must not silently change the global
index.  The generator's own integrity step can compare the projection with the
manifest when it creates a book.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


SCHEMA_VERSION = 1
TAG_NAMESPACES = {"concept", "framework", "method", "theme"}
RELEVANCES = {"primary", "supporting", "mention"}
BASIS_VALUES = {"explicit", "inferred"}
BOOK_FACETS = ("disciplines", "loci", "traditions")
CHAPTER_FACETS = ("loci", "scriptures", "persons")
FACET_NAMES = ("loci", "scriptures", "persons", "disciplines", "traditions")
RELEVANCE_SCORE = {"primary": 2, "supporting": 1, "mention": 0}

_KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TAG_RE = re.compile(r"^([a-z0-9]+(?:-[a-z0-9]+)*)/([a-z0-9]+(?:-[a-z0-9]+)*)$")
_PATH_RE = re.compile(r"^chapters/[a-zA-Z0-9][a-zA-Z0-9._-]*\.md$")
_CHAPTER_ID_RE = re.compile(r"^ch[0-9]+$")
_SCRIPTURE_RE = re.compile(
    r"^(?:[1-3] )?[A-Za-z][A-Za-z0-9.]* "
    r"[1-9][0-9]*(?::[1-9][0-9]*[a-z]?)?"
    r"(?:-[1-9][0-9]*(?::[1-9][0-9]*[a-z]?)?)?$"
)
_SKILL_NAME_RE = re.compile(r"^name:\s*(?P<value>[^#\r\n]+?)\s*$")


class CatalogError(ValueError):
    """Base error for invalid manifests, catalogs, and queries."""


class ManifestError(CatalogError):
    """Raised when a book manifest cannot be loaded or validated."""


class QueryError(CatalogError):
    """Raised for invalid query arguments."""


@dataclass(frozen=True)
class CatalogQuery:
    """A validated-in-use query for :func:`query_catalog`.

    Each value in one of the sequence fields is a separate condition.  The
    default ``match='all'`` therefore gives an intersection; ``any`` gives a
    union.  The CLI exposes these as repeatable options.
    """

    tags: Sequence[str] = ()
    terms: Sequence[str] = ()
    scriptures: Sequence[str] = ()
    loci: Sequence[str] = ()
    persons: Sequence[str] = ()
    book: Optional[str] = None
    match: str = "all"
    include_descendants: bool = False
    include_mentions: bool = False
    basis: str = "any"
    limit: int = 20


def normalize_alias(value: str) -> str:
    """Return the stable search key for a human-facing label.

    The order mirrors the v1 contract: Unicode NFKC, trim, collapse internal
    whitespace, then case-fold.  ``split`` intentionally handles tabs and
    other Unicode whitespace in addition to ordinary spaces.
    """

    if not isinstance(value, str):
        raise TypeError("alias must be a string")
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = " ".join(normalized.split())
    return normalized.casefold()


def _display_path(path: Path) -> str:
    return path.as_posix()


def _field(path: str, message: str) -> str:
    return f"{path}: {message}"


def _is_dict(value: Any) -> bool:
    return isinstance(value, dict)


def _required_keys(
    value: Any,
    *,
    allowed: Sequence[str],
    required: Sequence[str],
    path: str,
    errors: List[str],
) -> bool:
    if not _is_dict(value):
        errors.append(_field(path, "must be an object"))
        return False
    allowed_set = set(allowed)
    required_set = set(required)
    for key in sorted(set(value) - allowed_set, key=str):
        errors.append(_field(path, f"unknown field {key!r}"))
    for key in sorted(required_set - set(value), key=str):
        errors.append(_field(f"{path}.{key}", "is required"))
    return True


def _nonempty_string(value: Any, path: str, errors: List[str]) -> bool:
    if not isinstance(value, str) or not value.strip():
        errors.append(_field(path, "must be a non-empty string"))
        return False
    return True


def _string_array(
    value: Any,
    path: str,
    errors: List[str],
    *,
    allow_empty: bool = True,
) -> bool:
    if not isinstance(value, list):
        errors.append(_field(path, "must be an array"))
        return False
    if not allow_empty and not value:
        errors.append(_field(path, "must not be empty"))
    valid = True
    for index, item in enumerate(value):
        if not _nonempty_string(item, f"{path}[{index}]", errors):
            valid = False
    return valid


def _validate_common_ref(
    value: Any,
    path: str,
    errors: List[str],
    *,
    labels: bool,
) -> Optional[str]:
    allowed = ("id", "labels", "relevance", "basis") if labels else (
        "id",
        "relevance",
        "basis",
    )
    required = allowed
    if not _required_keys(value, allowed=allowed, required=required, path=path, errors=errors):
        return None

    identifier = value.get("id")
    if not _nonempty_string(identifier, f"{path}.id", errors):
        identifier = None
    if identifier is not None and identifier.startswith("#"):
        errors.append(_field(f"{path}.id", "must not start with '#'"))

    if labels:
        label_values = value.get("labels")
        if isinstance(label_values, list):
            if not 1 <= len(label_values) <= 8:
                errors.append(_field(f"{path}.labels", "must contain 1-8 labels"))
            seen: Dict[str, str] = {}
            for index, label in enumerate(label_values):
                label_path = f"{path}.labels[{index}]"
                if not _nonempty_string(label, label_path, errors):
                    continue
                key = normalize_alias(label)
                if key in seen:
                    errors.append(
                        _field(
                            label_path,
                            f"duplicates normalized label from {path}.labels[{seen[key]}]",
                        )
                    )
                else:
                    seen[key] = str(index)

    relevance = value.get("relevance")
    if not isinstance(relevance, str) or relevance not in RELEVANCES:
        errors.append(
            _field(
                f"{path}.relevance",
                "must be one of primary, supporting, mention",
            )
        )
    basis = value.get("basis")
    if not isinstance(basis, str) or basis not in BASIS_VALUES:
        errors.append(_field(f"{path}.basis", "must be explicit or inferred"))
    return identifier if isinstance(identifier, str) else None


def _validate_tag_array(value: Any, path: str, errors: List[str]) -> None:
    if not isinstance(value, list):
        errors.append(_field(path, "must be an array"))
        return
    seen: Dict[str, int] = {}
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        identifier = _validate_common_ref(item, item_path, errors, labels=True)
        if identifier is None:
            continue
        match = _TAG_RE.fullmatch(identifier)
        if not match or match.group(1) not in TAG_NAMESPACES:
            errors.append(
                _field(
                    f"{item_path}.id",
                    "must be <namespace>/<kebab-case> using concept, framework, method, or theme",
                )
            )
        if identifier in seen:
            errors.append(
                _field(item_path, f"duplicates id from {path}[{seen[identifier]}]")
            )
        else:
            seen[identifier] = index


def _validate_facet_id(identifier: str, facet: str) -> bool:
    if facet in {"disciplines", "loci"}:
        parts = identifier.split("/")
        return len(parts) >= 2 and all(_KEBAB_RE.fullmatch(part) for part in parts)
    if facet == "traditions":
        return bool(_KEBAB_RE.fullmatch(identifier))
    if facet == "persons":
        return bool(_KEBAB_RE.fullmatch(identifier))
    if facet == "scriptures":
        return bool(_SCRIPTURE_RE.fullmatch(identifier))
    return False


def _validate_facet_array(
    value: Any,
    path: str,
    facet: str,
    errors: List[str],
) -> None:
    if not isinstance(value, list):
        errors.append(_field(path, "must be an array"))
        return
    seen: Dict[str, int] = {}
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        identifier = _validate_common_ref(
            item,
            item_path,
            errors,
            labels=facet == "persons",
        )
        if identifier is None:
            continue
        canonical_identifier = _normalize_facet_id(identifier, facet)
        if not _validate_facet_id(canonical_identifier, facet):
            expected = {
                "disciplines": "a hierarchy such as theology/systematic-theology",
                "loci": "a hierarchy such as dogmatics/christology",
                "traditions": "a kebab-case id",
                "scriptures": "an SBL-style reference such as John 1:14",
                "persons": "a kebab-case canonical id",
            }[facet]
            errors.append(_field(f"{item_path}.id", f"must be {expected}"))
        if canonical_identifier in seen:
            errors.append(
                _field(item_path, f"duplicates id from {path}[{seen[canonical_identifier]}]")
            )
        else:
            seen[canonical_identifier] = index


def _normalize_facet_id(identifier: str, facet: str) -> str:
    if facet == "scriptures":
        value = unicodedata.normalize("NFKC", identifier).strip()
        return " ".join(value.split())
    return identifier


def _safe_chapter_path(raw_path: Any, book_dir: Path, path: str, errors: List[str]) -> None:
    if not isinstance(raw_path, str) or not raw_path:
        errors.append(_field(path, "must be a relative POSIX path"))
        return
    if raw_path.startswith("/") or "\\" in raw_path or not _PATH_RE.fullmatch(raw_path):
        errors.append(
            _field(path, "must be a relative chapters/*.md POSIX path")
        )
        return
    parts = raw_path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        errors.append(_field(path, "must not contain empty, '.' or '..' segments"))
        return

    current = book_dir
    try:
        for part in parts:
            current = current / part
            if current.is_symlink():
                errors.append(_field(path, "must not resolve through a symbolic link"))
                return
        book_root = book_dir.resolve(strict=True)
        resolved = current.resolve(strict=False)
        if resolved != book_root and book_root not in resolved.parents:
            errors.append(_field(path, "resolves outside the book directory"))
            return
    except OSError as exc:
        errors.append(_field(path, f"could not inspect path: {exc}"))
        return

    if not current.exists():
        errors.append(_field(path, "chapter file does not exist"))
    elif not current.is_file():
        errors.append(_field(path, "chapter path is not a regular file"))


def _read_skill_name(skill_path: Path) -> Optional[str]:
    try:
        text = skill_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        match = _SKILL_NAME_RE.match(line)
        if match:
            return match.group("value").strip().strip("\"'")
    return None


def validate_manifest(data: dict, book_dir: Path) -> List[str]:
    """Return all validation errors for a v1 manifest.

    The function is intentionally non-throwing for data errors so callers can
    report multiple JSON field paths at once.  Filesystem errors are reported
    in the same list.
    """

    errors: List[str] = []
    book_dir = Path(book_dir)
    root_path = _display_path(book_dir / "book-index.json")

    if book_dir.is_symlink():
        errors.append(_field(_display_path(book_dir), "book directory must not be a symbolic link"))
    elif not book_dir.is_dir():
        errors.append(_field(_display_path(book_dir), "book directory is missing"))

    if not _required_keys(
        data,
        allowed=("schema_version", "book", "chapters"),
        required=("schema_version", "book", "chapters"),
        path=f"{root_path}: $",
        errors=errors,
    ):
        return errors

    if type(data.get("schema_version")) is not int or data.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            _field(
                f"{root_path}: $.schema_version",
                f"must be integer {SCHEMA_VERSION}",
            )
        )

    book = data.get("book")
    if _required_keys(
        book,
        allowed=("id", "title", "authors", "lens", "tags", "facets"),
        required=("id", "title", "authors", "lens", "tags", "facets"),
        path=f"{root_path}: $.book",
        errors=errors,
    ):
        book_id = book.get("id")
        if _nonempty_string(book_id, f"{root_path}: $.book.id", errors):
            if not _KEBAB_RE.fullmatch(book_id):
                errors.append(
                    _field(
                        f"{root_path}: $.book.id",
                        "must be lowercase ASCII kebab-case",
                    )
                )
            if book_dir.name != book_id:
                errors.append(
                    _field(
                        f"{root_path}: $.book.id",
                        f"must match book directory name {book_dir.name!r}",
                    )
                )
        _nonempty_string(book.get("title"), f"{root_path}: $.book.title", errors)
        if _string_array(book.get("authors"), f"{root_path}: $.book.authors", errors):
            authors = book.get("authors")
            if len(authors) != len(set(authors)):
                errors.append(_field(f"{root_path}: $.book.authors", "contains duplicates"))
        lens = book.get("lens")
        if not isinstance(lens, str) or lens not in {"general", "theology", "philosophy"}:
            errors.append(
                _field(
                    f"{root_path}: $.book.lens",
                    "must be general, theology, or philosophy",
                )
            )
        _validate_tag_array(book.get("tags"), f"{root_path}: $.book.tags", errors)
        facets = book.get("facets")
        if _required_keys(
            facets,
            allowed=BOOK_FACETS,
            required=BOOK_FACETS,
            path=f"{root_path}: $.book.facets",
            errors=errors,
        ):
            for facet in BOOK_FACETS:
                _validate_facet_array(
                    facets.get(facet),
                    f"{root_path}: $.book.facets.{facet}",
                    facet,
                    errors,
                )

        skill_path = book_dir / "SKILL.md"
        if skill_path.is_symlink():
            errors.append(_field(_display_path(skill_path), "must not be a symbolic link"))
        elif not skill_path.is_file():
            errors.append(_field(_display_path(skill_path), "is missing"))
        else:
            skill_name = _read_skill_name(skill_path)
            if skill_name != book_id:
                errors.append(
                    _field(
                        f"{root_path}: $.book.id",
                        f"must match SKILL.md name {skill_name!r}",
                    )
                )

    chapters = data.get("chapters")
    chapter_ids: Dict[str, int] = {}
    chapter_paths: Dict[str, int] = {}
    if not isinstance(chapters, list):
        errors.append(_field(f"{root_path}: $.chapters", "must be an array"))
    else:
        for index, chapter in enumerate(chapters):
            chapter_path = f"{root_path}: $.chapters[{index}]"
            if not _required_keys(
                chapter,
                allowed=("id", "number", "slug", "title", "path", "tags", "facets"),
                required=("id", "number", "slug", "title", "path", "tags", "facets"),
                path=chapter_path,
                errors=errors,
            ):
                continue
            chapter_id = chapter.get("id")
            if not _nonempty_string(chapter_id, f"{chapter_path}.id", errors):
                chapter_id = None
            elif not _CHAPTER_ID_RE.fullmatch(chapter_id):
                errors.append(_field(f"{chapter_path}.id", "must look like ch01 or ch00"))
            elif chapter_id in chapter_ids:
                errors.append(
                    _field(
                        f"{chapter_path}.id",
                        f"duplicates id from $.chapters[{chapter_ids[chapter_id]}]",
                    )
                )
            else:
                chapter_ids[chapter_id] = index

            number = chapter.get("number")
            if number is not None and (
                isinstance(number, bool) or not isinstance(number, int) or number < 0
            ):
                errors.append(_field(f"{chapter_path}.number", "must be a non-negative integer or null"))
            slug = chapter.get("slug")
            if not _nonempty_string(slug, f"{chapter_path}.slug", errors):
                pass
            elif not _KEBAB_RE.fullmatch(slug):
                errors.append(_field(f"{chapter_path}.slug", "must be lowercase ASCII kebab-case"))
            _nonempty_string(chapter.get("title"), f"{chapter_path}.title", errors)
            chapter_file = chapter.get("path")
            if isinstance(chapter_file, str) and chapter_file in chapter_paths:
                errors.append(
                    _field(
                        f"{chapter_path}.path",
                        f"duplicates path from $.chapters[{chapter_paths[chapter_file]}]",
                    )
                )
            elif isinstance(chapter_file, str):
                chapter_paths[chapter_file] = index
            _safe_chapter_path(
                chapter_file,
                book_dir,
                f"{chapter_path}.path",
                errors,
            )
            _validate_tag_array(chapter.get("tags"), f"{chapter_path}.tags", errors)
            facets = chapter.get("facets")
            if _required_keys(
                facets,
                allowed=CHAPTER_FACETS,
                required=CHAPTER_FACETS,
                path=f"{chapter_path}.facets",
                errors=errors,
            ):
                for facet in CHAPTER_FACETS:
                    _validate_facet_array(
                        facets.get(facet),
                        f"{chapter_path}.facets.{facet}",
                        facet,
                        errors,
                    )

    return errors


def manifest_warnings(data: Mapping[str, Any], manifest_path: Optional[Path] = None) -> List[str]:
    """Return non-fatal quality warnings for sparse tag arrays.

    The v1 contract permits sparse arrays because a book may genuinely have no
    stable taxonomy yet.  The builder reports these warnings but still keeps
    strict validation for malformed data.
    """

    prefix = f"{manifest_path}: " if manifest_path is not None else ""
    warnings: List[str] = []
    book = data.get("book", {}) if isinstance(data, Mapping) else {}
    if isinstance(book, Mapping):
        tags = book.get("tags")
        if isinstance(tags, list) and not 3 <= len(tags) <= 8:
            warnings.append(
                f"{prefix}$.book.tags has {len(tags)} entries; 3-8 is recommended"
            )
    chapters = data.get("chapters", []) if isinstance(data, Mapping) else []
    if isinstance(chapters, list):
        for index, chapter in enumerate(chapters):
            if not isinstance(chapter, Mapping):
                continue
            tags = chapter.get("tags")
            if isinstance(tags, list) and not 3 <= len(tags) <= 8:
                warnings.append(
                    f"{prefix}$.chapters[{index}].tags has {len(tags)} entries; 3-8 is recommended"
                )
    return warnings


def load_manifest(path: Path) -> dict:
    """Load and strictly validate one ``book-index.json`` file."""

    manifest_path = Path(path)
    if manifest_path.is_symlink():
        raise ManifestError(f"{manifest_path}: manifest must not be a symbolic link")
    if manifest_path.name != "book-index.json":
        raise ManifestError(f"{manifest_path}: expected filename book-index.json")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{manifest_path}: invalid JSON at line {exc.lineno}, column {exc.colno}") from exc
    except UnicodeDecodeError as exc:
        raise ManifestError(f"{manifest_path}: file is not valid UTF-8") from exc
    except OSError as exc:
        raise ManifestError(f"{manifest_path}: could not read manifest: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError(f"{manifest_path}: root must be a JSON object")
    errors = validate_manifest(data, manifest_path.parent)
    if errors:
        raise ManifestError("\n".join(errors))
    return data


def _books_root(path: Path) -> Path:
    requested = Path(path)
    if requested.is_symlink():
        raise CatalogError(f"{requested}: books root must not be a symbolic link")
    try:
        root = requested.resolve(strict=True)
    except OSError as exc:
        raise CatalogError(f"{requested}: books root does not exist") from exc
    if not root.is_dir():
        raise CatalogError(f"{requested}: books root is not a directory")
    return root


def discover_manifests(books_root: Path) -> List[Path]:
    """Discover every direct child book that has ``SKILL.md``.

    A candidate without a manifest is an explicit migration error rather than
    a silently omitted book.  Other directories and files in the root are
    ignored so generated catalog outputs can live beside book directories.
    """

    root = _books_root(books_root)
    manifests: List[Path] = []
    try:
        children = sorted(root.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise CatalogError(f"{root}: could not enumerate books root: {exc}") from exc
    for child in children:
        if child.name in {"catalog.json", "INDEX.md"}:
            continue
        if child.is_symlink():
            if (child / "SKILL.md").exists():
                raise CatalogError(f"{child}: book directory must not be a symbolic link")
            continue
        if not child.is_dir():
            continue
        skill_path = child / "SKILL.md"
        if skill_path.is_symlink():
            raise CatalogError(f"{skill_path}: SKILL.md must not be a symbolic link")
        if not skill_path.is_file():
            continue
        manifest_path = child / "book-index.json"
        if not manifest_path.exists():
            raise CatalogError(
                f"{child}: migration required; SKILL.md exists but book-index.json is missing"
            )
        if manifest_path.is_symlink():
            raise CatalogError(f"{manifest_path}: manifest must not be a symbolic link")
        if not manifest_path.is_file():
            raise CatalogError(f"{manifest_path}: manifest is not a regular file")
        manifests.append(manifest_path)
    return manifests


def _sorted_labels(labels: Sequence[str]) -> List[str]:
    return sorted(labels, key=lambda value: (normalize_alias(value), value))


def _canonical_ref(ref: Mapping[str, Any], *, facet: Optional[str] = None) -> Dict[str, Any]:
    result: Dict[str, Any] = {"id": _normalize_facet_id(ref["id"], facet) if facet else ref["id"]}
    if "labels" in ref:
        result["labels"] = _sorted_labels(ref["labels"])
    result["relevance"] = ref["relevance"]
    result["basis"] = ref["basis"]
    return result


def _canonical_manifest(data: Mapping[str, Any]) -> dict:
    book = data["book"]
    canonical_book: Dict[str, Any] = {
        "id": book["id"],
        "title": book["title"],
        "authors": list(book["authors"]),
        "lens": book["lens"],
        "tags": sorted(
            (_canonical_ref(ref) for ref in book["tags"]),
            key=lambda ref: ref["id"],
        ),
        "facets": {
            facet: sorted(
                (_canonical_ref(ref, facet=facet) for ref in book["facets"][facet]),
                key=lambda ref: ref["id"],
            )
            for facet in BOOK_FACETS
        },
    }
    chapters: List[Dict[str, Any]] = []
    for chapter in data["chapters"]:
        chapters.append(
            {
                "id": chapter["id"],
                "number": chapter["number"],
                "slug": chapter["slug"],
                "title": chapter["title"],
                "path": chapter["path"],
                "tags": sorted(
                    (_canonical_ref(ref) for ref in chapter["tags"]),
                    key=lambda ref: ref["id"],
                ),
                "facets": {
                    facet: sorted(
                        (_canonical_ref(ref, facet=facet) for ref in chapter["facets"][facet]),
                        key=lambda ref: ref["id"],
                    )
                    for facet in CHAPTER_FACETS
                },
            }
        )
    chapters.sort(
        key=lambda chapter: (
            chapter["number"] is None,
            chapter["number"] if chapter["number"] is not None else -1,
            chapter["id"],
        )
    )
    return {"schema_version": SCHEMA_VERSION, "book": canonical_book, "chapters": chapters}


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve(strict=True).relative_to(root).as_posix()
    except (OSError, ValueError) as exc:
        raise CatalogError(f"{path}: path is outside books root") from exc


def _occurrence(
    book_id: str,
    path: str,
    ref: Mapping[str, Any],
    chapter_id: Optional[str] = None,
) -> dict:
    result: Dict[str, Any] = {
        "book_id": book_id,
        "path": path,
        "relevance": ref["relevance"],
        "basis": ref["basis"],
    }
    if chapter_id is not None:
        result["chapter_id"] = chapter_id
    return result


def _occurrence_sort_key(item: Mapping[str, Any]) -> Tuple[str, str, str, int, str]:
    return (
        str(item.get("book_id", "")),
        str(item.get("chapter_id", "")),
        str(item.get("path", "")),
        -RELEVANCE_SCORE.get(str(item.get("relevance", "")), -1),
        str(item.get("basis", "")),
    )


def build_catalog(
    manifests: Sequence[Tuple[Path, dict]],
    books_root: Path,
) -> dict:
    """Build a deterministic global catalog from validated manifests."""

    root = _books_root(books_root)
    normalized: List[Tuple[Path, dict]] = []
    errors: List[str] = []
    for manifest_path, data in manifests:
        path = Path(manifest_path)
        if path.is_symlink():
            errors.append(f"{path}: manifest must not be a symbolic link")
            continue
        try:
            resolved_manifest = path.resolve(strict=True)
            relative_manifest = resolved_manifest.relative_to(root)
            if len(relative_manifest.parts) != 2:
                errors.append(f"{path}: manifest must be in a direct child book directory")
                continue
        except (OSError, ValueError) as exc:
            errors.append(f"{path}: manifest must be inside books root")
            continue
        if not isinstance(data, dict):
            errors.append(f"{path}: manifest root must be an object")
            continue
        manifest_errors = validate_manifest(data, path.parent)
        if manifest_errors:
            errors.extend(manifest_errors)
            continue
        normalized.append((path, _canonical_manifest(data)))
    if errors:
        raise ManifestError("\n".join(errors))

    normalized.sort(key=lambda pair: pair[1]["book"]["id"])
    book_ids: Dict[str, Path] = {}
    for path, manifest in normalized:
        book_id = manifest["book"]["id"]
        if book_id in book_ids:
            raise ManifestError(
                f"{path}: $.book.id duplicates {book_ids[book_id]} ({book_id!r})"
            )
        book_ids[book_id] = path

    books: Dict[str, dict] = {}
    term_data: Dict[str, Dict[str, Any]] = {}
    facet_data: Dict[str, Dict[str, Dict[str, Any]]] = {
        facet: {} for facet in FACET_NAMES
    }
    alias_targets: Dict[str, set] = {}

    def add_aliases(ref: Mapping[str, Any], kind: str) -> None:
        for label in ref.get("labels", []):
            key = normalize_alias(label)
            alias_targets.setdefault(key, set()).add((kind, ref["id"]))

    def add_term(ref: Mapping[str, Any], occurrence: dict) -> None:
        identifier = ref["id"]
        entry = term_data.setdefault(identifier, {"labels_by_key": {}, "occurrences": []})
        for label in ref["labels"]:
            key = normalize_alias(label)
            current = entry["labels_by_key"].get(key)
            if current is None or label < current:
                entry["labels_by_key"][key] = label
        entry["occurrences"].append(occurrence)
        add_aliases(ref, "tag")

    def add_facet(facet: str, ref: Mapping[str, Any], occurrence: dict) -> None:
        identifier = ref["id"]
        entry = facet_data[facet].setdefault(identifier, {"occurrences": []})
        entry["occurrences"].append(occurrence)
        if facet == "persons":
            labels_by_key = entry.setdefault("labels_by_key", {})
            for label in ref["labels"]:
                key = normalize_alias(label)
                current = labels_by_key.get(key)
                if current is None or label < current:
                    labels_by_key[key] = label
            add_aliases(ref, "person")

    for manifest_path, manifest in normalized:
        book = manifest["book"]
        book_id = book["id"]
        book_dir = manifest_path.parent
        skill_path = _relative_path(book_dir / "SKILL.md", root)
        manifest_rel = _relative_path(manifest_path, root)
        chapter_lookup: Dict[str, dict] = {}
        for chapter in manifest["chapters"]:
            chapter_lookup[chapter["id"]] = {
                "number": chapter["number"],
                "slug": chapter["slug"],
                "title": chapter["title"],
                "path": f"{book_id}/{chapter['path']}",
                "tags": chapter["tags"],
                "facets": chapter["facets"],
            }

        books[book_id] = {
            "title": book["title"],
            "authors": book["authors"],
            "lens": book["lens"],
            "path": skill_path,
            "manifest": manifest_rel,
            "tags": book["tags"],
            "facets": book["facets"],
            "chapters": chapter_lookup,
        }

        for ref in book["tags"]:
            add_term(ref, _occurrence(book_id, skill_path, ref))
        for facet in BOOK_FACETS:
            for ref in book["facets"][facet]:
                add_facet(facet, ref, _occurrence(book_id, skill_path, ref))
        for chapter in manifest["chapters"]:
            chapter_id = chapter["id"]
            chapter_path = f"{book_id}/{chapter['path']}"
            for ref in chapter["tags"]:
                add_term(ref, _occurrence(book_id, chapter_path, ref, chapter_id))
            for facet in CHAPTER_FACETS:
                for ref in chapter["facets"][facet]:
                    add_facet(facet, ref, _occurrence(book_id, chapter_path, ref, chapter_id))

    terms: Dict[str, dict] = {}
    for identifier in sorted(term_data):
        raw = term_data[identifier]
        terms[identifier] = {
            "labels": [raw["labels_by_key"][key] for key in sorted(raw["labels_by_key"])],
            "occurrences": sorted(raw["occurrences"], key=_occurrence_sort_key),
        }

    facets: Dict[str, dict] = {}
    for facet in FACET_NAMES:
        facets[facet] = {}
        for identifier in sorted(facet_data[facet]):
            raw = facet_data[facet][identifier]
            entry: Dict[str, Any] = {}
            if facet == "persons":
                entry["labels"] = [
                    raw["labels_by_key"][key] for key in sorted(raw["labels_by_key"])
                ]
            entry["occurrences"] = sorted(raw["occurrences"], key=_occurrence_sort_key)
            facets[facet][identifier] = entry

    aliases = {
        key: [
            {"kind": kind, "id": identifier}
            for kind, identifier in sorted(targets, key=lambda item: (item[0], item[1]))
        ]
        for key, targets in sorted(alias_targets.items())
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "books": books,
        "terms": terms,
        "facets": facets,
        "aliases": aliases,
    }


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _markdown_safe(value: Any) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    return (
        text.replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("*", "\\*")
        .replace("_", "\\_")
    )


def _markdown_link(label: str, path: str) -> str:
    return f"[{_markdown_safe(label)}]({path})"


def render_index(catalog: dict) -> str:
    """Render the human-readable deterministic ``INDEX.md`` projection."""

    books = catalog.get("books", {})
    lines = [
        "# Global Books Knowledge Matrix",
        "",
        "Generated from validated `book-index.json` manifests.",
        "",
        "## Books",
        "",
    ]
    for book_id in sorted(books):
        book = books[book_id]
        author_text = ", ".join(_markdown_safe(author) for author in book.get("authors", []))
        suffix = f" — {author_text}" if author_text else ""
        chapter_count = len(book.get("chapters", {}))
        lines.append(
            f"- {_markdown_link(book.get('title', book_id), book['path'])} "
            f"(`{_markdown_safe(book_id)}`, {chapter_count} chapters){suffix}"
        )

    def append_inverse_section(title: str, key: str) -> None:
        lines.extend(["", f"## {title}", ""])
        inverse = catalog.get("terms", {}) if key == "terms" else catalog.get("facets", {}).get(key, {})
        if not inverse:
            lines.append("_No indexed entries._")
            return
        for identifier in sorted(inverse):
            entry = inverse[identifier]
            labels = entry.get("labels", [])
            label_suffix = f" — {', '.join(_markdown_safe(label) for label in labels)}" if labels else ""
            lines.append(f"### `{_markdown_safe(identifier)}`{label_suffix}")
            occurrences = sorted(entry.get("occurrences", []), key=_occurrence_sort_key)
            for occurrence in occurrences:
                book = books.get(occurrence.get("book_id"), {})
                book_title = book.get("title", occurrence.get("book_id", ""))
                chapter_id = occurrence.get("chapter_id")
                if chapter_id:
                    chapter = book.get("chapters", {}).get(chapter_id, {})
                    number = chapter.get("number")
                    chapter_label = f"Ch {number}" if number is not None else chapter_id
                    label = f"{book_title}: {chapter_label} — {chapter.get('title', chapter_id)}"
                else:
                    label = f"{book_title} (book)"
                details = f"{occurrence.get('relevance')}; {occurrence.get('basis')}"
                lines.append(
                    f"- {_markdown_link(label, occurrence['path'])} ({details})"
                )

    append_inverse_section("Tags", "terms")
    append_inverse_section("Loci", "loci")
    append_inverse_section("Scriptures", "scriptures")
    append_inverse_section("Persons", "persons")
    append_inverse_section("Disciplines", "disciplines")
    append_inverse_section("Traditions", "traditions")
    return "\n".join(lines).rstrip() + "\n"


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def write_outputs_atomic(catalog: dict, books_root: Path) -> None:
    """Atomically replace INDEX.md and catalog.json after both are prepared."""

    root = _books_root(books_root)
    index_payload = render_index(catalog).encode("utf-8")
    catalog_payload = _json_bytes(catalog)

    index_path = root / "INDEX.md"
    catalog_path = root / "catalog.json"
    index_temp: Optional[str] = None
    catalog_temp: Optional[str] = None
    try:
        for target, payload in ((index_path, index_payload), (catalog_path, catalog_payload)):
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=str(root),
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
                if target == index_path:
                    index_temp = handle.name
                else:
                    catalog_temp = handle.name
        if index_temp is None or catalog_temp is None:
            raise CatalogError("could not prepare catalog output files")
        os.replace(index_temp, index_path)
        index_temp = None
        os.replace(catalog_temp, catalog_path)
        catalog_temp = None
    finally:
        for temporary in (index_temp, catalog_temp):
            if temporary:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass


def load_catalog(path: Path) -> dict:
    """Load the generated catalog with lightweight shape validation."""

    catalog_path = Path(path)
    if catalog_path.is_symlink():
        raise CatalogError(f"{catalog_path}: catalog must not be a symbolic link")
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise CatalogError(f"{catalog_path}: invalid JSON at line {exc.lineno}, column {exc.colno}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise CatalogError(f"{catalog_path}: could not read catalog") from exc
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data.get("schema_version") != SCHEMA_VERSION:
        raise CatalogError(f"{catalog_path}: unsupported or missing schema_version 1")
    for key in ("books", "terms", "facets", "aliases"):
        if not isinstance(data.get(key), dict):
            raise CatalogError(f"{catalog_path}: $.{key} must be an object")
    return data


def _as_values(value: Any) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, (list, tuple)):
        raise QueryError("query values must be strings or arrays of strings")
    if not all(isinstance(item, str) for item in value):
        raise QueryError("query values must be strings")
    return tuple(value)


def _query_from_mapping(value: Mapping[str, Any]) -> CatalogQuery:
    data = dict(value)
    aliases = {
        "tag": "tags",
        "term": "terms",
        "scripture": "scriptures",
        "locus": "loci",
        "person": "persons",
    }
    for old, new in aliases.items():
        if old in data and new not in data:
            data[new] = data.pop(old)
    allowed = set(CatalogQuery.__dataclass_fields__)
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise QueryError(f"unknown query field(s): {', '.join(unknown)}")
    return CatalogQuery(**data)


@dataclass(frozen=True)
class _Condition:
    kind: str
    value: str
    ids: Tuple[str, ...]


def _validate_query(query: CatalogQuery) -> List[_Condition]:
    if not isinstance(query.match, str) or query.match not in {"all", "any"}:
        raise QueryError("match must be all or any")
    if not isinstance(query.basis, str) or query.basis not in {"any", "explicit", "inferred"}:
        raise QueryError("basis must be any, explicit, or inferred")
    if isinstance(query.limit, bool) or not isinstance(query.limit, int) or not 1 <= query.limit <= 200:
        raise QueryError("limit must be an integer between 1 and 200")
    conditions: List[_Condition] = []
    for value in _as_values(query.tags):
        if not _TAG_RE.fullmatch(value) or value.split("/", 1)[0] not in TAG_NAMESPACES:
            raise QueryError(f"invalid canonical tag id: {value!r}")
        conditions.append(_Condition("tag", value, (value,)))
    for value in _as_values(query.terms):
        if not value.strip() or value.lstrip().startswith("#"):
            raise QueryError("term must be a non-empty label or canonical tag id without '#'")
        conditions.append(_Condition("term", value, ()))
    for value in _as_values(query.scriptures):
        normalized = _normalize_facet_id(value, "scriptures")
        if not _SCRIPTURE_RE.fullmatch(normalized):
            raise QueryError(f"invalid scripture reference: {value!r}")
        conditions.append(_Condition("scripture", normalized, (normalized,)))
    for value in _as_values(query.loci):
        if not _validate_facet_id(value, "loci"):
            raise QueryError(f"invalid locus id: {value!r}")
        conditions.append(_Condition("locus", value, (value,)))
    for value in _as_values(query.persons):
        if not value.strip() or value.lstrip().startswith("#"):
            raise QueryError("person must be a non-empty canonical id or label without '#'")
        conditions.append(_Condition("person", value, ()))
    if query.book is not None and (not isinstance(query.book, str) or not query.book.strip()):
        raise QueryError("book must be a non-empty book id")
    return conditions


def _resolve_condition_ids(catalog: Mapping[str, Any], condition: _Condition) -> Tuple[str, ...]:
    if condition.kind == "tag":
        return (condition.value,) if condition.value in catalog.get("terms", {}) else ()
    if condition.kind == "term":
        if condition.value in catalog.get("terms", {}):
            return (condition.value,)
        alias = catalog.get("aliases", {}).get(normalize_alias(condition.value), [])
        return tuple(
            target["id"]
            for target in alias
            if isinstance(target, dict)
            and target.get("kind") == "tag"
            and target.get("id") in catalog.get("terms", {})
        )
    if condition.kind == "scripture":
        return (condition.value,) if condition.value in catalog.get("facets", {}).get("scriptures", {}) else ()
    if condition.kind == "person":
        persons = catalog.get("facets", {}).get("persons", {})
        if condition.value in persons:
            return (condition.value,)
        alias = catalog.get("aliases", {}).get(normalize_alias(condition.value), [])
        return tuple(
            target["id"]
            for target in alias
            if isinstance(target, dict)
            and target.get("kind") == "person"
            and target.get("id") in persons
        )
    if condition.kind == "locus":
        loci = catalog.get("facets", {}).get("loci", {})
        if condition.value in loci:
            return (condition.value,)
        return ()
    return ()


def _condition_index(catalog: Mapping[str, Any], condition: _Condition) -> Mapping[str, Any]:
    if condition.kind in {"tag", "term"}:
        return catalog.get("terms", {})
    if condition.kind == "locus":
        return catalog.get("facets", {}).get("loci", {})
    if condition.kind == "scripture":
        return catalog.get("facets", {}).get("scriptures", {})
    if condition.kind == "person":
        return catalog.get("facets", {}).get("persons", {})
    return {}


def _allowed_occurrence(occurrence: Mapping[str, Any], query: CatalogQuery) -> bool:
    if not query.include_mentions and occurrence.get("relevance") == "mention":
        return False
    return query.basis == "any" or occurrence.get("basis") == query.basis


def _hit_map(
    catalog: Mapping[str, Any],
    condition: _Condition,
    query: CatalogQuery,
) -> Dict[str, Dict[Optional[str], List[dict]]]:
    ids = list(condition.ids)
    if condition.kind == "locus" and query.include_descendants:
        loci = catalog.get("facets", {}).get("loci", {})
        ids = [
            identifier
            for identifier in loci
            if identifier == condition.value or identifier.startswith(condition.value + "/")
        ]
    else:
        ids = list(_resolve_condition_ids(catalog, condition))
    result: Dict[str, Dict[Optional[str], List[dict]]] = {}
    index = _condition_index(catalog, condition)
    for identifier in sorted(set(ids)):
        entry = index.get(identifier, {})
        for raw_occurrence in entry.get("occurrences", []):
            if not isinstance(raw_occurrence, dict) or not _allowed_occurrence(raw_occurrence, query):
                continue
            book_id = raw_occurrence.get("book_id")
            if not isinstance(book_id, str):
                continue
            chapter_id = raw_occurrence.get("chapter_id")
            hit = dict(raw_occurrence)
            hit["id"] = identifier
            result.setdefault(book_id, {}).setdefault(chapter_id, []).append(hit)
    return result


def _hit_sort_key(hit: Mapping[str, Any]) -> Tuple[int, int, str, str, str]:
    return (
        -RELEVANCE_SCORE.get(str(hit.get("relevance", "")), -1),
        0 if hit.get("basis") == "explicit" else 1,
        str(hit.get("id", "")),
        str(hit.get("path", "")),
        str(hit.get("chapter_id", "")),
    )


def _format_hit(condition: _Condition, hit: Mapping[str, Any], scope: str) -> dict:
    return {
        "condition": f"{condition.kind}:{condition.value}",
        "kind": condition.kind,
        "id": hit.get("id"),
        "scope": scope,
        "relevance": hit.get("relevance"),
        "basis": hit.get("basis"),
    }


def _best_hit(hits: Sequence[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    if not hits:
        return None
    return sorted(hits, key=_hit_sort_key)[0]


def _chapter_sort_key(item: Tuple[str, Mapping[str, Any]]) -> Tuple[bool, int, str]:
    chapter_id, chapter = item
    number = chapter.get("number")
    return (number is None, number if isinstance(number, int) else -1, chapter_id)


def query_catalog(catalog: dict, query: CatalogQuery) -> List[dict]:
    """Return a small, book-grouped result set for a catalog query."""

    if isinstance(query, Mapping):
        query = _query_from_mapping(query)
    if not isinstance(query, CatalogQuery):
        raise QueryError("query must be a CatalogQuery")
    conditions = _validate_query(query)
    books = catalog.get("books", {})
    if not isinstance(books, dict):
        raise CatalogError("catalog $.books must be an object")
    if query.book is not None:
        candidate_ids = [query.book] if query.book in books else []
    else:
        candidate_ids = sorted(books)

    hit_maps = [_hit_map(catalog, condition, query) for condition in conditions]
    results: List[dict] = []
    for book_id in candidate_ids:
        book = books[book_id]
        book_hits_by_condition: List[List[dict]] = []
        chapter_hits_by_condition: List[Dict[str, List[dict]]] = []
        condition_presence: List[bool] = []
        for hit_map in hit_maps:
            per_book = hit_map.get(book_id, {})
            book_hits = list(per_book.get(None, []))
            chapter_hits = {
                chapter_id: list(hits)
                for chapter_id, hits in per_book.items()
                if chapter_id is not None
            }
            book_hits_by_condition.append(book_hits)
            chapter_hits_by_condition.append(chapter_hits)
            condition_presence.append(bool(book_hits) or bool(chapter_hits))

        if conditions:
            book_matches_condition = (
                all(condition_presence) if query.match == "all" else any(condition_presence)
            )
            if not book_matches_condition:
                continue

        book_matches: List[dict] = []
        for index, condition in enumerate(conditions):
            best = _best_hit(book_hits_by_condition[index])
            if best is not None:
                book_matches.append(_format_hit(condition, best, "book"))

        chapter_results: List[dict] = []
        chapter_lookup = book.get("chapters", {})
        has_any_chapter_hits = any(bool(hits) for hits in chapter_hits_by_condition)
        chapter_ids = (
            sorted(chapter_lookup.items(), key=_chapter_sort_key)
            if has_any_chapter_hits
            else []
        )
        for chapter_id, chapter in chapter_ids:
            selected: List[Tuple[_Condition, Mapping[str, Any], str]] = []
            has_chapter_hit = False
            for index, condition in enumerate(conditions):
                direct_hits = chapter_hits_by_condition[index].get(chapter_id, [])
                if direct_hits:
                    has_chapter_hit = True
                    best = _best_hit(direct_hits)
                    if best is not None:
                        selected.append((condition, best, "chapter"))
                elif not chapter_hits_by_condition[index]:
                    # A book-level condition can constrain a chapter-level
                    # condition in an AND query.  If this same condition has
                    # chapter occurrences elsewhere, however, those explicit
                    # occurrences are the precise chapter projection and the
                    # broad book occurrence must not fan out to every chapter.
                    best = _best_hit(book_hits_by_condition[index])
                    if best is not None:
                        selected.append((condition, best, "book"))

            if not conditions:
                continue
            satisfied = len(selected)
            if query.match == "all":
                qualifies = satisfied == len(conditions)
            else:
                # Book-level matches are represented by the group-level result;
                # only chapter occurrences create nested results for a union.
                qualifies = has_chapter_hit and any(scope == "chapter" for _, _, scope in selected)
            if not qualifies:
                continue

            formatted_matches = [
                _format_hit(condition, hit, scope) for condition, hit, scope in selected
            ]
            relevance_score = sum(
                RELEVANCE_SCORE.get(str(hit.get("relevance")), 0)
                for _, hit, _ in selected
            )
            chapter_results.append(
                {
                    "chapter_id": chapter_id,
                    "number": chapter.get("number"),
                    "title": chapter.get("title"),
                    "path": chapter.get("path"),
                    "matches": formatted_matches,
                    "match_count": satisfied,
                    "relevance_score": relevance_score,
                }
            )

        chapter_results.sort(
            key=lambda item: (
                -item["match_count"],
                -item["relevance_score"],
                item["chapter_id"],
            )
        )
        if chapter_results:
            group_match_count = max(item["match_count"] for item in chapter_results)
            group_relevance = max(item["relevance_score"] for item in chapter_results)
        else:
            group_match_count = len(book_matches)
            group_relevance = sum(
                RELEVANCE_SCORE.get(str(match.get("relevance")), 0)
                for match in book_matches
            )

        # A book with only chapter hits from mutually exclusive conditions is
        # not a useful result for an AND query.  Book-level-only matches remain
        # useful and intentionally retain an empty chapters array.
        if conditions and query.match == "all" and not chapter_results and not book_matches:
            continue
        results.append(
            {
                "book_id": book_id,
                "title": book.get("title"),
                "authors": book.get("authors", []),
                "lens": book.get("lens"),
                "path": book.get("path"),
                "matches": book_matches,
                "chapters": chapter_results,
                "match_count": group_match_count,
                "relevance_score": group_relevance,
            }
        )

    results.sort(
        key=lambda item: (
            -item["match_count"],
            -item["relevance_score"],
            item["book_id"],
        )
    )
    # ``limit`` bounds the emitted result locations, not just the number of
    # outer book groups.  This keeps one book with many matching chapters from
    # defeating the small-context contract while retaining the required book
    # grouping in the response.
    bounded: List[dict] = []
    remaining = query.limit
    for result in results:
        if remaining <= 0:
            break
        chapters = result.get("chapters", [])
        if chapters:
            selected_chapters = chapters[:remaining]
            if not selected_chapters:
                break
            bounded_result = dict(result)
            bounded_result["chapters"] = selected_chapters
            bounded.append(bounded_result)
            remaining -= len(selected_chapters)
        else:
            bounded.append(result)
            remaining -= 1
    return bounded


__all__ = [
    "BASIS_VALUES",
    "CatalogError",
    "CatalogQuery",
    "CHAPTER_FACETS",
    "FACET_NAMES",
    "ManifestError",
    "QueryError",
    "SCHEMA_VERSION",
    "TAG_NAMESPACES",
    "build_catalog",
    "discover_manifests",
    "load_catalog",
    "load_manifest",
    "manifest_warnings",
    "normalize_alias",
    "query_catalog",
    "render_index",
    "validate_manifest",
    "write_outputs_atomic",
]
