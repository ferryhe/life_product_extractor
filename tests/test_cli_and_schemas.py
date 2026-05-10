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
from life_product_extractor.fixtures import FixtureContractError
from life_product_extractor.resources import resource_text
from life_product_extractor.routing import validate_routing_document

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
        "candidate_product.schema.json",
        "ai_review.schema.json",
        "review_decisions.schema.json",
        "reviewed_product.schema.json",
        "status_report.schema.json",
    ]
    for file_name in documented_schema_paths:
        assert (SCHEMAS / file_name).exists()


def test_packaged_resources_match_canonical_development_artifacts() -> None:
    assert resource_text("schemas/source_catalog.schema.json") == (SCHEMAS / "source_catalog.schema.json").read_text()
    assert resource_text("schemas/manifest.schema.json") == (SCHEMAS / "manifest.schema.json").read_text()
    assert resource_text("schemas/routing.schema.json") == (SCHEMAS / "routing.schema.json").read_text()
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
        "product_identity": {
            "product_name": "Sample product",
            "region_family": "north_america",
            "jurisdiction": "CA",
            "product_class_primary": "traditional_life",
        },
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
                "quote": "The policy provides a death benefit.",
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
            "quote": "The policy provides a death benefit.",
        }
    ]
    assert any(list(error.path) == ["evidence", 0] for error in validator.iter_errors(missing_coordinates))


def test_ai_review_schema_rejects_empty_field_reviews_and_accepts_minimal_review() -> None:
    validator = _schema_validator("ai_review.schema.json")

    empty_reviews = {
        "run_id": "run_001",
        "reviewer": {"type": "ai", "skillpack": "north_america/traditional_life", "version": "0.1.0"},
        "summary": {"ai_accepted_count": 0, "needs_human_review_count": 0, "blocked_count": 0},
        "field_reviews": [],
    }
    assert any(list(error.path) == ["field_reviews"] for error in validator.iter_errors(empty_reviews))

    minimal_review = {
        "run_id": "run_001",
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


def test_reviewed_product_composes_candidate_contract_and_requires_review_metadata() -> None:
    schema = json.loads((SCHEMAS / "reviewed_product.schema.json").read_text())
    assert schema["allOf"][0]["$ref"] == "candidate_product.schema.json"
    validator = _schema_validator("reviewed_product.schema.json")
    candidate_like = _minimal_candidate()

    assert any(list(error.path) == [] and "review_metadata" in error.message for error in validator.iter_errors(candidate_like))

    reviewed = candidate_like | {
        "review_metadata": {
            "review_status": "reviewed",
            "reviewed_at": "2026-05-09",
            "decisions_applied": [],
        }
    }
    validator.validate(reviewed)

    reviewed["review_metadata"]["decisions_applied"] = [{"path": "/benefits/0", "decision": "invented"}]
    assert any(
        list(error.path) == ["review_metadata", "decisions_applied", 0, "decision"]
        for error in validator.iter_errors(reviewed)
    )


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
