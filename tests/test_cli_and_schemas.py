from __future__ import annotations

import json
import os
import site
import subprocess
import sys
import sysconfig
from pathlib import Path

import jsonschema
import pytest
import yaml
from referencing import Registry, Resource

from life_product_extractor import cli
from life_product_extractor.catalog import (
    ALLOWED_AUTHORITY_LEVELS,
    ALLOWED_DOCUMENT_ROLES,
    ALLOWED_JURISDICTIONS,
    ALLOWED_PRIMARY_CLASSES,
    ALLOWED_REGION_FAMILIES,
    ALLOWED_SECONDARY_TAGS,
)
from life_product_extractor.extract import load_candidate_bundle_document, validate_candidate_bundle_document
from life_product_extractor.fixtures import FixtureContractError
from life_product_extractor.learn import (
    LearningContractError,
    build_skill_improvement_candidates_from_reviewed,
    build_skill_improvement_candidates_from_reviewed_runs,
    validate_skill_improvement_candidates_document,
)
from life_product_extractor.resources import resource_text
from life_product_extractor.review import load_ai_review_document, load_validation_report_document
from life_product_extractor.routing import validate_routing_document
from life_product_extractor.sections import load_sections_jsonl, validate_sections_document
from life_product_extractor.status import (
    StatusContractError,
    build_status_report_from_artifacts,
    validate_status_report_document,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"


def test_schema_files_are_valid_json_schema() -> None:
    schema_files = sorted(SCHEMAS.glob("*.json"))
    assert schema_files, "expected schema files"
    for path in schema_files:
        schema = json.loads(path.read_text())
        jsonschema.validators.validator_for(schema).check_schema(schema)


def test_source_catalog_schema_validates_catalog_and_matches_runtime_enums() -> None:
    catalog = yaml.safe_load((ROOT / "examples" / "sources" / "manulife_sources.yaml").read_text())
    schema = json.loads((SCHEMAS / "source_catalog.schema.json").read_text())

    jsonschema.Draft202012Validator(schema).validate(catalog)

    source_def = schema["$defs"]["source"]
    assert set(source_def["properties"]["region_family"]["enum"]) == ALLOWED_REGION_FAMILIES
    assert set(source_def["properties"]["jurisdiction"]["enum"]) == ALLOWED_JURISDICTIONS
    assert set(source_def["properties"]["product_class_primary"]["enum"]) == ALLOWED_PRIMARY_CLASSES
    assert set(schema["$defs"]["secondaryTag"]["enum"]) == ALLOWED_SECONDARY_TAGS
    assert set(source_def["properties"]["document_role"]["enum"]) == ALLOWED_DOCUMENT_ROLES
    assert set(source_def["properties"]["authority_level"]["enum"]) == ALLOWED_AUTHORITY_LEVELS


def test_documented_schema_paths_exist() -> None:
    documented_schema_paths = [
        "manifest.schema.json",
        "routing.schema.json",
        "sections_structured.schema.json",
        "candidate_product.schema.json",
        "candidate_bundle.schema.json",
        "validation_report.schema.json",
        "ai_review.schema.json",
        "review_decisions.schema.json",
        "reviewed_product.schema.json",
        "status_report.schema.json",
        "skill_improvement_candidates.schema.json",
    ]
    for file_name in documented_schema_paths:
        assert (SCHEMAS / file_name).exists()


def test_packaged_resources_match_canonical_development_artifacts() -> None:
    assert resource_text("schemas/source_catalog.schema.json") == (SCHEMAS / "source_catalog.schema.json").read_text()
    assert resource_text("schemas/manifest.schema.json") == (SCHEMAS / "manifest.schema.json").read_text()
    assert resource_text("schemas/routing.schema.json") == (SCHEMAS / "routing.schema.json").read_text()
    assert resource_text("schemas/sections_structured.schema.json") == (
        SCHEMAS / "sections_structured.schema.json"
    ).read_text()
    assert resource_text("schemas/candidate_product.schema.json") == (
        SCHEMAS / "candidate_product.schema.json"
    ).read_text()
    assert resource_text("schemas/candidate_bundle.schema.json") == (
        SCHEMAS / "candidate_bundle.schema.json"
    ).read_text()
    assert resource_text("schemas/validation_report.schema.json") == (
        SCHEMAS / "validation_report.schema.json"
    ).read_text()
    assert resource_text("schemas/ai_review.schema.json") == (SCHEMAS / "ai_review.schema.json").read_text()
    assert resource_text("schemas/review_decisions.schema.json") == (
        SCHEMAS / "review_decisions.schema.json"
    ).read_text()
    assert resource_text("schemas/reviewed_product.schema.json") == (
        SCHEMAS / "reviewed_product.schema.json"
    ).read_text()
    assert resource_text("schemas/status_report.schema.json") == (SCHEMAS / "status_report.schema.json").read_text()
    assert resource_text("schemas/skill_improvement_candidates.schema.json") == (
        SCHEMAS / "skill_improvement_candidates.schema.json"
    ).read_text()
    assert resource_text("examples/sources/manulife_sources.yaml") == (
        ROOT / "examples" / "sources" / "manulife_sources.yaml"
    ).read_text()


def _schema_validator(file_name: str) -> jsonschema.Draft202012Validator:
    schema = json.loads((SCHEMAS / file_name).read_text())
    candidate_schema = json.loads((SCHEMAS / "candidate_product.schema.json").read_text())
    registry = Registry().with_resource(candidate_schema["$id"], Resource.from_contents(candidate_schema))
    return jsonschema.Draft202012Validator(schema, registry=registry)


def _minimal_candidate() -> dict[str, object]:
    return {
        "schema_version": "0.1",
        "product_id": "sample_product",
        "product_identity": {
            "product_name": "Sample product",
            "region_family": "north_america",
            "jurisdiction": "CA",
            "product_class_primary": "traditional_life",
        },
        "source_document_ids": ["document_1"],
        "paired_source_scenario_ids": ["scenario_1"],
        "decrements": [],
        "benefits": [
            {
                "id": "benefit_1",
                "label": "Death benefit",
                "evidence_refs": ["evidence_1"],
                "confidence": 0.91,
                "review_status": "ai_accepted",
            }
        ],
        "explicit_unknowns": [
            {
                "id": "unknown_1",
                "path": "/decrements/surrender_lapse",
                "label": "Surrender or lapse decrement",
                "status": "not_in_excerpt",
                "reason": "The excerpt does not describe surrender or lapse mechanics.",
                "review_status": "blocked",
                "confidence": 1.0,
            }
        ],
        "evidence": [
            {
                "id": "evidence_1",
                "source_id": "source_1",
                "document_id": "document_1",
                "section_id": "section_1",
                "line_start": 10,
                "line_end": 12,
                "span_start": 240,
                "span_end": 312,
                "source_quote": "The policy provides a death benefit.",
            }
        ],
    }


def test_candidate_product_requires_minimum_audit_shape() -> None:
    validator = _schema_validator("candidate_product.schema.json")
    candidate = _minimal_candidate()
    validator.validate(candidate)

    missing_evidence = candidate | {"evidence": []}
    assert any(list(error.path) == ["evidence"] for error in validator.iter_errors(missing_evidence))

    empty_identity = candidate | {"product_identity": {}}
    assert any(list(error.path) == ["product_identity"] for error in validator.iter_errors(empty_identity))

    invalid_finding = candidate | {"benefits": [{"id": "benefit_1", "label": "Death benefit"}]}
    assert any(list(error.path) == ["benefits", 0] for error in validator.iter_errors(invalid_finding))

    missing_coordinates = _minimal_candidate()
    missing_coordinates["evidence"] = [
        {
            "id": "evidence_1",
            "source_id": "source_1",
            "document_id": "document_1",
            "source_quote": "The policy provides a death benefit.",
        }
    ]
    assert any(list(error.path) == ["evidence", 0] for error in validator.iter_errors(missing_coordinates))


def test_candidate_bundle_schema_accepts_minimal_bundle_artifact() -> None:
    bundle = {
        "schema_version": "0.1",
        "fixture_set_id": "sample_fixture_set",
        "extraction_strategy": {
            "deterministic": True,
            "supported_product_classes": ["traditional_life"],
            "supported_fixture_ids": ["sample_fixture"],
        },
        "summary": {
            "product_count": 1,
            "supported_document_count": 1,
            "unsupported_document_count": 0,
        },
        "products": [_minimal_candidate()],
        "unsupported_documents": [],
    }

    validate_candidate_bundle_document(bundle)


def test_ai_review_schema_rejects_empty_field_reviews_and_accepts_minimal_review() -> None:
    validator = _schema_validator("ai_review.schema.json")

    empty_reviews = {
        "schema_version": "0.1",
        "run_id": "run_001",
        "candidate_fixture_set_id": "sample_fixture_set",
        "candidate_digest": "sha256:" + "0" * 64,
        "reviewer": {"type": "ai", "skillpack": "north_america/traditional_life", "version": "0.1.0"},
        "summary": {"ai_accepted_count": 0, "needs_human_review_count": 0, "blocked_count": 0},
        "field_reviews": [],
    }
    assert any(list(error.path) == ["field_reviews"] for error in validator.iter_errors(empty_reviews))

    minimal_review = {
        "schema_version": "0.1",
        "run_id": "run_001",
        "candidate_fixture_set_id": "sample_fixture_set",
        "candidate_digest": "sha256:" + "0" * 64,
        "reviewer": {"type": "ai", "skillpack": "north_america/traditional_life", "version": "0.1.0"},
        "summary": {"ai_accepted_count": 0, "needs_human_review_count": 1, "blocked_count": 0},
        "field_reviews": [
            {
                "path": "/benefits/0/calculation_method",
                "decision": "needs_human_review",
                "materiality": "high",
                "reason_code": "formula_references_unparsed_table",
                "rationale": "The quote references a table that is not yet structured.",
                "required_human_action": "Confirm formula and table scope."
            }
        ],
    }
    validator.validate(minimal_review)

    missing_fixture_set = dict(minimal_review)
    del missing_fixture_set["candidate_fixture_set_id"]
    assert any(list(error.path) == [] and "candidate_fixture_set_id" in error.message for error in validator.iter_errors(missing_fixture_set))

    missing_candidate_digest = dict(minimal_review)
    del missing_candidate_digest["candidate_digest"]
    assert any(list(error.path) == [] and "candidate_digest" in error.message for error in validator.iter_errors(missing_candidate_digest))

    invalid_candidate_digest = dict(minimal_review)
    invalid_candidate_digest["candidate_digest"] = "not-a-digest"
    assert any(list(error.path) == ["candidate_digest"] for error in validator.iter_errors(invalid_candidate_digest))


def test_reviewed_product_composes_candidate_bundle_contract_and_requires_review_metadata() -> None:
    schema = json.loads((SCHEMAS / "reviewed_product.schema.json").read_text())
    assert schema["allOf"][0]["$ref"] == "candidate_bundle.schema.json"
    candidate_bundle_schema = json.loads((SCHEMAS / "candidate_bundle.schema.json").read_text())
    candidate_product_schema = json.loads((SCHEMAS / "candidate_product.schema.json").read_text())
    registry = Registry().with_resources(
        [
            (candidate_bundle_schema["$id"], Resource.from_contents(candidate_bundle_schema)),
            (candidate_product_schema["$id"], Resource.from_contents(candidate_product_schema)),
        ]
    )
    validator = jsonschema.Draft202012Validator(schema, registry=registry)
    reviewed_bundle = {
        "schema_version": "0.1",
        "fixture_set_id": "fixture_set",
        "extraction_strategy": {
            "deterministic": True,
            "supported_product_classes": ["traditional_life"],
            "supported_fixture_ids": ["fixture_set"],
        },
        "summary": {"product_count": 0, "supported_document_count": 0, "unsupported_document_count": 0},
        "products": [],
        "unsupported_documents": [],
    }

    assert any(list(error.path) == [] and "review_metadata" in error.message for error in validator.iter_errors(reviewed_bundle))

    reviewed_bundle["review_metadata"] = {
        "schema_version": "0.1",
        "source": "review_decisions",
        "run_id": "fixture_set-validation-v0-1",
        "reviewer": "fixture-reviewer",
        "decisions_applied": [],
    }
    validator.validate(reviewed_bundle)

    missing_run_id_bundle = json.loads(json.dumps(reviewed_bundle))
    del missing_run_id_bundle["review_metadata"]["run_id"]
    assert any(
        list(error.path) == ["review_metadata"] and "run_id" in error.message
        for error in validator.iter_errors(missing_run_id_bundle)
    )

    invalid_bundle = reviewed_bundle | {"products": [{"bogus": True}]}
    assert any(list(error.path) == ["products", 0] for error in validator.iter_errors(invalid_bundle))

    reviewed_bundle["review_metadata"]["decisions_applied"] = [{"path": "/products/0/benefits/not-a-number", "decision": "reviewed"}]
    assert any(
        list(error.path) == ["review_metadata", "decisions_applied", 0, "path"]
        for error in validator.iter_errors(reviewed_bundle)
    )

    reviewed_bundle["review_metadata"]["decisions_applied"] = [{"path": "/products/0/benefits/0", "decision": "invented"}]
    assert any(
        list(error.path) == ["review_metadata", "decisions_applied", 0, "decision"]
        for error in validator.iter_errors(reviewed_bundle)
    )


def test_skill_improvement_candidates_schema_requires_proposal_guardrails() -> None:
    validator = _schema_validator("skill_improvement_candidates.schema.json")
    proposal = {
        "schema_version": "0.1",
        "run_id": "run_001",
        "fixture_set_id": "fixture_set",
        "source": "reviewed_product",
        "summary": {
            "candidate_count": 1,
            "target_skillpack_count": 1,
            "requires_fixture_count": 1,
            "auto_applied_count": 0,
        },
        "candidates": [
            {
                "id": "skill_candidate_001",
                "target_skillpack": "north_america/traditional_life",
                "evidence_runs": [
                    {
                        "run_id": "run_001",
                        "fixture_set_id": "fixture_set",
                        "product_id": "sample_product",
                        "decision_path": "/products/0/benefits/0",
                        "decision": "reviewed",
                        "finding_id": "benefit_1",
                        "finding_label": "Death benefit",
                        "confidence": 0.91,
                        "review_status": "reviewed",
                        "evidence_refs": ["evidence_1"],
                        "evidence_spans": [
                            {
                                "id": "evidence_1",
                                "source_id": "source_1",
                                "document_id": "document_1",
                                "section_id": "section_1",
                                "line_start": 10,
                                "line_end": 12,
                                "span_start": 240,
                                "span_end": 312,
                                "source_quote": "The policy provides a death benefit.",
                            }
                        ],
                    }
                ],
                "proposed_change": {
                    "change_type": "extraction_rule",
                    "scope": "benefits/0",
                    "rationale": "Human correction should be reviewed before activation.",
                    "status": "proposed_only",
                },
                "required_fixture": {
                    "fixture_set_id": "fixture_set-skill-candidate-001",
                    "description": "Regression fixture proving the proposed change.",
                    "must_fail_before_activation": True,
                },
            }
        ],
    }
    validator.validate(proposal)

    missing_source = json.loads(json.dumps(proposal))
    del missing_source["source"]
    assert any(list(error.path) == [] and "source" in error.message for error in validator.iter_errors(missing_source))

    auto_applied = json.loads(json.dumps(proposal))
    auto_applied["summary"]["auto_applied_count"] = 1
    assert any(list(error.path) == ["summary", "auto_applied_count"] for error in validator.iter_errors(auto_applied))

    missing_fixture = json.loads(json.dumps(proposal))
    del missing_fixture["candidates"][0]["required_fixture"]
    assert any(list(error.path) == ["candidates", 0] and "required_fixture" in error.message for error in validator.iter_errors(missing_fixture))


def test_build_skill_improvement_candidates_from_reviewed_is_proposed_only() -> None:
    reviewed = {
        "schema_version": "0.1",
        "fixture_set_id": "fixture_set_a",
        "extraction_strategy": {
            "deterministic": True,
            "supported_product_classes": ["traditional_life"],
            "supported_fixture_ids": ["fixture_set"],
        },
        "summary": {"product_count": 1, "supported_document_count": 1, "unsupported_document_count": 0},
        "products": [_minimal_candidate()],
        "unsupported_documents": [],
        "review_metadata": {
            "schema_version": "0.1",
            "source": "review_decisions",
            "run_id": "fixture_set_a-validation-v0-1",
            "reviewer": "fixture-reviewer",
            "decisions_applied": [
                {
                    "path": "/products/0/benefits/0",
                    "decision": "reviewed",
                    "reviewer_note": "Confirmed death benefit wording.",
                }
            ],
        },
    }
    recurring_reviewed = json.loads(json.dumps(reviewed))
    recurring_reviewed["fixture_set_id"] = "fixture_set_b"
    recurring_reviewed["review_metadata"]["run_id"] = "fixture_set_b-validation-v0-1"

    original = json.loads(json.dumps(reviewed))
    single_run_proposal = build_skill_improvement_candidates_from_reviewed(reviewed)
    proposal = build_skill_improvement_candidates_from_reviewed_runs([reviewed, recurring_reviewed])

    validate_skill_improvement_candidates_document(proposal)
    assert reviewed == original
    assert single_run_proposal["summary"]["candidate_count"] == 0
    assert proposal["summary"] == {
        "candidate_count": 1,
        "target_skillpack_count": 1,
        "requires_fixture_count": 1,
        "auto_applied_count": 0,
    }
    [candidate] = proposal["candidates"]
    assert candidate["target_skillpack"] == "north_america/traditional_life"
    assert [evidence["run_id"] for evidence in candidate["evidence_runs"]] == [
        "fixture_set_a-validation-v0-1",
        "fixture_set_b-validation-v0-1",
    ]
    assert candidate["evidence_runs"][0]["decision_path"] == "/products/0/benefits/0"
    assert candidate["evidence_runs"][0]["source_quote"] == "The policy provides a death benefit."
    assert candidate["evidence_runs"][0]["confidence"] == 0.91
    assert candidate["evidence_runs"][0]["review_status"] == "ai_accepted"
    assert candidate["evidence_runs"][0]["evidence_spans"] == reviewed["products"][0]["evidence"]
    assert candidate["proposed_change"]["scope"] == "benefits/benefit_1"
    assert candidate["proposed_change"]["status"] == "proposed_only"
    assert candidate["required_fixture"]["must_fail_before_activation"] is True
    reversed_proposal = build_skill_improvement_candidates_from_reviewed_runs([recurring_reviewed, reviewed])
    assert reversed_proposal == proposal


def test_skill_improvement_candidates_do_not_merge_different_findings_by_array_position() -> None:
    reviewed = {
        "schema_version": "0.1",
        "fixture_set_id": "fixture_set_a",
        "extraction_strategy": {
            "deterministic": True,
            "supported_product_classes": ["traditional_life"],
            "supported_fixture_ids": ["fixture_set"],
        },
        "summary": {"product_count": 1, "supported_document_count": 1, "unsupported_document_count": 0},
        "products": [_minimal_candidate()],
        "unsupported_documents": [],
        "review_metadata": {
            "schema_version": "0.1",
            "source": "review_decisions",
            "run_id": "fixture_set_a-validation-v0-1",
            "reviewer": "fixture-reviewer",
            "decisions_applied": [{"path": "/products/0/benefits/0", "decision": "reviewed"}],
        },
    }
    other_reviewed = json.loads(json.dumps(reviewed))
    other_reviewed["fixture_set_id"] = "fixture_set_b"
    other_reviewed["review_metadata"]["run_id"] = "fixture_set_b-validation-v0-1"
    other_reviewed["products"][0]["benefits"][0]["id"] = "benefit_conversion_option"
    other_reviewed["products"][0]["benefits"][0]["label"] = "Conversion option"

    proposal = build_skill_improvement_candidates_from_reviewed_runs([reviewed, other_reviewed])

    assert proposal["summary"]["candidate_count"] == 0


def test_build_skill_improvement_candidates_validates_reviewed_contract() -> None:
    invalid_reviewed = {
        "fixture_set_id": "fixture_set",
        "products": [
            {
                "product_id": "sample_product",
                "product_identity": {"region_family": "north_america", "product_class_primary": "traditional_life"},
                "benefits": [{"evidence_refs": [], "review_status": "reviewed"}],
            }
        ],
        "review_metadata": {
            "run_id": "run_001",
            "decisions_applied": [{"path": "/products/0/benefits/0", "decision": "reviewed"}],
        },
    }

    with pytest.raises(LearningContractError, match="reviewed product"):
        build_skill_improvement_candidates_from_reviewed(invalid_reviewed)


def test_cli_help_works() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "life_product_extractor.cli", "--help"],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=True,
    )
    assert "life-extract" in result.stdout
    assert "validate-catalog" in result.stdout
    assert "classify" in result.stdout
    assert "sectionize" in result.stdout
    assert "extract" in result.stdout
    assert "validate" in result.stdout
    assert "ai-review" in result.stdout
    assert "learn" in result.stdout


