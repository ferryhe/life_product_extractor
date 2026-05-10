from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

import jsonschema

from .catalog import (
    ALLOWED_PRIMARY_CLASSES,
    ALLOWED_REGION_FAMILIES,
    ALLOWED_SECONDARY_TAGS,
    load_source_catalog_document,
    validate_source_catalog_document,
)
from .fixtures import (
    DEFAULT_CATALOG_RESOURCE,
    load_fixture_manifest_document,
    validate_fixture_manifest_document,
)
from .resources import resource_path, resource_text


class RoutingContractError(ValueError):
    """Raised when routing inputs or outputs violate the PR C contract."""


def load_routing_document(path: str | Path) -> dict[str, Any]:
    routing_path = Path(path)
    try:
        data = json.loads(routing_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RoutingContractError(f"could not read routing document {routing_path}: {exc.strerror or exc}") from exc
    except json.JSONDecodeError as exc:
        raise RoutingContractError(f"could not parse routing document JSON {routing_path}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise RoutingContractError("routing document must be a JSON object")
    return dict(data)


def classify_fixture_manifest_from_path(
    manifest_path: str | Path,
    *,
    catalog_path: str | Path | None = None,
) -> dict[str, Any]:
    fixture_manifest_path = Path(manifest_path)
    manifest = load_fixture_manifest_document(fixture_manifest_path)
    validate_fixture_manifest_document(manifest, base_dir=fixture_manifest_path.parent)
    catalog = _load_catalog_for_manifest(manifest, manifest_dir=fixture_manifest_path.parent, catalog_path=catalog_path)
    return classify_fixture_manifest(manifest, base_dir=fixture_manifest_path.parent, catalog=catalog)


def classify_fixture_manifest(
    manifest: Mapping[str, Any],
    *,
    base_dir: str | Path,
    catalog: Mapping[str, Any],
) -> dict[str, Any]:
    validate_fixture_manifest_document(manifest, base_dir=base_dir)
    validate_source_catalog_document(catalog)

    catalog_by_id = {entry["id"]: dict(entry) for entry in catalog["sources"]}
    documents = []
    for document in manifest["documents"]:
        source_catalog_id = document["source_catalog_id"]
        if source_catalog_id not in catalog_by_id:
            raise RoutingContractError(f"{document['fixture_id']}: source_catalog_id {source_catalog_id!r} not found in catalog")
        documents.append(
            _classify_document(document, base_dir=Path(base_dir), catalog_entry=catalog_by_id[source_catalog_id])
        )
    documents_by_id = {document["document_id"]: document for document in documents}
    scenarios = [_classify_scenario(scenario, documents_by_id=documents_by_id) for scenario in manifest["paired_source_scenarios"]]

    routing = {
        "schema_version": "0.1",
        "fixture_set_id": manifest["fixture_set_id"],
        "source_catalog": dict(manifest["source_catalog"]),
        "routing_strategy": {
            "deterministic": True,
            "manifest_taxonomy_precedence": True,
            "taxonomy_sources_in_order": ["manifest_document", "source_catalog", "content_keywords"],
        },
        "summary": {
            "document_count": len(documents),
            "scenario_count": len(scenarios),
            "primary_class_counts": dict(sorted(Counter(document["product_class_primary"] for document in documents).items())),
        },
        "documents": documents,
        "paired_source_scenarios": scenarios,
    }
    validate_routing_document(routing)
    return routing


def validate_routing_document(routing: Mapping[str, Any]) -> None:
    schema = json.loads(resource_text("schemas/routing.schema.json"))
    try:
        jsonschema.Draft202012Validator(schema).validate(routing)
    except jsonschema.ValidationError as exc:
        raise RoutingContractError(f"routing document does not match routing.schema.json: {exc.message}") from exc


def _classify_document(
    document: Mapping[str, Any],
    *,
    base_dir: Path,
    catalog_entry: Mapping[str, Any],
) -> dict[str, Any]:
    document_id = document["fixture_id"]
    product_class_primary, primary_source = _resolve_preferred_string(
        manifest_value=document.get("product_class_primary"),
        catalog_value=catalog_entry.get("product_class_primary"),
        label=f"{document_id}.product_class_primary",
    )
    if product_class_primary not in ALLOWED_PRIMARY_CLASSES:
        raise RoutingContractError(f"{document_id}: invalid routed product_class_primary {product_class_primary!r}")

    region_family, region_source = _resolve_preferred_string(
        manifest_value=document.get("region_family"),
        catalog_value=catalog_entry.get("region_family"),
        label=f"{document_id}.region_family",
    )
    if region_family not in ALLOWED_REGION_FAMILIES:
        raise RoutingContractError(f"{document_id}: invalid routed region_family {region_family!r}")

    jurisdiction, jurisdiction_source = _resolve_preferred_string(
        manifest_value=document.get("jurisdiction"),
        catalog_value=catalog_entry.get("jurisdiction"),
        label=f"{document_id}.jurisdiction",
    )

    secondary_tags, secondary_source = _resolve_secondary_tags(
        manifest_value=document.get("product_class_secondary"),
        catalog_value=catalog_entry.get("product_class_secondary"),
        document_id=document_id,
    )
    markdown_quote = _first_markdown_quote(base_dir / document["markdown_path"])
    routing_flags = _derive_routing_flags(primary=product_class_primary, secondary_tags=secondary_tags)
    route = {
        "document_id": document_id,
        "source_catalog_id": document["source_catalog_id"],
        "product_name": document["product_name"],
        "region_family": region_family,
        "jurisdiction": jurisdiction,
        "product_class_primary": product_class_primary,
        "product_class_secondary": secondary_tags,
        "routing_confidence": 1.0 if primary_source == "manifest_document" else 0.95,
        "classification_mode": "manifest_precedence" if primary_source == "manifest_document" else "source_catalog_fallback",
        "skill_pack_hint": f"{region_family}/{product_class_primary}",
        "routing_flags": routing_flags,
        "routing_evidence": [
            {
                "kind": "taxonomy_field",
                "source": primary_source,
                "field": "product_class_primary",
                "value": product_class_primary,
            },
            {
                "kind": "taxonomy_field",
                "source": region_source,
                "field": "region_family",
                "value": region_family,
            },
            {
                "kind": "taxonomy_field",
                "source": jurisdiction_source,
                "field": "jurisdiction",
                "value": jurisdiction,
            },
            {
                "kind": "taxonomy_field",
                "source": secondary_source,
                "field": "product_class_secondary",
                "value": secondary_tags,
            },
            {
                "kind": "document_metadata",
                "source": "manifest_document",
                "field": "document_role",
                "value": document["document_role"],
            },
            {
                "kind": "content_keyword",
                "source": "markdown_excerpt",
                "field": "headline_quote",
                "quote": markdown_quote,
            },
        ],
    }
    if _has_taxonomy_mismatch(document=document, catalog_entry=catalog_entry):
        route["routing_warnings"] = [
            "manifest taxonomy differs from source catalog; manifest value preserved by precedence"
        ]
    return route


def _classify_scenario(
    scenario: Mapping[str, Any],
    *,
    documents_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    scenario_documents = [documents_by_id[fixture_id] for fixture_id in scenario["fixture_ids"]]
    primary_classes = sorted({document["product_class_primary"] for document in scenario_documents})
    secondary_tags = sorted({tag for document in scenario_documents for tag in document["product_class_secondary"]})
    implications = {
        "complementary": "cross_reference_same_product_sources",
        "known_overlap": "reconcile_overlapping_same_product_evidence",
        "potentially_contradictory": "escalate_same_product_source_disagreements",
    }
    return {
        "scenario_id": scenario["scenario_id"],
        "product_name": scenario["product_name"],
        "relation": scenario["relation"],
        "fixture_ids": list(scenario["fixture_ids"]),
        "source_catalog_ids": list(scenario["source_catalog_ids"]),
        "product_class_primary": primary_classes[0] if len(primary_classes) == 1 else "other",
        "product_class_secondary": secondary_tags,
        "routing_implication": implications[scenario["relation"]],
        "rationale": scenario["rationale"],
    }


def _load_catalog_for_manifest(
    manifest: Mapping[str, Any],
    *,
    manifest_dir: Path,
    catalog_path: str | Path | None,
) -> dict[str, Any]:
    if catalog_path is not None:
        catalog = load_source_catalog_document(catalog_path)
        validate_source_catalog_document(catalog)
        return catalog

    source_catalog = manifest.get("source_catalog")
    if isinstance(source_catalog, Mapping):
        source = source_catalog.get("source")
        source_type = source_catalog.get("source_type")
        if source_type == "filesystem_path" and isinstance(source, str) and source:
            candidate = Path(source)
            if not candidate.is_absolute():
                candidate = manifest_dir / candidate
            catalog = load_source_catalog_document(candidate)
            validate_source_catalog_document(catalog)
            return catalog
        if source_type == "bundled_resource" and isinstance(source, str) and source.startswith("bundled://"):
            resource_name = source.removeprefix("bundled://")
            with resource_path(resource_name) as bundled_catalog_path:
                catalog = load_source_catalog_document(bundled_catalog_path)
                validate_source_catalog_document(catalog)
                return catalog

    with resource_path(DEFAULT_CATALOG_RESOURCE) as default_catalog_path:
        catalog = load_source_catalog_document(default_catalog_path)
        validate_source_catalog_document(catalog)
        return catalog


def _resolve_preferred_string(*, manifest_value: Any, catalog_value: Any, label: str) -> tuple[str, str]:
    if isinstance(manifest_value, str) and manifest_value:
        return manifest_value, "manifest_document"
    if isinstance(catalog_value, str) and catalog_value:
        return catalog_value, "source_catalog"
    raise RoutingContractError(f"{label}: expected a non-empty string from manifest or source catalog")


def _resolve_secondary_tags(*, manifest_value: Any, catalog_value: Any, document_id: str) -> tuple[list[str], str]:
    manifest_tags = _normalize_tag_list(manifest_value, label=f"{document_id}.product_class_secondary")
    catalog_tags = _normalize_tag_list(catalog_value, label=f"{document_id}.source_catalog.product_class_secondary")
    if manifest_tags:
        return manifest_tags, "manifest_document"
    if catalog_tags:
        return catalog_tags, "source_catalog"
    return [], "manifest_document"


def _normalize_tag_list(value: Any, *, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(tag, str) and tag for tag in value):
        raise RoutingContractError(f"{label}: expected a list of non-empty strings")
    unique_tags = sorted(dict.fromkeys(value))
    unknown_tags = sorted(set(unique_tags) - ALLOWED_SECONDARY_TAGS)
    if unknown_tags:
        raise RoutingContractError(f"{label}: unknown secondary tags: {', '.join(unknown_tags)}")
    return unique_tags


def _first_markdown_quote(markdown_path: Path) -> str:
    try:
        lines = markdown_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RoutingContractError(f"could not read markdown fixture {markdown_path}: {exc.strerror or exc}") from exc
    for line in lines:
        stripped = line.strip()
        if stripped:
            return stripped[:240]
    raise RoutingContractError(f"{markdown_path}: markdown fixture must contain at least one non-empty line")


def _derive_routing_flags(*, primary: str, secondary_tags: list[str]) -> list[str]:
    flags: list[str] = []
    secondary = set(secondary_tags)
    if "combination_product" in secondary or len({"critical_illness", "disability", "long_term_care"} & secondary) >= 2:
        flags.append("multi_benefit")
    if "supporting_table" in secondary or "investment_account_table" in secondary:
        flags.append("supporting_table_source")
    if primary in {"deferred_annuity", "immediate_annuity"} and (
        {"educational_context", "gic_adjacent", "segregated_fund_adjacent", "investment_contract"} & secondary
    ):
        flags.append("adjacent_context")
    return flags


def _has_taxonomy_mismatch(*, document: Mapping[str, Any], catalog_entry: Mapping[str, Any]) -> bool:
    document_secondary = _normalize_tag_list(
        document.get("product_class_secondary"),
        label=f"{document.get('fixture_id', 'document')}.product_class_secondary",
    )
    catalog_secondary = _normalize_tag_list(
        catalog_entry.get("product_class_secondary"),
        label=f"{catalog_entry.get('id', 'source_catalog')}.product_class_secondary",
    )
    return (
        document.get("product_class_primary") != catalog_entry.get("product_class_primary")
        or document_secondary != catalog_secondary
        or document.get("region_family") != catalog_entry.get("region_family")
        or document.get("jurisdiction") != catalog_entry.get("jurisdiction")
    )
