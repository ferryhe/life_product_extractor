from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from life_product_extractor.catalog import (
    ALLOWED_PRIMARY_CLASSES,
    SourceCatalogError,
    load_source_catalog_document,
    load_source_catalog,
    validate_source_catalog_document,
    validate_source_catalog,
)

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "examples" / "sources" / "manulife_sources.yaml"


def test_manulife_source_catalog_validates() -> None:
    catalog = load_source_catalog_document(CATALOG_PATH)
    entries = catalog["sources"]

    validate_source_catalog_document(catalog)

    assert len(entries) >= 20
    assert {entry["product_class_primary"] for entry in entries} <= ALLOWED_PRIMARY_CLASSES
    assert all("source_url" in entry for entry in entries)
    assert any(entry["fixture_tier"] == 1 for entry in entries)
    assert any(entry["allowed_as_fixture"] is False for entry in entries)


def test_source_catalog_rejects_missing_stable_id() -> None:
    entries = load_source_catalog(CATALOG_PATH)
    missing_id = deepcopy(entries[0])
    del missing_id["id"]

    with pytest.raises(SourceCatalogError, match="missing required fields: id"):
        validate_source_catalog([missing_id])


def test_source_catalog_rejects_unsupported_top_level_key() -> None:
    catalog = load_source_catalog_document(CATALOG_PATH)
    bad_catalog = deepcopy(catalog)
    bad_catalog["catalog_version"] = "0.1"

    with pytest.raises(SourceCatalogError, match="unsupported top-level keys: catalog_version"):
        validate_source_catalog_document(bad_catalog)


def test_source_catalog_rejects_empty_sources_list() -> None:
    with pytest.raises(SourceCatalogError, match="must contain at least one entry"):
        validate_source_catalog_document({"sources": []})


def test_source_catalog_rejects_invalid_primary_class() -> None:
    entries = load_source_catalog(CATALOG_PATH)
    bad = deepcopy(entries[0])
    bad["product_class_primary"] = "critical_illness"

    with pytest.raises(SourceCatalogError, match="invalid product_class_primary"):
        validate_source_catalog([bad])


def test_source_catalog_rejects_unknown_region_as_product_class() -> None:
    entries = load_source_catalog(CATALOG_PATH)
    bad = deepcopy(entries[0])
    bad["product_class_primary"] = "unknown_region"

    with pytest.raises(SourceCatalogError, match="invalid product_class_primary|unknown_region"):
        validate_source_catalog([bad])


def test_source_catalog_rejects_unknown_secondary_tag_by_default() -> None:
    entries = load_source_catalog(CATALOG_PATH)
    bad = deepcopy(entries[0])
    bad["product_class_secondary"] = ["brand_new_tag"]

    with pytest.raises(SourceCatalogError, match="unknown secondary tags"):
        validate_source_catalog([bad])


def test_source_catalog_allows_experimental_secondary_tag_when_marked() -> None:
    entries = load_source_catalog(CATALOG_PATH)
    experimental = deepcopy(entries[0])
    experimental["product_class_secondary"] = ["brand_new_tag"]
    experimental["experimental_secondary_tags"] = True

    validate_source_catalog([experimental])


def test_mirror_or_educational_source_cannot_be_promoted_without_review_override() -> None:
    entries = load_source_catalog(CATALOG_PATH)
    mirror = next(entry for entry in entries if entry["document_role"] == "mirror_discovery_only")
    promoted = deepcopy(mirror)
    promoted["allowed_as_fixture"] = True
    promoted["fixture_tier"] = 1

    with pytest.raises(SourceCatalogError, match="override_rationale"):
        validate_source_catalog([promoted])

    promoted["override_rationale"] = "Official source unavailable; reviewed rights and narrowed fixture excerpt."
    promoted["reviewed_by"] = "fixture-reviewer"
    promoted["reviewed_at"] = "2026-05-09"
    validate_source_catalog([promoted])


def test_yaml_catalog_has_no_duplicate_ids() -> None:
    raw = yaml.safe_load(CATALOG_PATH.read_text())
    ids = [entry["id"] for entry in raw["sources"]]
    assert len(ids) == len(set(ids))


def test_source_catalog_rejects_invalid_region_and_jurisdiction() -> None:
    entries = load_source_catalog(CATALOG_PATH)
    bad_region = deepcopy(entries[0])
    bad_region["region_family"] = "north-america"
    with pytest.raises(SourceCatalogError, match="invalid region_family"):
        validate_source_catalog([bad_region])

    bad_jurisdiction = deepcopy(entries[0])
    bad_jurisdiction["jurisdiction"] = "CAN"
    with pytest.raises(SourceCatalogError, match="invalid jurisdiction"):
        validate_source_catalog([bad_jurisdiction])


def test_source_catalog_rejects_schema_forbidden_runtime_values() -> None:
    entries = load_source_catalog(CATALOG_PATH)

    bad_tier = deepcopy(entries[0])
    bad_tier["fixture_tier"] = True
    with pytest.raises(SourceCatalogError, match="fixture_tier"):
        validate_source_catalog([bad_tier])

    bad_experimental_flag = deepcopy(entries[0])
    bad_experimental_flag["product_class_secondary"] = ["new_tag"]
    bad_experimental_flag["experimental_secondary_tags"] = "yes"
    with pytest.raises(SourceCatalogError, match="experimental_secondary_tags"):
        validate_source_catalog([bad_experimental_flag])

    bad_url = deepcopy(entries[0])
    bad_url["source_url"] = "https://bad url"
    with pytest.raises(SourceCatalogError, match="source_url"):
        validate_source_catalog([bad_url])

    mirror = next(entry for entry in entries if entry["document_role"] == "mirror_discovery_only")
    bad_review_fields = deepcopy(mirror)
    bad_review_fields.update(
        {
            "allowed_as_fixture": True,
            "fixture_tier": 1,
            "override_rationale": 123,
            "reviewed_by": "fixture-reviewer",
            "reviewed_at": "2026-05-09",
        }
    )
    with pytest.raises(SourceCatalogError, match="override review fields"):
        validate_source_catalog([bad_review_fields])
