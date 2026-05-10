from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

import jsonschema
import yaml

from ._version import __version__
from .catalog import (
    load_source_catalog_document,
    validate_source_catalog_document,
)
from .resources import resource_path, resource_text

DEFAULT_FIXTURE_SPEC_RESOURCE = "examples/fixtures/manulife_fixture_builder.yaml"
DEFAULT_CATALOG_RESOURCE = "examples/sources/manulife_sources.yaml"
ALLOWED_BLOCK_TYPES = {"heading", "paragraph", "bullet_list"}
ALLOWED_SOURCE_TYPES = {"api_table_excerpt", "html_page_excerpt", "pdf_excerpt"}


class FixtureContractError(ValueError):
    """Raised when fixture specs or manifests violate the PR B contract."""


def load_fixture_builder_spec(path: str | Path) -> dict[str, Any]:
    spec_path = Path(path)
    try:
        raw_text = spec_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FixtureContractError(f"could not read fixture builder spec {spec_path}: {exc.strerror or exc}") from exc
    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise FixtureContractError(f"could not parse fixture builder spec YAML {spec_path}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise FixtureContractError("fixture builder spec must be a YAML mapping")
    return dict(data)


def load_fixture_manifest_document(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FixtureContractError(f"could not read fixture manifest {manifest_path}: {exc.strerror or exc}") from exc
    except json.JSONDecodeError as exc:
        raise FixtureContractError(f"could not parse fixture manifest JSON {manifest_path}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise FixtureContractError("fixture manifest must be a JSON object")
    return dict(data)


def validate_fixture_manifest_document(manifest: Mapping[str, Any], *, base_dir: str | Path | None = None) -> None:
    _validate_manifest_shape(manifest)

    documents = manifest["documents"]
    seen_fixture_ids: set[str] = set()
    seen_markdown_paths: set[str] = set()
    seen_catalog_ids: set[str] = set()
    documents_by_fixture_id: dict[str, Mapping[str, Any]] = {}

    manifest_base_dir = Path(base_dir) if base_dir is not None else None
    for index, document in enumerate(documents):
        label = document.get("fixture_id") or f"documents[{index}]"
        fixture_id = document["fixture_id"]
        markdown_path = document["markdown_path"]
        if fixture_id in seen_fixture_ids:
            raise FixtureContractError(f"{label}: duplicate fixture_id {fixture_id!r}")
        if markdown_path in seen_markdown_paths:
            raise FixtureContractError(f"{label}: duplicate markdown_path {markdown_path!r}")
        seen_fixture_ids.add(fixture_id)
        seen_markdown_paths.add(markdown_path)
        seen_catalog_ids.add(document["source_catalog_id"])
        documents_by_fixture_id[fixture_id] = document

        selected_lines = document["provenance"]["selected_line_numbers"]
        if selected_lines != sorted(selected_lines):
            raise FixtureContractError(f"{label}: provenance.selected_line_numbers must be sorted ascending")
        raw_line_count = document["provenance"]["raw_line_count"]
        if any(line_number < 1 or line_number > raw_line_count for line_number in selected_lines):
            raise FixtureContractError(f"{label}: provenance.selected_line_numbers must stay within 1..raw_line_count")

        previous_end = 0
        for omitted_range in document["provenance"]["omitted_line_ranges"]:
            if omitted_range["start"] < 1 or omitted_range["end"] > raw_line_count:
                raise FixtureContractError(f"{label}: omitted line ranges must stay within 1..raw_line_count")
            if omitted_range["start"] > omitted_range["end"]:
                raise FixtureContractError(f"{label}: omitted line ranges must have start <= end")
            if omitted_range["start"] <= previous_end:
                raise FixtureContractError(f"{label}: omitted line ranges must be sorted and non-overlapping")
            previous_end = omitted_range["end"]
        if document["provenance"]["omitted_line_ranges"] != _omitted_ranges(raw_line_count, selected_lines):
            raise FixtureContractError(
                f"{label}: omitted line ranges must exactly equal the complement of selected_line_numbers"
            )

        if manifest_base_dir is not None:
            markdown_file = manifest_base_dir / markdown_path
            if not markdown_file.exists():
                raise FixtureContractError(f"{label}: markdown file referenced by manifest is missing: {markdown_path}")
            markdown_bytes = markdown_file.read_bytes()
            if hashlib.sha256(markdown_bytes).hexdigest() != document["sha256"]:
                raise FixtureContractError(f"{label}: sha256 does not match markdown file contents")
            if len(markdown_bytes) != document["byte_count"]:
                raise FixtureContractError(f"{label}: byte_count does not match markdown file contents")

    scenarios = manifest["paired_source_scenarios"]
    if not any(scenario["relation"] in {"known_overlap", "potentially_contradictory"} for scenario in scenarios):
        raise FixtureContractError(
            "paired_source_scenarios must include at least one known_overlap or potentially_contradictory scenario"
        )

    for index, scenario in enumerate(scenarios):
        label = scenario.get("scenario_id") or f"paired_source_scenarios[{index}]"
        missing_fixtures = sorted(set(scenario["fixture_ids"]) - seen_fixture_ids)
        if missing_fixtures:
            raise FixtureContractError(f"{label}: unknown fixture_ids referenced: {', '.join(missing_fixtures)}")
        missing_sources = sorted(set(scenario["source_catalog_ids"]) - seen_catalog_ids)
        if missing_sources:
            raise FixtureContractError(f"{label}: unknown source_catalog_ids referenced: {', '.join(missing_sources)}")

        scenario_documents = [documents_by_fixture_id[fixture_id] for fixture_id in scenario["fixture_ids"]]
        document_product_names = {document["product_name"] for document in scenario_documents}
        if len(document_product_names) != 1 or scenario["product_name"] not in document_product_names:
            raise FixtureContractError(f"{label}: fixture_ids must reference the same product_name as the scenario")

        document_source_ids = {document["source_catalog_id"] for document in scenario_documents}
        if set(scenario["source_catalog_ids"]) != document_source_ids:
            raise FixtureContractError(f"{label}: source_catalog_ids must exactly match the referenced fixture sources")


def build_fixture_bundle(
    *,
    spec: Mapping[str, Any],
    output_dir: str | Path,
    catalog: Mapping[str, Any],
    catalog_source: str,
    catalog_source_type: str,
) -> dict[str, Any]:
    validate_source_catalog_document(catalog)
    source_entries = catalog["sources"]
    source_by_id = {entry["id"]: dict(entry) for entry in source_entries}

    fixture_set_id = spec.get("fixture_set_id")
    documents_spec = spec.get("documents")
    scenarios_spec = spec.get("paired_source_scenarios")
    if not isinstance(fixture_set_id, str) or not fixture_set_id:
        raise FixtureContractError("fixture builder spec must include non-empty fixture_set_id")
    if not isinstance(documents_spec, list) or not documents_spec:
        raise FixtureContractError("fixture builder spec must include a non-empty documents list")
    if not all(isinstance(item, Mapping) for item in documents_spec):
        raise FixtureContractError("fixture builder spec documents must be mappings")
    if not isinstance(scenarios_spec, list) or not scenarios_spec or not all(
        isinstance(item, Mapping) for item in scenarios_spec
    ):
        raise FixtureContractError("fixture builder spec paired_source_scenarios must be a non-empty list of mappings")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=out_dir, prefix=".fixture-build-") as temp_dir_name:
            temp_out_dir = Path(temp_dir_name)
            documents_dir = temp_out_dir / "documents"
            documents_dir.mkdir(parents=True, exist_ok=True)

            manifest_documents: list[dict[str, Any]] = []
            for document_spec in documents_spec:
                manifest_documents.append(_build_document_entry(document_spec, documents_dir, source_by_id))

            manifest = {
                "schema_version": "0.1",
                "fixture_set_id": fixture_set_id,
                "source_catalog": {
                    "source": catalog_source,
                    "source_type": catalog_source_type,
                },
                "generated_by": {
                    "tool": "life_product_extractor.fixture_builder",
                    "version": __version__,
                },
                "documents": sorted(manifest_documents, key=lambda item: item["fixture_id"]),
                "paired_source_scenarios": _build_paired_source_scenarios(scenarios_spec),
            }
            validate_fixture_manifest_document(manifest, base_dir=temp_out_dir)

            manifest_path = temp_out_dir / "manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
                encoding="utf-8",
            )
            _replace_fixture_output(temp_out_dir=temp_out_dir, out_dir=out_dir)
    except OSError as exc:
        raise FixtureContractError(f"could not write fixture bundle to {out_dir}: {exc.strerror or exc}") from exc
    return manifest


def build_fixture_bundle_from_paths(
    *,
    spec_path: str | Path,
    output_dir: str | Path,
    catalog_path: str | Path | None = None,
) -> dict[str, Any]:
    spec = load_fixture_builder_spec(spec_path)
    catalog, catalog_source, catalog_source_type = _load_catalog_for_build(catalog_path)
    return build_fixture_bundle(
        spec=spec,
        output_dir=output_dir,
        catalog=catalog,
        catalog_source=catalog_source,
        catalog_source_type=catalog_source_type,
    )


def _load_catalog_for_build(catalog_path: str | Path | None) -> tuple[dict[str, Any], str, str]:
    if catalog_path is not None:
        catalog = load_source_catalog_document(catalog_path)
        return catalog, str(Path(catalog_path)), "filesystem_path"

    with resource_path(DEFAULT_CATALOG_RESOURCE) as default_catalog_path:
        catalog = load_source_catalog_document(default_catalog_path)
    return catalog, f"bundled://{DEFAULT_CATALOG_RESOURCE}", "bundled_resource"


def _validate_manifest_shape(manifest: Mapping[str, Any]) -> None:
    schema = json.loads(resource_text("schemas/manifest.schema.json"))
    try:
        jsonschema.Draft202012Validator(schema).validate(manifest)
    except jsonschema.ValidationError as exc:
        raise FixtureContractError(f"fixture manifest does not match manifest.schema.json: {exc.message}") from exc


def _build_document_entry(
    document_spec: Mapping[str, Any],
    documents_dir: Path,
    source_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    fixture_id = _required_str(document_spec, "fixture_id")
    source_catalog_id = _required_str(document_spec, "source_catalog_id")
    retrieval_date = _required_str(document_spec, "retrieval_date")
    output_file = _required_str(document_spec, "output_file")
    source_type = _required_str(document_spec, "source_type")
    output_path = _validated_output_path(documents_dir, fixture_id, output_file)

    if source_type not in ALLOWED_SOURCE_TYPES:
        raise FixtureContractError(f"{fixture_id}: unsupported source_type {source_type!r}")

    source_entry = source_by_id.get(source_catalog_id)
    if source_entry is None:
        raise FixtureContractError(f"{fixture_id}: unknown source_catalog_id {source_catalog_id!r}")
    if not source_entry.get("allowed_as_fixture", False):
        raise FixtureContractError(f"{fixture_id}: source catalog entry is not allowed_as_fixture")
    if int(source_entry.get("fixture_tier", 0)) < 1:
        raise FixtureContractError(f"{fixture_id}: source catalog entry must be Tier 1 or above for fixture building")

    raw_lines = document_spec.get("raw_lines")
    markdown_blocks = document_spec.get("markdown_blocks")
    if not isinstance(raw_lines, list) or not raw_lines or not all(isinstance(line, str) and line for line in raw_lines):
        raise FixtureContractError(f"{fixture_id}: raw_lines must be a non-empty list of non-empty strings")
    if not isinstance(markdown_blocks, list) or not markdown_blocks or not all(isinstance(block, Mapping) for block in markdown_blocks):
        raise FixtureContractError(f"{fixture_id}: markdown_blocks must be a non-empty list of mappings")

    markdown_text, selected_line_numbers = _render_markdown(raw_lines, markdown_blocks, fixture_id)
    markdown_bytes = markdown_text.encode("utf-8")
    markdown_path = Path("documents") / output_path.name
    output_path.write_text(markdown_text, encoding="utf-8")

    raw_text = "\n".join(raw_lines) + "\n"
    provenance = {
        "source_kind": "committed_curated_snippet",
        "normalization": "curated_markdown_excerpt_v1",
        "raw_text_sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
        "raw_line_count": len(raw_lines),
        "selected_line_numbers": selected_line_numbers,
        "omitted_line_ranges": _omitted_ranges(len(raw_lines), selected_line_numbers),
        "selected_block_count": len(markdown_blocks),
    }

    return {
        "fixture_id": fixture_id,
        "source_catalog_id": source_catalog_id,
        "product_name": source_entry["product_name"],
        "region_family": source_entry["region_family"],
        "jurisdiction": source_entry["jurisdiction"],
        "product_class_primary": source_entry["product_class_primary"],
        "product_class_secondary": list(source_entry["product_class_secondary"]),
        "document_role": source_entry["document_role"],
        "authority_level": source_entry["authority_level"],
        "source_url": source_entry["source_url"],
        "retrieval_date": retrieval_date,
        "source_type": source_type,
        "markdown_path": markdown_path.as_posix(),
        "sha256": hashlib.sha256(markdown_bytes).hexdigest(),
        "byte_count": len(markdown_bytes),
        "provenance": provenance,
    }


def _build_paired_source_scenarios(scenarios_spec: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    built: list[dict[str, Any]] = []
    for index, scenario in enumerate(scenarios_spec):
        scenario_id = _required_str(scenario, "scenario_id")
        relation = _required_str(scenario, "relation")
        if relation not in {"complementary", "known_overlap", "potentially_contradictory"}:
            raise FixtureContractError(f"{scenario_id or f'scenario[{index}]'}: unsupported relation {relation!r}")
        fixture_ids = scenario.get("fixture_ids")
        source_catalog_ids = scenario.get("source_catalog_ids")
        if not isinstance(fixture_ids, list) or len(fixture_ids) < 2 or not all(isinstance(item, str) and item for item in fixture_ids):
            raise FixtureContractError(f"{scenario_id}: fixture_ids must contain at least two non-empty strings")
        if not isinstance(source_catalog_ids, list) or len(source_catalog_ids) < 2 or not all(
            isinstance(item, str) and item for item in source_catalog_ids
        ):
            raise FixtureContractError(f"{scenario_id}: source_catalog_ids must contain at least two non-empty strings")
        built.append(
            {
                "scenario_id": scenario_id,
                "product_name": _required_str(scenario, "product_name"),
                "relation": relation,
                "fixture_ids": fixture_ids,
                "source_catalog_ids": source_catalog_ids,
                "rationale": _required_str(scenario, "rationale"),
            }
        )
    return sorted(built, key=lambda item: item["scenario_id"])


def _render_markdown(raw_lines: Sequence[str], markdown_blocks: Sequence[Mapping[str, Any]], fixture_id: str) -> tuple[str, list[int]]:
    rendered_lines: list[str] = []
    selected_line_numbers: list[int] = []

    for block_index, block in enumerate(markdown_blocks):
        block_type = _required_str(block, "type")
        line_numbers = block.get("line_numbers")
        if block_type not in ALLOWED_BLOCK_TYPES:
            raise FixtureContractError(f"{fixture_id}: markdown_blocks[{block_index}] has unsupported type {block_type!r}")
        if not isinstance(line_numbers, list) or not line_numbers or not all(
            isinstance(item, int) and item >= 1 for item in line_numbers
        ):
            raise FixtureContractError(f"{fixture_id}: markdown_blocks[{block_index}] line_numbers must be positive integers")

        block_lines: list[str] = []
        for line_number in line_numbers:
            if line_number > len(raw_lines):
                raise FixtureContractError(
                    f"{fixture_id}: markdown_blocks[{block_index}] references raw line {line_number} beyond raw_line_count"
                )
            block_lines.append(raw_lines[line_number - 1].strip())
            selected_line_numbers.append(line_number)

        if block_type == "heading":
            if len(block_lines) != 1:
                raise FixtureContractError(f"{fixture_id}: heading blocks must reference exactly one line")
            rendered_lines.append(f"# {block_lines[0]}")
        elif block_type == "paragraph":
            rendered_lines.append(" ".join(block_lines))
        else:
            for line in block_lines:
                rendered_lines.append(f"- {line}")

        rendered_lines.append("")

    markdown_text = "\n".join(rendered_lines).rstrip() + "\n"
    unique_sorted_lines = sorted(set(selected_line_numbers))
    return markdown_text, unique_sorted_lines


def _omitted_ranges(raw_line_count: int, selected_line_numbers: Sequence[int]) -> list[dict[str, int]]:
    selected_set = set(selected_line_numbers)
    omitted_numbers = [line for line in range(1, raw_line_count + 1) if line not in selected_set]
    if not omitted_numbers:
        return []

    ranges: list[dict[str, int]] = []
    start = omitted_numbers[0]
    end = omitted_numbers[0]
    for line_number in omitted_numbers[1:]:
        if line_number == end + 1:
            end = line_number
            continue
        ranges.append({"start": start, "end": end})
        start = end = line_number
    ranges.append({"start": start, "end": end})
    return ranges


def _validated_output_path(documents_dir: Path, fixture_id: str, output_file: str) -> Path:
    output_file_path = Path(output_file)
    if output_file_path.is_absolute():
        raise FixtureContractError(f"{fixture_id}: output_file must be a simple relative filename")
    if any(part == ".." for part in output_file_path.parts):
        raise FixtureContractError(f"{fixture_id}: output_file must not contain parent-directory traversal")
    if output_file_path.name != output_file or len(output_file_path.parts) != 1:
        raise FixtureContractError(f"{fixture_id}: output_file must not contain path separators or subdirectories")

    output_path = documents_dir / output_file_path.name
    try:
        output_path.resolve(strict=False).relative_to(documents_dir.resolve())
    except ValueError as exc:
        raise FixtureContractError(f"{fixture_id}: output_file resolves outside documents_dir") from exc
    return output_path


def _replace_fixture_output(*, temp_out_dir: Path, out_dir: Path) -> None:
    target_documents_dir = out_dir / "documents"
    target_manifest_path = out_dir / "manifest.json"
    new_documents_dir = temp_out_dir / "documents"
    new_manifest_path = temp_out_dir / "manifest.json"

    with tempfile.TemporaryDirectory(dir=out_dir, prefix=".fixture-commit-") as backup_dir_name:
        backup_dir = Path(backup_dir_name)
        backup_documents_dir = backup_dir / "documents"
        backup_manifest_path = backup_dir / "manifest.json"
        new_documents_installed = False
        new_manifest_installed = False
        try:
            if target_documents_dir.exists():
                shutil.move(str(target_documents_dir), str(backup_documents_dir))
            if target_manifest_path.exists():
                shutil.move(str(target_manifest_path), str(backup_manifest_path))

            shutil.move(str(new_documents_dir), str(target_documents_dir))
            new_documents_installed = True
            os.replace(new_manifest_path, target_manifest_path)
            new_manifest_installed = True
        except Exception:
            if new_manifest_installed and target_manifest_path.exists():
                target_manifest_path.unlink()
            if backup_manifest_path.exists():
                os.replace(backup_manifest_path, target_manifest_path)

            if new_documents_installed and target_documents_dir.exists():
                shutil.rmtree(target_documents_dir)
            if backup_documents_dir.exists():
                shutil.move(str(backup_documents_dir), str(target_documents_dir))
            raise


def _required_str(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise FixtureContractError(f"fixture builder spec requires non-empty string field {key!r}")
    return value