def test_cli_reports_missing_catalog_without_traceback() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "life_product_extractor.cli",
            "validate-catalog",
            "--catalog",
            "/does/not/exist",
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "could not read source catalog" in payload["error"]


def test_cli_validates_default_catalog() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "life_product_extractor.cli",
            "validate-catalog",
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["source_count"] >= 20


def test_cli_builds_default_fixtures(tmp_path: Path) -> None:
    out_dir = tmp_path / "fixtures"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "life_product_extractor.cli",
            "build-fixtures",
            "--out-dir",
            str(out_dir),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["document_count"] == 8
    assert payload["scenario_count"] == 1
    assert (out_dir / "manifest.json").exists()


def test_sections_schema_accepts_minimal_document_artifact() -> None:
    sections_document = {
        "schema_version": "0.1",
        "fixture_set_id": "sample_fixture_set",
        "document_id": "sample_fixture",
        "source_catalog_id": "sample_source",
        "product_name": "Sample product",
        "document_role": "product_marketing_page",
        "source_type": "html_page_excerpt",
        "source_url": "https://example.com/product",
        "markdown_path": "documents/sample.md",
        "sectionization_strategy": {
            "deterministic": True,
            "html_escaped_quotes": True,
            "low_value_labeling": True,
            "table_artifacts_enabled": True,
        },
        "source_provenance": {
            "raw_line_count": 6,
            "selected_line_numbers": [1, 2, 3, 4],
            "omitted_line_ranges": [{"start": 5, "end": 6}],
        },
        "sections": [
            {
                "section_id": "sample_fixture-sec-0001-sample-product",
                "heading": {"text": "Sample product", "level": 1},
                "heading_path": ["Sample product"],
                "line_start": 1,
                "line_end": 4,
                "body_line_start": 3,
                "body_line_end": 4,
                "content_types": ["paragraph"],
                "labels": ["primary_content"],
                "table_artifact_ids": [],
                "source_quote": "# Sample product\n\nCore benefit text.",
            }
        ],
        "table_artifacts": [],
    }

    validate_sections_document(sections_document)


