from __future__ import annotations

from collections.abc import Iterable, Mapping
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import jsonschema
import yaml

from .resources import resource_text

ALLOWED_REGION_FAMILIES = {"north_america"}

ALLOWED_JURISDICTIONS = {"CA"}

ALLOWED_PRIMARY_CLASSES = {
    "traditional_life",
    "ltc_di",
    "ul_iul",
    "deferred_annuity",
    "immediate_annuity",
    "multi_state",
    "participating_life",
    "other",
}

ALLOWED_SECONDARY_TAGS = {
    "accident",
    "adjacent_investment_context",
    "combination_product",
    "critical_illness",
    "deferred_annuity_adjacent",
    "direct_to_consumer",
    "disability",
    "disability_adjacent",
    "dividend",
    "educational_context",
    "gic_adjacent",
    "guaranteed_issue",
    "investment_account_table",
    "investment_contract",
    "long_term_care",
    "mirror_discovery_only",
    "permanent_life",
    "segregated_fund_adjacent",
    "simplified_issue",
    "supporting_table",
    "term_life",
    "universal_life",
    "vitality",
    "whole_life",
}

ALLOWED_DOCUMENT_ROLES = {
    "adjacent_context",
    "client_guide",
    "educational_page",
    "investment_account_table",
    "mirror_discovery_only",
    "product_guide",
    "product_marketing_page",
}

ALLOWED_AUTHORITY_LEVELS = {
    "official_advisor",
    "official_investment_affiliate",
    "official_public",
    "third_party_mirror",
    "unknown",
}

REQUIRED_FIELDS = {
    "id",
    "product_name",
    "region_family",
    "jurisdiction",
    "product_class_primary",
    "product_class_secondary",
    "document_role",
    "authority_level",
    "allowed_as_fixture",
    "fixture_tier",
    "source_url",
}

AUTHORITY_FIXTURE_REVIEW_FIELDS = {
    "override_rationale",
    "reviewed_by",
    "reviewed_at",
}


class SourceCatalogError(ValueError):
    """Raised when the source catalog violates the project contract."""


def _load_catalog_yaml(path: str | Path) -> Any:
    catalog_path = Path(path)
    try:
        raw_text = catalog_path.read_text()
    except OSError as exc:
        raise SourceCatalogError(f"could not read source catalog {catalog_path}: {exc.strerror or exc}") from exc
    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise SourceCatalogError(f"could not parse source catalog YAML {catalog_path}: {exc}") from exc
    return data


def load_source_catalog_document(path: str | Path) -> dict[str, Any]:
    """Load a source catalog YAML document."""

    data = _load_catalog_yaml(path)
    if not isinstance(data, Mapping):
        raise SourceCatalogError("source catalog must be a YAML mapping")
    return dict(data)


def load_source_catalog(path: str | Path) -> list[dict[str, Any]]:
    """Load source catalog entries from a YAML file."""

    data = load_source_catalog_document(path)
    entries = data.get("sources")
    if not isinstance(entries, list):
        raise SourceCatalogError("source catalog must contain a 'sources' list")
    if not all(isinstance(entry, Mapping) for entry in entries):
        raise SourceCatalogError("every source catalog entry must be a mapping")
    return [dict(entry) for entry in entries]


def validate_source_catalog_document(catalog: Mapping[str, Any]) -> None:
    """Validate the top-level source catalog contract plus entry-level rules."""

    _validate_catalog_shape(catalog)
    validate_source_catalog(catalog["sources"])


def validate_source_catalog(entries: Iterable[Mapping[str, Any]]) -> None:
    """Validate source catalog entries against the PR A contract.

    The validation is intentionally deterministic and conservative. It rejects
    taxonomy drift, missing authority metadata, and accidental promotion of
    mirror or educational sources into committed authoritative fixtures.
    """

    seen_ids: set[str] = set()
    for index, entry in enumerate(entries):
        label = entry.get("id") or entry.get("product_name") or f"entry[{index}]"
        _validate_required_fields(entry, str(label))
        _validate_unique_id(entry, seen_ids, str(label))
        _validate_region_and_jurisdiction(entry, str(label))
        _validate_taxonomy(entry, str(label))
        _validate_source_authority(entry, str(label))
        _validate_fixture_tier(entry, str(label))


def _validate_catalog_shape(catalog: Mapping[str, Any]) -> None:
    extra_keys = sorted(set(catalog) - {"sources"})
    if extra_keys:
        raise SourceCatalogError(f"source catalog contains unsupported top-level keys: {', '.join(extra_keys)}")

    if "sources" not in catalog:
        raise SourceCatalogError("source catalog must contain a 'sources' list")

    entries = catalog["sources"]
    if not isinstance(entries, list):
        raise SourceCatalogError("source catalog must contain a 'sources' list")
    if not entries:
        raise SourceCatalogError("source catalog 'sources' must contain at least one entry")
    if not all(isinstance(entry, Mapping) for entry in entries):
        raise SourceCatalogError("every source catalog entry must be a mapping")

    schema = json.loads(resource_text("schemas/source_catalog.schema.json"))
    try:
        jsonschema.Draft202012Validator(schema).validate(catalog)
    except jsonschema.ValidationError as exc:
        raise SourceCatalogError(f"source catalog does not match source_catalog.schema.json: {exc.message}") from exc


