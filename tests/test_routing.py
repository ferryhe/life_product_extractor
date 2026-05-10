from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from life_product_extractor.catalog import load_source_catalog_document
from life_product_extractor.fixtures import load_fixture_manifest_document
from life_product_extractor.resources import resource_text
from life_product_extractor.routing import (
    classify_fixture_manifest,
    classify_fixture_manifest_from_path,
    validate_routing_document,
)

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_FIXTURE_DIR = ROOT / "examples" / "fixtures" / "manulife_tier1_curated"


def test_classify_fixture_manifest_routes_manulife_tier1_bundle_deterministically() -> None:
    routing = classify_fixture_manifest_from_path(CANONICAL_FIXTURE_DIR / "manifest.json")
    validate_routing_document(routing)

    assert routing["fixture_set_id"] == "manulife_tier1_curated"
    assert routing["summary"] == {
        "document_count": 8,
        "scenario_count": 1,
        "primary_class_counts": {
            "ltc_di": 2,
            "participating_life": 1,
            "traditional_life": 3,
            "ul_iul": 2,
        },
    }

    routes_by_id = {document["document_id"]: document for document in routing["documents"]}
    assert all(route["classification_mode"] == "manifest_precedence" for route in routes_by_id.values())
    assert all(route["routing_confidence"] == 1.0 for route in routes_by_id.values())

    synergy = routes_by_id["synergy_combination_insurance"]
    assert synergy["product_class_primary"] == "traditional_life"
    assert set(synergy["product_class_secondary"]) == {"combination_product", "critical_illness", "disability"}
    assert synergy["routing_flags"] == ["multi_benefit"]

    ul_table = routes_by_id["manulife_universal_life_investment_accounts"]
    assert ul_table["product_class_primary"] == "ul_iul"
    assert set(ul_table["product_class_secondary"]) == {"investment_account_table", "supporting_table"}
    assert ul_table["routing_flags"] == ["supporting_table_source"]

    scenario = routing["paired_source_scenarios"][0]
    assert scenario["relation"] == "potentially_contradictory"
    assert scenario["product_class_primary"] == "ul_iul"
    assert scenario["routing_implication"] == "escalate_same_product_source_disagreements"
    assert set(scenario["product_class_secondary"]) == {"investment_account_table", "supporting_table", "universal_life"}


def test_classify_preserves_manifest_taxonomy_over_catalog_taxonomy() -> None:
    manifest = load_fixture_manifest_document(CANONICAL_FIXTURE_DIR / "manifest.json")
    manifest["documents"][0]["product_class_primary"] = "other"
    manifest["documents"][0]["product_class_secondary"] = ["direct_to_consumer"]
    catalog = load_source_catalog_document(ROOT / "examples" / "sources" / "manulife_sources.yaml")

    mutated_routing = classify_fixture_manifest(
        manifest,
        base_dir=CANONICAL_FIXTURE_DIR,
        catalog=catalog,
    )
    mutated = {document["document_id"]: document for document in mutated_routing["documents"]}
    assert mutated["family_term_life"]["product_class_primary"] == "other"
    assert mutated["family_term_life"]["product_class_secondary"] == ["direct_to_consumer"]
    assert mutated["family_term_life"]["routing_warnings"] == [
        "manifest taxonomy differs from source catalog; manifest value preserved by precedence"
    ]


def test_cli_classify_smoke_with_generated_fixture_manifest(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "fixtures"
    build_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "life_product_extractor.cli",
            "build-fixtures",
            "--out-dir",
            str(fixture_dir),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=True,
    )
    build_payload = json.loads(build_result.stdout)
    assert build_payload["ok"] is True

    routing_path = tmp_path / "routing.json"
    classify_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "life_product_extractor.cli",
            "classify",
            "--manifest",
            str(fixture_dir / "manifest.json"),
            "--out",
            str(routing_path),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(classify_result.stdout)
    assert payload == {
        "document_count": 8,
        "fixture_set_id": "manulife_tier1_curated",
        "ok": True,
        "routing_path": str(routing_path),
        "scenario_count": 1,
    }

    routing = json.loads(routing_path.read_text(encoding="utf-8"))
    validate_routing_document(routing)
    assert routing["summary"]["primary_class_counts"]["ul_iul"] == 2


def test_packaged_routing_schema_resource_matches_canonical_schema() -> None:
    assert resource_text("schemas/routing.schema.json") == (ROOT / "schemas" / "routing.schema.json").read_text()