def test_sections_schema_rejects_raw_angle_brackets_in_section_and_table_quotes() -> None:
    validator = _schema_validator("sections_structured.schema.json")
    document = {
        "schema_version": "0.1",
        "fixture_set_id": "sample_fixture_set",
        "document_id": "sample_fixture",
        "source_catalog_id": "sample_source",
        "product_name": "Sample product",
        "document_role": "product_marketing_page",
        "source_type": "html_page_excerpt",
        "source_url": "https://example.com/product",
        "markdown_path": "documents/sample.md",
        "sectionization_strategy": {
            "deterministic": True,
            "html_escaped_quotes": True,
            "low_value_labeling": True,
            "table_artifacts_enabled": True,
        },
        "source_provenance": {
            "raw_line_count": 4,
            "selected_line_numbers": [1, 2, 3, 4],
            "omitted_line_ranges": [],
        },
        "sections": [
            {
                "section_id": "sample_fixture-sec-0001-sample-product",
                "heading": {"text": "Sample product", "level": 1},
                "heading_path": ["Sample product"],
                "line_start": 1,
                "line_end": 4,
                "body_line_start": 2,
                "body_line_end": 4,
                "content_types": ["paragraph", "table"],
                "labels": ["primary_content"],
                "table_artifact_ids": ["sample_fixture-table-0003-table"],
                "source_quote": "# Sample product\n\nCore benefit &lt;safe&gt; text.",
            }
        ],
        "table_artifacts": [
            {
                "table_id": "sample_fixture-table-0003-table",
                "section_id": "sample_fixture-sec-0001-sample-product",
                "artifact_type": "markdown_table",
                "line_start": 3,
                "line_end": 4,
                "source_quote": "| &lt;safe&gt; | value |",
                "rows": [["raw", "value"]],
            }
        ],
    }

    validator.validate(document)

    document["sections"][0]["source_quote"] = "# Sample product\n\nCore benefit <unsafe> text."
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(document)

    document["sections"][0]["source_quote"] = "# Sample product\n\nCore benefit &lt;safe&gt; text."
    document["table_artifacts"][0]["source_quote"] = "| <raw> | value |"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(document)


