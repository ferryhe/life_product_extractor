from __future__ import annotations

import json
from pathlib import Path

import pytest

from life_product_extractor.extract import (
    CandidateContractError,
    extract_candidate_bundle,
    extract_candidate_bundle_from_paths,
    validate_candidate_bundle_document,
)
from life_product_extractor.fixtures import load_fixture_manifest_document
from life_product_extractor.routing import classify_fixture_manifest_from_path
from life_product_extractor.sections import sectionize_fixture_manifest_from_path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_FIXTURE_DIR = ROOT / "examples" / "fixtures" / "manulife_tier1_curated"


def test_extract_candidate_bundle_for_pr_e_scope_is_deterministic(tmp_path: Path) -> None:
    manifest_path = CANONICAL_FIXTURE_DIR / "manifest.json"

    first = extract_candidate_bundle_from_paths(
        manifest_path,
        routing_path=_write_tmp_artifact(tmp_path / "routing-first.json", classify_fixture_manifest_from_path(manifest_path)),
        sections_path=_write_tmp_jsonl(tmp_path / "sections-first.jsonl", sectionize_fixture_manifest_from_path(manifest_path)),
    )
    second = extract_candidate_bundle_from_paths(
        manifest_path,
        routing_path=_write_tmp_artifact(tmp_path / "routing-second.json", classify_fixture_manifest_from_path(manifest_path)),
        sections_path=_write_tmp_jsonl(tmp_path / "sections-second.jsonl", sectionize_fixture_manifest_from_path(manifest_path)),
    )

    assert first == second
    validate_candidate_bundle_document(first)
    assert first["summary"] == {
        "product_count": 3,
        "supported_document_count": 4,
        "unsupported_document_count": 4,
    }

    products = {product["product_id"]: product for product in first["products"]}
    assert set(products) == {
        "family_term_life",
        "manulife_par_whole_life",
        "manulife_universal_life",
    }

    family_term = products["family_term_life"]
    assert family_term["source_document_ids"] == ["family_term_life"]
    assert {item["benefit_type"] for item in family_term["benefits"]} == {
        "death_benefit",
        "policy_option",
    }
    assert {item["option_type"] for item in family_term["benefits"] if item["benefit_type"] == "policy_option"} == {
        "renewal_option",
        "conversion_option",
    }
    assert family_term["explicit_unknowns"] == [
        {
            "id": "family_term_life-unknown-surrender-lapse",
            "path": "/decrements/surrender_lapse",
            "label": "Surrender or lapse decrement",
            "status": "not_in_excerpt",
            "reason": "The Family Term curated excerpt does not describe surrender or lapse mechanics.",
            "evidence_refs": ["family_term_life-evidence-0001"],
            "confidence": 1.0,
            "review_status": "blocked",
        }
    ]

    par = products["manulife_par_whole_life"]
    dividend = next(item for item in par["benefits"] if item["benefit_type"] == "dividend_option")
    assert dividend["guarantee_status"] == "non_guaranteed"
    assert dividend["review_status"] == "ai_accepted"
    cash_value = next(item for item in par["benefits"] if item["benefit_type"] == "cash_value_accumulation")
    assert cash_value["guarantee_status"] == "guaranteed"

    ul = products["manulife_universal_life"]
    assert ul["source_document_ids"] == [
        "manulife_universal_life_page",
        "manulife_universal_life_investment_accounts",
    ]
    assert ul["paired_source_scenario_ids"] == ["manulife_ul_overlap_and_availability_tension"]
    account_value = next(item for item in ul["benefits"] if item["benefit_type"] == "account_value_crediting")
    assert account_value["review_status"] == "ai_accepted"
    investment_accounts = next(item for item in ul["benefits"] if item["benefit_type"] == "investment_account_option")
    assert investment_accounts["options"] == ["Fixed Account", "Daily Interest Account", "Index Account"]
    table_evidence = next(item for item in ul["evidence"] if item.get("artifact_id"))
    assert table_evidence["artifact_id"] == "manulife_universal_life_investment_accounts-table-0005-bullet-list"
    assert "Fixed Account" in table_evidence["source_quote"]
    assert any(
        unknown["path"] == "/benefits/account_value_crediting/calculation_method"
        for unknown in ul["explicit_unknowns"]
    )

    assert first["unsupported_documents"] == [
        {
            "document_id": "lifecheque_critical_illness",
            "product_name": "Lifecheque critical illness insurance",
            "product_class_primary": "traditional_life",
            "reason": "not_in_pr_e_scope",
        },
        {
            "document_id": "livingcare_product_guide_excerpt",
            "product_name": "LivingCare product guide",
            "product_class_primary": "ltc_di",
            "reason": "not_in_pr_e_scope",
        },
        {
            "document_id": "proguard_disability_client_guide_excerpt",
            "product_name": "Proguard Series disability insurance client guide",
            "product_class_primary": "ltc_di",
            "reason": "not_in_pr_e_scope",
        },
        {
            "document_id": "synergy_combination_insurance",
            "product_name": "Manulife Synergy combination insurance",
            "product_class_primary": "traditional_life",
            "reason": "not_in_pr_e_scope",
        },
    ]


