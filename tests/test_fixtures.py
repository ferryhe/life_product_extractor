from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from life_product_extractor.fixtures import (
    FixtureContractError,
    build_fixture_bundle_from_paths,
    load_fixture_manifest_document,
    validate_fixture_manifest_document,
)
from life_product_extractor.resources import resource_text

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_SPEC_PATH = ROOT / "examples" / "fixtures" / "manulife_fixture_builder.yaml"
CANONICAL_FIXTURE_DIR = ROOT / "examples" / "fixtures" / "manulife_tier1_curated"


def test_packaged_fixture_resources_match_canonical_development_artifacts() -> None:
    assert resource_text("schemas/manifest.schema.json") == (ROOT / "schemas" / "manifest.schema.json").read_text()
    assert resource_text("examples/fixtures/manulife_fixture_builder.yaml") == FIXTURE_SPEC_PATH.read_text()


def test_canonical_fixture_manifest_validates_with_local_files() -> None:
    manifest = load_fixture_manifest_document(CANONICAL_FIXTURE_DIR / "manifest.json")
    validate_fixture_manifest_document(manifest, base_dir=CANONICAL_FIXTURE_DIR)

    assert manifest["fixture_set_id"] == "manulife_tier1_curated"
    assert len(manifest["documents"]) == 8
    assert any(doc["product_class_primary"] == "ul_iul" for doc in manifest["documents"])
    scenario = manifest["paired_source_scenarios"][0]
    assert scenario["relation"] == "potentially_contradictory"
    assert set(scenario["fixture_ids"]) == {
        "manulife_universal_life_page",
        "manulife_universal_life_investment_accounts",
    }


def test_fixture_builder_is_deterministic_and_reproduces_canonical_bundle(tmp_path: Path) -> None:
    out_a = tmp_path / "out_a"
    out_b = tmp_path / "out_b"

    manifest_a = build_fixture_bundle_from_paths(spec_path=FIXTURE_SPEC_PATH, output_dir=out_a)
    manifest_b = build_fixture_bundle_from_paths(spec_path=FIXTURE_SPEC_PATH, output_dir=out_b)
    canonical_manifest = load_fixture_manifest_document(CANONICAL_FIXTURE_DIR / "manifest.json")

    assert manifest_a == manifest_b == canonical_manifest
    assert _snapshot_directory(out_a) == _snapshot_directory(out_b) == _snapshot_directory(CANONICAL_FIXTURE_DIR)


@pytest.mark.parametrize("output_file,error_fragment", [
    ("/tmp/escape.md", "simple relative filename"),
    ("../escape.md", "parent-directory traversal"),
    ("nested/escape.md", "path separators or subdirectories"),
])
def test_fixture_builder_rejects_unsafe_output_file_before_writing(
    tmp_path: Path, output_file: str, error_fragment: str
) -> None:
    spec = yaml.safe_load(FIXTURE_SPEC_PATH.read_text())
    spec["documents"][0]["output_file"] = output_file
    spec_path = tmp_path / "unsafe_fixture_builder.yaml"
    spec_path.write_text(yaml.safe_dump(spec, sort_keys=False))
    out_dir = tmp_path / "out"

    with pytest.raises(FixtureContractError, match=error_fragment):
        build_fixture_bundle_from_paths(spec_path=spec_path, output_dir=out_dir)

    assert list(out_dir.rglob("*")) == []


def test_fixture_builder_rebuild_replaces_stale_document_files_in_same_output_dir(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"

    first_manifest = build_fixture_bundle_from_paths(spec_path=FIXTURE_SPEC_PATH, output_dir=out_dir)
    stale_path = out_dir / "documents" / "stale.md"
    stale_path.write_text("stale fixture\n")

    second_manifest = build_fixture_bundle_from_paths(spec_path=FIXTURE_SPEC_PATH, output_dir=out_dir)
    canonical_manifest = load_fixture_manifest_document(CANONICAL_FIXTURE_DIR / "manifest.json")

    assert first_manifest == second_manifest == canonical_manifest
    assert not stale_path.exists()
    assert _snapshot_directory(out_dir) == _snapshot_directory(CANONICAL_FIXTURE_DIR)


def test_fixture_manifest_preserves_provenance_and_overlap_signal() -> None:
    manifest = load_fixture_manifest_document(CANONICAL_FIXTURE_DIR / "manifest.json")
    by_id = {document["fixture_id"]: document for document in manifest["documents"]}

    family_term = by_id["family_term_life"]
    assert family_term["provenance"]["selected_line_numbers"] == [3, 4, 5, 6, 7]
    assert family_term["provenance"]["omitted_line_ranges"] == [{"start": 1, "end": 2}, {"start": 8, "end": 8}]

    ul_table = by_id["manulife_universal_life_investment_accounts"]
    assert ul_table["document_role"] == "investment_account_table"
    assert ul_table["source_type"] == "api_table_excerpt"
    assert "supporting_table" in ul_table["product_class_secondary"]

    scenario = manifest["paired_source_scenarios"][0]
    assert "may require reconciliation" in scenario["rationale"]


@pytest.mark.parametrize(
    ("mutator", "error_fragment"),
    [
        (
            lambda manifest: manifest["documents"][0]["provenance"].__setitem__("selected_line_numbers", [3, 4, 99]),
            "selected_line_numbers must stay within 1..raw_line_count",
        ),
        (
            lambda manifest: manifest["documents"][0]["provenance"].__setitem__(
                "omitted_line_ranges",
                [{"start": 8, "end": 8}, {"start": 1, "end": 2}],
            ),
            "omitted line ranges must be sorted and non-overlapping",
        ),
        (
            lambda manifest: manifest["documents"][0]["provenance"].__setitem__(
                "omitted_line_ranges",
                [{"start": 1, "end": 1}, {"start": 8, "end": 8}],
            ),
            "omitted line ranges must exactly equal the complement",
        ),
    ],
)
def test_validate_fixture_manifest_enforces_provenance_range_and_complement_semantics(
    mutator, error_fragment: str
) -> None:
    manifest = load_fixture_manifest_document(CANONICAL_FIXTURE_DIR / "manifest.json")
    mutated = json.loads(json.dumps(manifest))
    mutator(mutated)

    with pytest.raises(FixtureContractError, match=error_fragment):
        validate_fixture_manifest_document(mutated, base_dir=CANONICAL_FIXTURE_DIR)


def _snapshot_directory(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            snapshot[path.relative_to(root).as_posix()] = path.read_text()
    return snapshot