def test_cli_sectionizes_manifest_into_jsonl(tmp_path: Path) -> None:
    out_path = tmp_path / "sections_structured.jsonl"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "life_product_extractor.cli",
            "sectionize",
            "--manifest",
            str(ROOT / "examples" / "fixtures" / "manulife_tier1_curated" / "manifest.json"),
            "--out",
            str(out_path),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["document_count"] == 8
    documents = load_sections_jsonl(out_path)
    assert len(documents) == 8
    assert documents[0]["schema_version"] == "0.1"


def test_cli_extracts_candidate_bundle_from_manifest_routing_and_sections(tmp_path: Path) -> None:
    routing_path = tmp_path / "routing.json"
    sections_path = tmp_path / "sections_structured.jsonl"
    candidate_path = tmp_path / "candidate.json"

    classify_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "life_product_extractor.cli",
            "classify",
            "--manifest",
            str(ROOT / "examples" / "fixtures" / "manulife_tier1_curated" / "manifest.json"),
            "--out",
            str(routing_path),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(classify_result.stdout)["ok"] is True

    sectionize_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "life_product_extractor.cli",
            "sectionize",
            "--manifest",
            str(ROOT / "examples" / "fixtures" / "manulife_tier1_curated" / "manifest.json"),
            "--out",
            str(sections_path),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(sectionize_result.stdout)["ok"] is True

    extract_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "life_product_extractor.cli",
            "extract",
            "--manifest",
            str(ROOT / "examples" / "fixtures" / "manulife_tier1_curated" / "manifest.json"),
            "--routing",
            str(routing_path),
            "--sections",
            str(sections_path),
            "--out",
            str(candidate_path),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(extract_result.stdout)
    assert payload == {
        "candidate_path": str(candidate_path),
        "fixture_set_id": "manulife_tier1_curated",
        "ok": True,
        "product_count": 3,
        "unsupported_document_count": 4,
    }

    candidate_bundle = load_candidate_bundle_document(candidate_path)
    assert candidate_bundle["summary"]["product_count"] == 3

    validation_path = tmp_path / "validation_report.json"
    validate_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "life_product_extractor.cli",
            "validate",
            "--candidate",
            str(candidate_path),
            "--out",
            str(validation_path),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=True,
    )
    validate_payload = json.loads(validate_result.stdout)
    assert validate_payload["ok"] is True
    assert validate_payload["status"] == "blocked"
    validation_report = load_validation_report_document(validation_path)
    assert validation_report["summary"]["blocked_count"] > 0

    ai_review_path = tmp_path / "ai_review.json"
    ai_review_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "life_product_extractor.cli",
            "ai-review",
            "--candidate",
            str(candidate_path),
            "--validation",
            str(validation_path),
            "--out",
            str(ai_review_path),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=True,
    )
    ai_review_payload = json.loads(ai_review_result.stdout)
    assert ai_review_payload["ok"] is True
    assert ai_review_payload["blocked_count"] > 0
    ai_review = load_ai_review_document(ai_review_path)
    assert ai_review["summary"]["needs_human_review_count"] > 0

    review_html_path = tmp_path / "review.html"
    review_html_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "life_product_extractor.cli",
            "review",
            "build-html",
            "--candidate",
            str(candidate_path),
            "--ai-review",
            str(ai_review_path),
            "--out",
            str(review_html_path),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(review_html_result.stdout)["ok"] is True
    assert "review_decisions.json is authoritative" in review_html_path.read_text(encoding="utf-8")

    decisions_path = tmp_path / "review_decisions.json"
    decisions_path.write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "candidate_fixture_set_id": "manulife_tier1_curated",
                "reviewer": "cli-fixture-reviewer",
                "decisions": [{"path": "/products/0/benefits/1", "decision": "reviewed"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    reviewed_path = tmp_path / "reviewed.json"
    review_apply_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "life_product_extractor.cli",
            "review",
            "apply",
            "--candidate",
            str(candidate_path),
            "--decisions",
            str(decisions_path),
            "--out",
            str(reviewed_path),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(review_apply_result.stdout)["decisions_applied_count"] == 1
    reviewed_payload = json.loads(reviewed_path.read_text(encoding="utf-8"))
    assert reviewed_payload["products"][0]["benefits"][1]["review_status"] == "reviewed"
    assert reviewed_payload["review_metadata"]["run_id"] == "manulife_tier1_curated-validation-v0-1"

    status_from_reviewed_json = tmp_path / "status_from_reviewed.json"
    status_from_reviewed_md = tmp_path / "status_from_reviewed.md"
    status_from_reviewed_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "life_product_extractor.cli",
            "status",
            "--reviewed",
            str(reviewed_path),
            "--out-json",
            str(status_from_reviewed_json),
            "--out-md",
            str(status_from_reviewed_md),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(status_from_reviewed_result.stdout)["ok"] is True
    status_from_reviewed = json.loads(status_from_reviewed_json.read_text(encoding="utf-8"))
    assert status_from_reviewed["run_id"] == "manulife_tier1_curated-validation-v0-1"
    validate_status_report_document(status_from_reviewed)

    recurring_reviewed = json.loads(reviewed_path.read_text(encoding="utf-8"))
    recurring_reviewed["fixture_set_id"] = "manulife_tier1_curated_second_run"
    recurring_reviewed["review_metadata"]["run_id"] = "manulife_tier1_curated_second_run-validation-v0-1"
    recurring_reviewed_path = tmp_path / "reviewed_recurring.json"
    recurring_reviewed_path.write_text(json.dumps(recurring_reviewed, ensure_ascii=False) + "\n", encoding="utf-8")
    skill_candidates_path = tmp_path / "skill_improvement_candidates.json"
    learn_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "life_product_extractor.cli",
            "learn",
            "propose",
            "--reviewed",
            str(reviewed_path),
            str(recurring_reviewed_path),
            "--out",
            str(skill_candidates_path),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(learn_result.stdout)["candidate_count"] == 1
    skill_candidates = json.loads(skill_candidates_path.read_text(encoding="utf-8"))
    validate_skill_improvement_candidates_document(skill_candidates)
    assert skill_candidates["summary"]["auto_applied_count"] == 0
    assert len(skill_candidates["candidates"][0]["evidence_runs"]) == 2


def test_cli_extract_reports_missing_required_pr_e_fixture_without_traceback(tmp_path: Path) -> None:
    manifest = json.loads((ROOT / "examples" / "fixtures" / "manulife_tier1_curated" / "manifest.json").read_text())
    manifest["documents"] = [
        document for document in manifest["documents"] if document["fixture_id"] != "manulife_par_whole_life"
    ]
    fixture_dir = ROOT / "examples" / "fixtures" / "manulife_tier1_curated"

    manifest_path = tmp_path / "manifest.json"
    routing_path = tmp_path / "routing.json"
    sections_path = tmp_path / "sections_structured.jsonl"
    candidate_path = tmp_path / "candidate.json"
    documents_dir = tmp_path / "documents"
    documents_dir.mkdir()

    for document in manifest["documents"]:
        source_path = fixture_dir / document["markdown_path"]
        target_path = documents_dir / Path(document["markdown_path"]).name
        target_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    classify_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "life_product_extractor.cli",
            "classify",
            "--manifest",
            str(manifest_path),
            "--out",
            str(routing_path),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(classify_result.stdout)["ok"] is True

    sectionize_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "life_product_extractor.cli",
            "sectionize",
            "--manifest",
            str(manifest_path),
            "--out",
            str(sections_path),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(sectionize_result.stdout)["ok"] is True

    extract_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "life_product_extractor.cli",
            "extract",
            "--manifest",
            str(manifest_path),
            "--routing",
            str(routing_path),
            "--sections",
            str(sections_path),
            "--out",
            str(candidate_path),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=False,
    )

    assert extract_result.returncode == 2
    assert "Traceback" not in extract_result.stderr
    payload = json.loads(extract_result.stdout)
    assert payload["ok"] is False
    assert "missing required PR E fixture ids" in payload["error"]


def test_routing_schema_accepts_minimal_classification_artifact() -> None:
    routing = {
        "schema_version": "0.1",
        "fixture_set_id": "sample_fixture_set",
        "source_catalog": {
            "source": "bundled://examples/sources/manulife_sources.yaml",
            "source_type": "bundled_resource",
        },
        "routing_strategy": {
            "deterministic": True,
            "manifest_taxonomy_precedence": True,
            "taxonomy_sources_in_order": ["manifest_document", "source_catalog", "content_keywords"],
        },
        "summary": {
            "document_count": 1,
            "scenario_count": 1,
            "primary_class_counts": {"traditional_life": 1},
        },
        "documents": [
            {
                "document_id": "sample_fixture",
                "source_catalog_id": "sample_source",
                "product_name": "Sample product",
                "region_family": "north_america",
                "jurisdiction": "CA",
                "product_class_primary": "traditional_life",
                "product_class_secondary": ["term_life"],
                "routing_confidence": 1.0,
                "classification_mode": "manifest_precedence",
                "skill_pack_hint": "north_america/traditional_life",
                "routing_flags": [],
                "routing_evidence": [
                    {
                        "kind": "taxonomy_field",
                        "source": "manifest_document",
                        "field": "product_class_primary",
                        "value": "traditional_life",
                    }
                ],
            }
        ],
        "paired_source_scenarios": [
            {
                "scenario_id": "sample_scenario",
                "product_name": "Sample product",
                "relation": "known_overlap",
                "fixture_ids": ["sample_fixture", "sample_fixture_peer"],
                "source_catalog_ids": ["sample_source", "sample_source_peer"],
                "product_class_primary": "traditional_life",
                "product_class_secondary": ["term_life"],
                "routing_implication": "reconcile_overlapping_same_product_evidence",
                "rationale": "Overlapping same-product sources should be reconciled.",
            }
        ],
    }

    validate_routing_document(routing)


def test_routing_schema_requires_kind_specific_quote_or_value() -> None:
    base_routing = {
        "schema_version": "0.1",
        "fixture_set_id": "sample_fixture_set",
        "source_catalog": {
            "source": "bundled://examples/sources/manulife_sources.yaml",
            "source_type": "bundled_resource",
        },
        "routing_strategy": {
            "deterministic": True,
            "manifest_taxonomy_precedence": True,
            "taxonomy_sources_in_order": ["manifest_document", "source_catalog", "content_keywords"],
        },
        "summary": {
            "document_count": 1,
            "scenario_count": 1,
            "primary_class_counts": {"traditional_life": 1},
        },
        "documents": [
            {
                "document_id": "sample_fixture",
                "source_catalog_id": "sample_source",
                "product_name": "Sample product",
                "region_family": "north_america",
                "jurisdiction": "CA",
                "product_class_primary": "traditional_life",
                "product_class_secondary": ["term_life"],
                "routing_confidence": 1.0,
                "classification_mode": "manifest_precedence",
                "skill_pack_hint": "north_america/traditional_life",
                "routing_flags": [],
                "routing_evidence": [],
            }
        ],
        "paired_source_scenarios": [
            {
                "scenario_id": "sample_scenario",
                "product_name": "Sample product",
                "relation": "known_overlap",
                "fixture_ids": ["sample_fixture", "sample_fixture_peer"],
                "source_catalog_ids": ["sample_source", "sample_source_peer"],
                "product_class_primary": "traditional_life",
                "product_class_secondary": ["term_life"],
                "routing_implication": "reconcile_overlapping_same_product_evidence",
                "rationale": "Overlapping same-product sources should be reconciled.",
            }
        ],
    }

    missing_quote = json.loads(json.dumps(base_routing))
    missing_quote["documents"][0]["routing_evidence"] = [
        {
            "kind": "content_keyword",
            "source": "markdown_excerpt",
            "field": "headline_quote",
        }
    ]
    with pytest.raises(Exception, match="quote"):
        validate_routing_document(missing_quote)

    missing_value = json.loads(json.dumps(base_routing))
    missing_value["documents"][0]["routing_evidence"] = [
        {
            "kind": "taxonomy_field",
            "source": "manifest_document",
            "field": "product_class_primary",
        }
    ]
    with pytest.raises(Exception, match="value"):
        validate_routing_document(missing_value)

    wrong_field_for_kind = json.loads(json.dumps(base_routing))
    wrong_field_for_kind["documents"][0]["routing_evidence"] = [
        {
            "kind": "document_metadata",
            "source": "manifest_document",
            "field": "document_role",
            "value": "product_marketing_page",
            "quote": "should not be present",
        }
    ]
    with pytest.raises(Exception, match="quote"):
        validate_routing_document(wrong_field_for_kind)


def test_installed_cli_validates_bundled_default_catalog_from_temp_cwd(tmp_path: Path) -> None:
    venv_dir = tmp_path / "venv"
    subprocess.run(
        [sys.executable, "-m", "venv", "--system-site-packages", str(venv_dir)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    bin_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    python_bin = bin_dir / ("python.exe" if os.name == "nt" else "python")
    site_packages = subprocess.run(
        [str(python_bin), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    dependency_paths = [site.getusersitepackages(), sysconfig.get_paths()["purelib"]]
    Path(site_packages, "_workspace_deps.pth").write_text("".join(f"{path}\n" for path in dependency_paths))
    subprocess.run(
        [str(python_bin), "-m", "pip", "install", "--no-build-isolation", "--no-deps", str(ROOT)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    work_dir = tmp_path / "outside-repo"
    work_dir.mkdir()
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    result = subprocess.run(
        [str(python_bin), "-m", "life_product_extractor.cli", "validate-catalog"],
        cwd=work_dir,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["source_count"] >= 20


def test_installed_cli_builds_bundled_default_fixtures_from_temp_cwd(tmp_path: Path) -> None:
    venv_dir = tmp_path / "venv"
    subprocess.run(
        [sys.executable, "-m", "venv", "--system-site-packages", str(venv_dir)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    bin_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    python_bin = bin_dir / ("python.exe" if os.name == "nt" else "python")
    site_packages = subprocess.run(
        [str(python_bin), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    dependency_paths = [site.getusersitepackages(), sysconfig.get_paths()["purelib"]]
    Path(site_packages, "_workspace_deps.pth").write_text("".join(f"{path}\n" for path in dependency_paths))
    subprocess.run(
        [str(python_bin), "-m", "pip", "install", "--no-build-isolation", "--no-deps", str(ROOT)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )

    work_dir = tmp_path / "outside-repo"
    work_dir.mkdir()
    out_dir = work_dir / "fixtures"
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    result = subprocess.run(
        [str(python_bin), "-m", "life_product_extractor.cli", "build-fixtures", "--out-dir", str(out_dir)],
        cwd=work_dir,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["document_count"] == 8
    assert payload["scenario_count"] == 1
    assert (out_dir / "manifest.json").exists()


def test_cli_rejects_catalog_with_unsupported_top_level_key(tmp_path: Path) -> None:
    bad_catalog_path = tmp_path / "bad_catalog.yaml"
    bad_catalog_path.write_text(
        yaml.safe_dump(
            {
                "sources": [
                    {
                        "id": "source_1",
                        "product_name": "Sample product",
                        "region_family": "north_america",
                        "jurisdiction": "CA",
                        "product_class_primary": "traditional_life",
                        "product_class_secondary": ["term_life"],
                        "document_role": "product_marketing_page",
                        "authority_level": "official_public",
                        "allowed_as_fixture": True,
                        "fixture_tier": 1,
                        "source_url": "https://example.com/product",
                    }
                ],
                "unexpected": True,
            },
            sort_keys=False,
        )
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "life_product_extractor.cli",
            "validate-catalog",
            "--catalog",
            str(bad_catalog_path),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "unsupported top-level keys" in payload["error"]


def test_cli_build_fixtures_reports_wrapped_builder_oserror_as_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def raise_wrapped_oserror(**_: object) -> dict[str, object]:
        raise FixtureContractError("could not write fixture bundle to /tmp/out: simulated write failure")

    monkeypatch.setattr(cli, "build_fixture_bundle_from_paths", raise_wrapped_oserror)

    exit_code = cli.main(["build-fixtures", "--out-dir", str(tmp_path / "fixtures")])

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": False,
        "error": "could not write fixture bundle to /tmp/out: simulated write failure",
    }


def test_cli_run_and_status_from_artifacts_pipeline(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"
    manifest = ROOT / "examples" / "fixtures" / "manulife_tier1_curated" / "manifest.json"
    run_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "life_product_extractor.cli",
            "run",
            "--manifest",
            str(manifest),
            "--out",
            str(out_dir),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=True,
    )
    run_payload = json.loads(run_result.stdout)
    assert run_payload["ok"] is True
    expected_files = [
        "routing.json",
        "sections_structured.jsonl",
        "candidate.json",
        "validation_report.json",
        "ai_review.json",
        "review.html",
        "status_report.json",
        "status_report.md",
    ]
    for file_name in expected_files:
        assert (out_dir / file_name).exists()
    status_report = json.loads((out_dir / "status_report.json").read_text(encoding="utf-8"))
    validate_status_report_document(status_report)
    assert status_report["source"] == "run_artifacts"
    assert status_report["summary"]["status"] == "blocked"
    blocker_paths = {blocker["path"] for blocker in status_report["blockers"]}
    ai_review_payload = json.loads((out_dir / "ai_review.json").read_text(encoding="utf-8"))
    escalated_paths = {
        review["path"]
        for review in ai_review_payload["field_reviews"]
        if review["decision"] in {"blocked", "needs_human_review", "unknown"}
    }
    assert escalated_paths <= blocker_paths
    assert "# Status report:" in (out_dir / "status_report.md").read_text(encoding="utf-8")

    candidate_bundle = load_candidate_bundle_document(out_dir / "candidate.json")
    validation_report = load_validation_report_document(out_dir / "validation_report.json")
    ai_review = load_ai_review_document(out_dir / "ai_review.json")
    mismatched_ai_review = dict(ai_review)
    mismatched_ai_review["run_id"] = "run_mismatch"
    with pytest.raises(StatusContractError, match="run_id"):
        build_status_report_from_artifacts(
            candidate_bundle=candidate_bundle,
            validation_report=validation_report,
            ai_review=mismatched_ai_review,
        )

    mismatched_digest_ai_review = json.loads(json.dumps(ai_review))
    mismatched_digest_ai_review["candidate_digest"] = "sha256:" + "0" * 64
    with pytest.raises(StatusContractError, match="candidate_digest"):
        build_status_report_from_artifacts(
            candidate_bundle=candidate_bundle,
            validation_report=validation_report,
            ai_review=mismatched_digest_ai_review,
        )

    validation_error_ai_accepted = json.loads(json.dumps(validation_report))
    validation_error_ai_accepted["issues"].append(
        {
            "path": "/products/0/benefits/0",
            "severity": "error",
            "check": "synthetic_contract_error",
            "message": "Synthetic validation error must block status even if review decision is accepted.",
            "review_decision": "ai_accepted",
            "materiality": "high",
        }
    )
    ai_review_all_clear = json.loads(json.dumps(ai_review))
    ai_review_all_clear["summary"] = {
        **ai_review_all_clear["summary"],
        "ai_accepted_count": len(ai_review_all_clear["field_reviews"]),
        "needs_human_review_count": 0,
        "blocked_count": 0,
        "unknown_count": 0,
    }
    for field_review in ai_review_all_clear["field_reviews"]:
        field_review["decision"] = "ai_accepted"
        field_review.pop("required_human_action", None)
    validation_error_report = build_status_report_from_artifacts(
        candidate_bundle=candidate_bundle,
        validation_report=validation_error_ai_accepted,
        ai_review=ai_review_all_clear,
    )
    assert validation_error_report["summary"]["status"] == "blocked"
    assert validation_error_report["summary"]["blocked_count"] >= 1
    assert "/products/0/benefits/0" in {blocker["path"] for blocker in validation_error_report["blockers"]}

    needs_human_review_report = dict(status_report)
    needs_human_review_report["summary"] = {
        **status_report["summary"],
        "status": "needs_human_review",
        "model_ready": False,
        "unsupported_document_count": 0,
        "needs_human_review_count": 1,
        "blocked_count": 0,
    }
    validate_status_report_document(needs_human_review_report)

    rebuilt_json = tmp_path / "rebuilt_status.json"
    rebuilt_md = tmp_path / "rebuilt_status.md"
    status_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "life_product_extractor.cli",
            "status",
            "--candidate",
            str(out_dir / "candidate.json"),
            "--validation",
            str(out_dir / "validation_report.json"),
            "--ai-review",
            str(out_dir / "ai_review.json"),
            "--out-json",
            str(rebuilt_json),
            "--out-md",
            str(rebuilt_md),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(status_result.stdout)["ok"] is True
    validate_status_report_document(json.loads(rebuilt_json.read_text(encoding="utf-8")))
    assert rebuilt_md.read_text(encoding="utf-8").endswith("\n")


def test_cli_status_reviewed_missing_file_reports_json_error(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "life_product_extractor.cli",
            "status",
            "--reviewed",
            str(tmp_path / "missing-reviewed.json"),
            "--out-json",
            str(tmp_path / "status.json"),
            "--out-md",
            str(tmp_path / "status.md"),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "could not read reviewed product" in payload["error"]
