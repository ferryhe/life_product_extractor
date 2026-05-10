from __future__ import annotations

from collections.abc import Mapping, Sequence
import html
import json
from pathlib import Path
import re
from typing import Any

import jsonschema

from .fixtures import load_fixture_manifest_document, validate_fixture_manifest_document
from .resources import resource_text

LOW_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(contact us|get a quote|speak with an advisor|talk to an advisor)\b", re.IGNORECASE),
    re.compile(r"^\s*(advisor use only|for advisor[- ]supported explanation)\b", re.IGNORECASE),
    re.compile(r"^\s*(privacy|legal|copyright|footer|navigation|menu)\b", re.IGNORECASE),
)


class SectionContractError(ValueError):
    """Raised when sectionization inputs or outputs violate the PR D contract."""


def load_sections_jsonl(path: str | Path) -> list[dict[str, Any]]:
    jsonl_path = Path(path)
    try:
        raw_text = jsonl_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SectionContractError(f"could not read sections JSONL {jsonl_path}: {exc.strerror or exc}") from exc

    documents: list[dict[str, Any]] = []
    for line_number, line in enumerate(raw_text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SectionContractError(f"could not parse sections JSONL line {line_number} in {jsonl_path}: {exc}") from exc
        if not isinstance(data, Mapping):
            raise SectionContractError(f"sections JSONL line {line_number} in {jsonl_path} must be a JSON object")
        document = dict(data)
        validate_sections_document(document)
        documents.append(document)
    return documents


def validate_sections_document(document: Mapping[str, Any]) -> None:
    schema = json.loads(resource_text("schemas/sections_structured.schema.json"))
    try:
        jsonschema.Draft202012Validator(schema).validate(document)
    except jsonschema.ValidationError as exc:
        raise SectionContractError(
            f"sections document does not match sections_structured.schema.json: {exc.message}"
        ) from exc
    _validate_sections_semantics(document)


def sectionize_fixture_manifest_from_path(manifest_path: str | Path) -> list[dict[str, Any]]:
    fixture_manifest_path = Path(manifest_path)
    manifest = load_fixture_manifest_document(fixture_manifest_path)
    validate_fixture_manifest_document(manifest, base_dir=fixture_manifest_path.parent)
    return sectionize_fixture_manifest(manifest, base_dir=fixture_manifest_path.parent)


def sectionize_fixture_manifest(
    manifest: Mapping[str, Any],
    *,
    base_dir: str | Path,
) -> list[dict[str, Any]]:
    validate_fixture_manifest_document(manifest, base_dir=base_dir)

    documents: list[dict[str, Any]] = []
    for document in manifest["documents"]:
        documents.append(_sectionize_document(document, base_dir=Path(base_dir), fixture_set_id=manifest["fixture_set_id"]))
    return documents


def _sectionize_document(
    document: Mapping[str, Any],
    *,
    base_dir: Path,
    fixture_set_id: str,
) -> dict[str, Any]:
    markdown_path = base_dir / document["markdown_path"]
    try:
        raw_text = markdown_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SectionContractError(f"could not read markdown fixture {markdown_path}: {exc.strerror or exc}") from exc

    lines = raw_text.splitlines()
    blocks = _scan_blocks(lines)
    sections = _build_sections(document=document, lines=lines, blocks=blocks)
    tables = _build_table_artifacts(document=document, blocks=blocks, sections=sections)

    payload = {
        "schema_version": "0.1",
        "fixture_set_id": fixture_set_id,
        "document_id": document["fixture_id"],
        "source_catalog_id": document["source_catalog_id"],
        "product_name": document["product_name"],
        "document_role": document["document_role"],
        "source_type": document["source_type"],
        "source_url": document["source_url"],
        "markdown_path": document["markdown_path"],
        "sectionization_strategy": {
            "deterministic": True,
            "html_escaped_quotes": True,
            "low_value_labeling": True,
            "table_artifacts_enabled": True,
        },
        "source_provenance": {
            "raw_line_count": document["provenance"]["raw_line_count"],
            "selected_line_numbers": list(document["provenance"]["selected_line_numbers"]),
            "omitted_line_ranges": list(document["provenance"]["omitted_line_ranges"]),
        },
        "sections": sections,
        "table_artifacts": tables,
    }
    validate_sections_document(payload)
    return payload


def _validate_sections_semantics(document: Mapping[str, Any]) -> None:
    sections = document["sections"]
    section_ids: set[str] = set()
    table_ids: set[str] = set()
    section_ranges: dict[str, tuple[int, int]] = {}
    declared_table_refs: dict[str, set[str]] = {}
    table_owners: dict[str, str] = {}

    for section in sections:
        if section["section_id"] in section_ids:
            raise SectionContractError(f"{document['document_id']}: duplicate section_id {section['section_id']!r}")
        section_ids.add(section["section_id"])
        section_ranges[section["section_id"]] = (int(section["line_start"]), int(section["line_end"]))
        declared_table_refs[section["section_id"]] = set(str(table_id) for table_id in section["table_artifact_ids"])
        if int(section["line_start"]) > int(section["line_end"]):
            raise SectionContractError(f"{section['section_id']}: line_start must be <= line_end")
        if int(section["body_line_start"]) > int(section["body_line_end"]):
            raise SectionContractError(f"{section['section_id']}: body_line_start must be <= body_line_end")
        if int(section["body_line_start"]) < int(section["line_start"]) or int(section["body_line_end"]) > int(section["line_end"]):
            raise SectionContractError(f"{section['section_id']}: body_line range must stay within section line range")
        _validate_escaped_quote(section["source_quote"], owner=section["section_id"])

    valid_section_ids = {section["section_id"] for section in sections}
    seen_table_refs: dict[str, set[str]] = {section_id: set() for section_id in valid_section_ids}
    for artifact in document["table_artifacts"]:
        if artifact["table_id"] in table_ids:
            raise SectionContractError(f"{document['document_id']}: duplicate table_id {artifact['table_id']!r}")
        table_ids.add(artifact["table_id"])
        table_owners[str(artifact["table_id"])] = str(artifact["section_id"])
        if artifact["section_id"] not in valid_section_ids:
            raise SectionContractError(
                f"{document['document_id']}: table artifact {artifact['table_id']!r} references unknown section_id"
            )
        if int(artifact["line_start"]) > int(artifact["line_end"]):
            raise SectionContractError(f"{artifact['table_id']}: line_start must be <= line_end")
        section_line_start, section_line_end = section_ranges[artifact["section_id"]]
        if int(artifact["line_start"]) < section_line_start or int(artifact["line_end"]) > section_line_end:
            raise SectionContractError(
                f"{artifact['table_id']}: table artifact line range must stay within referenced section line range"
            )
        _validate_escaped_quote(artifact["source_quote"], owner=artifact["table_id"])
        seen_table_refs[artifact["section_id"]].add(str(artifact["table_id"]))

    for section_id, table_artifact_ids in declared_table_refs.items():
        unknown_table_ids = sorted(table_id for table_id in table_artifact_ids if table_id not in table_ids)
        if unknown_table_ids:
            raise SectionContractError(f"{section_id}: references unknown table_artifact_ids {unknown_table_ids!r}")
        cross_section_table_ids = sorted(
            table_id for table_id in table_artifact_ids if table_owners.get(table_id) not in {None, section_id}
        )
        if cross_section_table_ids:
            raise SectionContractError(
                f"{section_id}: references table_artifact_ids owned by another section {cross_section_table_ids!r}"
            )
        missing_table_ids = sorted(seen_table_refs[section_id] - table_artifact_ids)
        if missing_table_ids:
            raise SectionContractError(
                f"{section_id}: missing referenced table_artifact_ids for artifacts {missing_table_ids!r}"
            )


def _scan_blocks(lines: Sequence[str]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    line_number = 1
    while line_number <= len(lines):
        line = lines[line_number - 1]
        stripped = line.strip()
        if not stripped:
            line_number += 1
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
        if heading_match is not None:
            blocks.append(
                {
                    "kind": "heading",
                    "line_start": line_number,
                    "line_end": line_number,
                    "level": len(heading_match.group(1)),
                    "text": heading_match.group(2).strip(),
                    "quote": _escape_quote([line]),
                }
            )
            line_number += 1
            continue

        if _is_pipe_table_line(stripped):
            start = line_number
            table_lines = [line]
            line_number += 1
            while line_number <= len(lines) and _is_pipe_table_line(lines[line_number - 1].strip()):
                table_lines.append(lines[line_number - 1])
                line_number += 1
            blocks.append(
                {
                    "kind": "table",
                    "line_start": start,
                    "line_end": line_number - 1,
                    "lines": table_lines,
                    "quote": _escape_quote(table_lines),
                }
            )
            continue

        if stripped.startswith("- "):
            start = line_number
            items = [stripped[2:].strip()]
            bullet_lines = [line]
            line_number += 1
            while line_number <= len(lines):
                candidate = lines[line_number - 1].strip()
                if candidate.startswith("- "):
                    items.append(candidate[2:].strip())
                    bullet_lines.append(lines[line_number - 1])
                    line_number += 1
                    continue
                break
            blocks.append(
                {
                    "kind": "bullet_list",
                    "line_start": start,
                    "line_end": line_number - 1,
                    "items": items,
                    "quote": _escape_quote(bullet_lines),
                }
            )
            continue

        start = line_number
        paragraph_lines = [line]
        line_number += 1
        while line_number <= len(lines):
            candidate = lines[line_number - 1]
            candidate_stripped = candidate.strip()
            if not candidate_stripped:
                break
            if re.match(r"^(#{1,6})\s+", candidate) or candidate_stripped.startswith("- ") or _is_pipe_table_line(candidate_stripped):
                break
            paragraph_lines.append(candidate)
            line_number += 1
        blocks.append(
            {
                "kind": "paragraph",
                "line_start": start,
                "line_end": line_number - 1,
                "text": " ".join(part.strip() for part in paragraph_lines),
                "quote": _escape_quote(paragraph_lines),
            }
        )

    return blocks


def _build_sections(
    *,
    document: Mapping[str, Any],
    lines: Sequence[str],
    blocks: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    section_specs: list[dict[str, Any]] = []
    heading_stack: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for block in blocks:
        if block["kind"] == "heading":
            if current is not None:
                section_specs.append(current)
            level = int(block["level"])
            while heading_stack and int(heading_stack[-1]["level"]) >= level:
                heading_stack.pop()
            heading_stack.append({"level": level, "text": block["text"]})
            current = {
                "line_start": block["line_start"],
                "line_end": block["line_end"],
                "heading": {"text": block["text"], "level": level},
                "heading_path": [item["text"] for item in heading_stack],
                "content_blocks": [block],
            }
            continue

        if current is None:
            current = {
                "line_start": block["line_start"],
                "line_end": block["line_end"],
                "heading": {"text": "Preamble", "level": 0},
                "heading_path": ["Preamble"],
                "content_blocks": [],
            }
        current["line_end"] = block["line_end"]
        current["content_blocks"].append(block)

    if current is not None:
        section_specs.append(current)

    sections: list[dict[str, Any]] = []
    for spec in section_specs:
        section_id = _section_id(document_id=document["fixture_id"], line_start=spec["line_start"], heading_path=spec["heading_path"])
        content_blocks = list(spec["content_blocks"])
        body_line_numbers = [
            int(block["line_start"])
            for block in content_blocks
            if block["kind"] != "heading"
        ] + [
            int(block["line_end"])
            for block in content_blocks
            if block["kind"] != "heading"
        ]
        content_types = sorted({block["kind"] for block in content_blocks if block["kind"] != "heading"})
        labels = _section_labels(spec)
        table_ids = [
            _table_id(document_id=document["fixture_id"], line_start=block["line_start"], artifact_kind=block["kind"])
            for block in content_blocks
            if _supports_table_artifact(document=document, block=block)
        ]
        sections.append(
            {
                "section_id": section_id,
                "heading": spec["heading"],
                "heading_path": list(spec["heading_path"]),
                "line_start": spec["line_start"],
                "line_end": spec["line_end"],
                "body_line_start": min(body_line_numbers) if body_line_numbers else spec["line_start"],
                "body_line_end": max(body_line_numbers) if body_line_numbers else spec["line_end"],
                "content_types": content_types,
                "labels": labels,
                "table_artifact_ids": table_ids,
                "source_quote": _escape_quote(lines[spec["line_start"] - 1 : spec["line_end"]]),
            }
        )
    return sections


def _build_table_artifacts(
    *,
    document: Mapping[str, Any],
    blocks: Sequence[Mapping[str, Any]],
    sections: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    section_by_range: list[tuple[int, int, str]] = [
        (int(section["line_start"]), int(section["line_end"]), str(section["section_id"])) for section in sections
    ]
    artifacts: list[dict[str, Any]] = []
    for block in blocks:
        if not _supports_table_artifact(document=document, block=block):
            continue
        table_id = _table_id(document_id=document["fixture_id"], line_start=block["line_start"], artifact_kind=block["kind"])
        section_id = _section_for_range(section_by_range, block["line_start"], block["line_end"])
        artifact = {
            "table_id": table_id,
            "section_id": section_id,
            "artifact_type": "markdown_table" if block["kind"] == "table" else "bullet_list_table",
            "line_start": block["line_start"],
            "line_end": block["line_end"],
            "source_quote": block["quote"],
            "rows": _table_rows(block),
        }
        artifacts.append(artifact)
    return artifacts

def _section_labels(section_spec: Mapping[str, Any]) -> list[str]:
    non_heading_blocks = [block for block in section_spec["content_blocks"] if block["kind"] != "heading"]
    if non_heading_blocks and all(_is_low_value_block(block) for block in non_heading_blocks):
        return ["low_value"]
    if any(_is_low_value_block(block) for block in non_heading_blocks):
        return ["contains_low_value_lines", "primary_content"]
    return ["primary_content"]


def _is_low_value_block(block: Mapping[str, Any]) -> bool:
    text = _block_text(block)
    if not text:
        return False
    return any(pattern.search(text) for pattern in LOW_VALUE_PATTERNS)


def _block_text(block: Mapping[str, Any]) -> str:
    kind = block["kind"]
    if kind == "heading":
        return str(block["text"])
    if kind == "paragraph":
        return str(block["text"])
    if kind == "bullet_list":
        return "\n".join(str(item) for item in block["items"])
    if kind == "table":
        return "\n".join(str(line) for line in block["lines"])
    return ""


def _supports_table_artifact(*, document: Mapping[str, Any], block: Mapping[str, Any]) -> bool:
    if block["kind"] == "table":
        return True
    return (
        block["kind"] == "bullet_list"
        and (
            document["document_role"] == "investment_account_table"
            or "investment_account_table" in document["product_class_secondary"]
            or "supporting_table" in document["product_class_secondary"]
        )
    )


def _section_for_range(section_ranges: Sequence[tuple[int, int, str]], line_start: int, line_end: int) -> str:
    for section_start, section_end, section_id in section_ranges:
        if section_start <= line_start and line_end <= section_end:
            return section_id
    raise SectionContractError(f"could not assign table artifact for line range {line_start}-{line_end} to a section")


def _table_rows(block: Mapping[str, Any]) -> list[list[str]]:
    if block["kind"] == "bullet_list":
        return [[str(item)] for item in block["items"]]
    rows: list[list[str]] = []
    for line in block["lines"]:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        rows.append(cells)
    return rows


def _is_pipe_table_line(line: str) -> bool:
    return line.startswith("|") and line.endswith("|") and line.count("|") >= 2


def _escape_quote(lines: Sequence[str]) -> str:
    return html.escape("\n".join(lines), quote=False)


def _validate_escaped_quote(source_quote: str, *, owner: str) -> None:
    if "<" in source_quote or ">" in source_quote:
        raise SectionContractError(f"{owner}: source_quote must not contain raw angle brackets")


def _section_id(*, document_id: str, line_start: int, heading_path: Sequence[str]) -> str:
    return f"{document_id}-sec-{line_start:04d}-{_slugify('__'.join(heading_path))}"


def _table_id(*, document_id: str, line_start: int, artifact_kind: str) -> str:
    return f"{document_id}-table-{line_start:04d}-{_slugify(artifact_kind)}"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "section"