def test_validate_candidate_bundle_rejects_unknown_evidence_ref() -> None:
    manifest = load_fixture_manifest_document(CANONICAL_FIXTURE_DIR / "manifest.json")
    routing = classify_fixture_manifest_from_path(CANONICAL_FIXTURE_DIR / "manifest.json")
    sections = sectionize_fixture_manifest_from_path(CANONICAL_FIXTURE_DIR / "manifest.json")

    bundle = extract_candidate_bundle(
        manifest,
        base_dir=CANONICAL_FIXTURE_DIR,
        routing=routing,
        sections_documents=sections,
    )
    bundle["products"][0]["benefits"][0]["evidence_refs"] = ["missing-evidence"]

    with pytest.raises(CandidateContractError, match="references unknown evidence ids"):
        validate_candidate_bundle_document(bundle)


def test_extract_candidate_bundle_rejects_missing_required_pr_e_fixture_ids() -> None:
    manifest = load_fixture_manifest_document(CANONICAL_FIXTURE_DIR / "manifest.json")
    routing = classify_fixture_manifest_from_path(CANONICAL_FIXTURE_DIR / "manifest.json")
    sections = sectionize_fixture_manifest_from_path(CANONICAL_FIXTURE_DIR / "manifest.json")

    manifest["documents"] = [
        document for document in manifest["documents"] if document["fixture_id"] != "manulife_par_whole_life"
    ]

    with pytest.raises(CandidateContractError, match="missing required PR E fixture ids"):
        extract_candidate_bundle(
            manifest,
            base_dir=CANONICAL_FIXTURE_DIR,
            routing=routing,
            sections_documents=sections,
        )


def test_validate_candidate_bundle_rejects_unknown_trigger_decrement_ids() -> None:
    manifest = load_fixture_manifest_document(CANONICAL_FIXTURE_DIR / "manifest.json")
    routing = classify_fixture_manifest_from_path(CANONICAL_FIXTURE_DIR / "manifest.json")
    sections = sectionize_fixture_manifest_from_path(CANONICAL_FIXTURE_DIR / "manifest.json")

    bundle = extract_candidate_bundle(
        manifest,
        base_dir=CANONICAL_FIXTURE_DIR,
        routing=routing,
        sections_documents=sections,
    )
    bundle["products"][0]["benefits"][0]["trigger_decrement_ids"] = ["missing-decrement"]

    with pytest.raises(CandidateContractError, match="unknown trigger_decrement_ids"):
        validate_candidate_bundle_document(bundle)


def test_validate_candidate_bundle_rejects_invalid_trigger_decrement_ids_shape() -> None:
    manifest = load_fixture_manifest_document(CANONICAL_FIXTURE_DIR / "manifest.json")
    routing = classify_fixture_manifest_from_path(CANONICAL_FIXTURE_DIR / "manifest.json")
    sections = sectionize_fixture_manifest_from_path(CANONICAL_FIXTURE_DIR / "manifest.json")

    bundle = extract_candidate_bundle(
        manifest,
        base_dir=CANONICAL_FIXTURE_DIR,
        routing=routing,
        sections_documents=sections,
    )
    bundle["products"][0]["benefits"][0]["trigger_decrement_ids"] = 1

    with pytest.raises(CandidateContractError, match="candidate bundle does not match"):
        validate_candidate_bundle_document(bundle)


def test_validate_candidate_bundle_rejects_unknown_paired_source_scenario_ids() -> None:
    manifest = load_fixture_manifest_document(CANONICAL_FIXTURE_DIR / "manifest.json")
    routing = classify_fixture_manifest_from_path(CANONICAL_FIXTURE_DIR / "manifest.json")
    sections = sectionize_fixture_manifest_from_path(CANONICAL_FIXTURE_DIR / "manifest.json")

    bundle = extract_candidate_bundle(
        manifest,
        base_dir=CANONICAL_FIXTURE_DIR,
        routing=routing,
        sections_documents=sections,
    )
    ul_product = next(product for product in bundle["products"] if product["product_id"] == "manulife_universal_life")
    ul_product["paired_source_scenario_ids"] = ["missing-scenario-id"]

    with pytest.raises(CandidateContractError, match="unknown manifest scenario ids"):
        validate_candidate_bundle_document(
            bundle,
            paired_source_scenarios={
                "manulife_ul_overlap_and_availability_tension": {
                    "manulife_universal_life_page",
                    "manulife_universal_life_investment_accounts",
                }
            },
        )


def test_validate_candidate_bundle_rejects_mismatched_paired_source_scenario_ids() -> None:
    manifest = load_fixture_manifest_document(CANONICAL_FIXTURE_DIR / "manifest.json")
    routing = classify_fixture_manifest_from_path(CANONICAL_FIXTURE_DIR / "manifest.json")
    sections = sectionize_fixture_manifest_from_path(CANONICAL_FIXTURE_DIR / "manifest.json")

    bundle = extract_candidate_bundle(
        manifest,
        base_dir=CANONICAL_FIXTURE_DIR,
        routing=routing,
        sections_documents=sections,
    )
    family_product = next(product for product in bundle["products"] if product["product_id"] == "family_term_life")
    family_product["paired_source_scenario_ids"] = ["manulife_ul_overlap_and_availability_tension"]

    with pytest.raises(CandidateContractError, match="do not match source_document_ids"):
        validate_candidate_bundle_document(
            bundle,
            paired_source_scenarios={
                "manulife_ul_overlap_and_availability_tension": {
                    "manulife_universal_life_page",
                    "manulife_universal_life_investment_accounts",
                }
            },
        )


def _write_tmp_artifact(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _write_tmp_jsonl(path: Path, documents: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(document, ensure_ascii=False) for document in documents) + "\n", encoding="utf-8")
    return path
