from __future__ import annotations

import json
from pathlib import Path

import pytest

from life_product_extractor.extract import extract_candidate_bundle
from life_product_extractor.fixtures import load_fixture_manifest_document
from life_product_extractor.review import (
    ReviewContractError,
    build_ai_review,
    build_validation_report,
    build_validation_report_from_path,
    validate_ai_review_document,
    validate_validation_report_document,
)
from life_product_extractor.routing import classify_fixture_manifest_from_path
from life_product_extractor.sections import sectionize_fixture_manifest_from_path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_FIXTURE_DIR = ROOT / "examples" / "fixtures" / "manulife_tier1_curated"


def test_validation_report_escalates_unknowns_and_unsupported_documents() -> None:
    candidate = _candidate_bundle()

    report = build_validation_report(candidate)

    validate_validation_report_document(report)
    assert report["candidate_fixture_set_id"] == "manulife_tier1_curated"
    assert report["summary"]["status"] == "blocked"
    assert report["candidate_digest"].startswith("sha256:")
    assert report["summary"]["needs_human_review_count"] > 0
    assert report["summary"]["blocked_count"] > 0
    assert any(issue["check"] == "explicit_unknown_not_auto_accepted" for issue in report["issues"])
    assert any(issue["check"] == "unsupported_document_not_auto_accepted" for issue in report["issues"])


def test_validation_report_blocks_low_confidence_auto_acceptance() -> None:
    candidate = _candidate_bundle()
    candidate["products"][0]["benefits"][1]["confidence"] = 0.5
    candidate["products"][0]["benefits"][1]["review_status"] = "ai_accepted"

    report = build_validation_report(candidate)

    assert report["summary"]["status"] == "blocked"
    assert any(issue["check"] == "low_confidence_auto_acceptance" for issue in report["issues"])


def test_ai_review_is_separate_and_does_not_auto_accept_unsupported_fields() -> None:
    candidate = _candidate_bundle()
    validation_report = build_validation_report(candidate)

    review = build_ai_review(candidate, validation_report=validation_report)

    validate_ai_review_document(review)
    assert review["candidate_fixture_set_id"] == candidate["fixture_set_id"]
    assert review["reviewer"]["skillpack"] == "north_america/mixed_participating_life_traditional_life_ul_iul"
    assert review["reviewer"]["product_classes"] == ["participating_life", "traditional_life", "ul_iul"]
    decisions = {field_review["decision"] for field_review in review["field_reviews"]}
    assert {"ai_accepted", "needs_human_review", "blocked"}.issubset(decisions)
    paths = [field_review["path"] for field_review in review["field_reviews"]]
    assert len(paths) == len(set(paths))
    blocked_reviews = [field_review for field_review in review["field_reviews"] if field_review["decision"] == "blocked"]
    assert blocked_reviews
    assert all("required_human_action" in field_review for field_review in blocked_reviews)
    assert any(field_review["reason_code"] == "explicit_unknown_requires_human_resolution" for field_review in blocked_reviews)


def test_ai_review_rejects_mismatched_validation_report() -> None:
    candidate = _candidate_bundle()
    validation_report = build_validation_report(candidate)
    validation_report["candidate_fixture_set_id"] = "other_fixture_set"

    with pytest.raises(ReviewContractError, match="does not match"):
        build_ai_review(candidate, validation_report=validation_report)


def test_ai_review_treats_already_reviewed_candidate_status_as_not_applicable() -> None:
    candidate = _candidate_bundle()
    candidate["products"][0]["benefits"][0]["review_status"] = "reviewed"
    candidate["products"][0]["explicit_unknowns"][0]["review_status"] = "reviewed"
    validation_report = build_validation_report(candidate)

    review = build_ai_review(candidate, validation_report=validation_report)

    reviews_by_path = {field_review["path"]: field_review for field_review in review["field_reviews"]}
    benefit_review = reviews_by_path["/products/0/benefits/0"]
    unknown_review = reviews_by_path["/products/0/explicit_unknowns/0"]
    assert benefit_review["decision"] == "not_applicable"
    assert benefit_review["reason_code"] == "candidate_already_reviewed"
    assert "required_human_action" not in benefit_review
    assert unknown_review["decision"] == "not_applicable"
    assert unknown_review["reason_code"] == "explicit_unknown_already_reviewed"


def test_validation_and_ai_review_json_round_trip(tmp_path: Path) -> None:
    candidate = _candidate_bundle()
    report = build_validation_report(candidate)
    review = build_ai_review(candidate, validation_report=report)

    report_path = tmp_path / "validation_report.json"
    review_path = tmp_path / "ai_review.json"
    report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
    review_path.write_text(json.dumps(review) + "\n", encoding="utf-8")

    assert json.loads(report_path.read_text())["summary"]["warning_count"] == report["summary"]["warning_count"]
    assert json.loads(review_path.read_text())["summary"]["blocked_count"] == review["summary"]["blocked_count"]


def test_validation_from_path_writes_blocked_report_for_contract_invalid_candidate(tmp_path: Path) -> None:
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps({"schema_version": "0.1", "fixture_set_id": ""}) + "\n", encoding="utf-8")

    report = build_validation_report_from_path(candidate_path)

    validate_validation_report_document(report)
    assert report["summary"]["status"] == "blocked"
    assert report["candidate_fixture_set_id"] == "unknown"
    assert report["run_id"] == "unknown-validation-v0-1"
    assert report["issues"][0]["path"] == "/"
    assert report["issues"][0]["severity"] == "error"
    assert report["issues"][0]["check"] == "candidate_bundle_contract"
    assert report["issues"][0]["review_decision"] == "blocked"


def _candidate_bundle() -> dict[str, object]:
    manifest = load_fixture_manifest_document(CANONICAL_FIXTURE_DIR / "manifest.json")
    routing = classify_fixture_manifest_from_path(CANONICAL_FIXTURE_DIR / "manifest.json")
    sections = sectionize_fixture_manifest_from_path(CANONICAL_FIXTURE_DIR / "manifest.json")
    return extract_candidate_bundle(
        manifest,
        base_dir=CANONICAL_FIXTURE_DIR,
        routing=routing,
        sections_documents=sections,
    )