def _validate_required_fields(entry: Mapping[str, Any], label: str) -> None:
    missing = sorted(REQUIRED_FIELDS - set(entry))
    if missing:
        raise SourceCatalogError(f"{label}: missing required fields: {', '.join(missing)}")


def _validate_unique_id(entry: Mapping[str, Any], seen_ids: set[str], label: str) -> None:
    source_id = entry["id"]
    if not isinstance(source_id, str) or not source_id:
        raise SourceCatalogError(f"{label}: id must be a non-empty string when provided")
    if source_id in seen_ids:
        raise SourceCatalogError(f"{label}: duplicate source id {source_id!r}")
    seen_ids.add(source_id)


def _validate_region_and_jurisdiction(entry: Mapping[str, Any], label: str) -> None:
    region_family = entry["region_family"]
    jurisdiction = entry["jurisdiction"]
    if region_family not in ALLOWED_REGION_FAMILIES:
        raise SourceCatalogError(f"{label}: invalid region_family {region_family!r}")
    if jurisdiction not in ALLOWED_JURISDICTIONS:
        raise SourceCatalogError(f"{label}: invalid jurisdiction {jurisdiction!r}")


def _validate_taxonomy(entry: Mapping[str, Any], label: str) -> None:
    primary = entry["product_class_primary"]
    if primary not in ALLOWED_PRIMARY_CLASSES:
        raise SourceCatalogError(f"{label}: invalid product_class_primary {primary!r}")

    secondary = entry["product_class_secondary"]
    if not isinstance(secondary, list) or not all(isinstance(tag, str) for tag in secondary):
        raise SourceCatalogError(f"{label}: product_class_secondary must be a list of strings")
    unknown_tags = sorted(set(secondary) - ALLOWED_SECONDARY_TAGS)
    experimental_secondary_tags = entry.get("experimental_secondary_tags", False)
    if not isinstance(experimental_secondary_tags, bool):
        raise SourceCatalogError(f"{label}: experimental_secondary_tags must be boolean when provided")
    if unknown_tags and not experimental_secondary_tags:
        raise SourceCatalogError(f"{label}: unknown secondary tags: {', '.join(unknown_tags)}")


def _validate_source_authority(entry: Mapping[str, Any], label: str) -> None:
    document_role = entry["document_role"]
    authority_level = entry["authority_level"]
    if document_role not in ALLOWED_DOCUMENT_ROLES:
        raise SourceCatalogError(f"{label}: invalid document_role {document_role!r}")
    if authority_level not in ALLOWED_AUTHORITY_LEVELS:
        raise SourceCatalogError(f"{label}: invalid authority_level {authority_level!r}")
    if not isinstance(entry["allowed_as_fixture"], bool):
        raise SourceCatalogError(f"{label}: allowed_as_fixture must be boolean")

    is_low_authority = document_role in {"educational_page", "mirror_discovery_only", "adjacent_context"} or authority_level in {
        "third_party_mirror",
        "unknown",
    }
    if is_low_authority and entry["allowed_as_fixture"]:
        missing_review = sorted(AUTHORITY_FIXTURE_REVIEW_FIELDS - set(entry))
        if missing_review:
            raise SourceCatalogError(
                f"{label}: low-authority or educational source cannot be a fixture without review fields: "
                f"{', '.join(missing_review)}"
            )
        invalid_review_fields = sorted(
            field for field in AUTHORITY_FIXTURE_REVIEW_FIELDS if not isinstance(entry.get(field), str) or not entry.get(field)
        )
        if invalid_review_fields:
            raise SourceCatalogError(
                f"{label}: authority override review fields must be non-empty strings: "
                f"{', '.join(invalid_review_fields)}"
            )


def _validate_fixture_tier(entry: Mapping[str, Any], label: str) -> None:
    tier = entry["fixture_tier"]
    if not isinstance(tier, int) or isinstance(tier, bool) or tier < 0 or tier > 3:
        raise SourceCatalogError(f"{label}: fixture_tier must be an integer from 0 to 3")
    if tier >= 1 and not entry["allowed_as_fixture"]:
        raise SourceCatalogError(f"{label}: fixture_tier >= 1 requires allowed_as_fixture=true")
    url = entry["source_url"]
    parsed = urlparse(url) if isinstance(url, str) else None
    if not parsed or parsed.scheme not in {"http", "https"} or not parsed.netloc or any(char.isspace() for char in url):
        raise SourceCatalogError(f"{label}: source_url must be a valid HTTP(S) URL")
