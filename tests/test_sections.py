from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from life_product_extractor.fixtures import load_fixture_manifest_document
from life_product_extractor.sections import (
    SectionContractError,
    load_sections_jsonl,
    sectionize_fixture_manifest,
    sectionize_fixture_manifest_from_path,
    validate_sections_document,
)

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_FIXTURE_DIR = ROOT / "examples" / "fixtures" / "manulife_tier1_curated"


def test_sectionize_canonical_manulife_manifest_is_deterministic() -> None:
    manifest_path = CANONICAL_FIXTURE_DIR / "manifest.json"

    first = sectionize_fixture_manifest_from_path(manifest_path)
    second = sectionize_fixture_manifest_from_path(manifest_path)

    assert first == second
    assert len(first) == 8

    by_document_id = {document["document_id"]: document for document in first}
    family_term = by_document_id["family_term_life"]
    assert family_term["sections"][0]["heading_path"] == ["Family Term Life Insurance Plan"]
    assert family_term["sections"][0]["line_start"] == 1
    assert family_term["sections"][0]["line_end"] == 6
    assert family_term["source_provenance"]["omitted_line_ranges"] == [{"start": 1, "end": 2}, {"start": 8, "end": 8}]

    ul_table = by_document_id["manulife_universal_life_investment_accounts"]
    assert ul_table["table_artifacts"] == [
        {
            "table_id": "manulife_universal_life_investment_accounts-table-0005-bullet-list",
            "section_id": "manulife_universal_life_investment_accounts-sec-0001-manulife-ul-investment-accounts",
            "artifact_type": "bullet_list_table",
            "line_start": 5,
            "line_end": 7,
            "source_quote": "- Fixed Account\n- Daily Interest Account\n- Index Account",
            "rows": [["Fixed Account"], ["Daily Interest Account"], ["Index Account"]],
        }
    ]


def test_sectionize_supports_heading_hierarchy_repeated_headings_and_low_value_labels(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "fixtures"
    documents_dir = fixture_dir / "documents"
    documents_dir.mkdir(parents=True)
    manifest = {
        "schema_version": "0.1",
        "fixture_set_id": "sample_fixture_set",
        "source_catalog": {
            "source": "bundled://examples/sources/manulife_sources.yaml",
            "source_type": "bundled_resource",
        },
        "generated_by": {
            "tool": "life_product_extractor.fixture_builder",
            "version": "0.1.0",
        },
        "documents": [
            {
                "fixture_id": "sample_nested_sections",
                "source_catalog_id": "manulife_family_term_life",
                "product_name": "Sample nested sections",
                "region_family": "north_america",
                "jurisdiction": "CA",
                "product_class_primary": "traditional_life",
                "product_class_secondary": ["term_life"],
                "document_role": "product_marketing_page",
                "authority_level": "official_public",
                "source_url": "https://example.com/sample-nested-sections",
                "retrieval_date": "2026-05-10",
                "source_type": "html_page_excerpt",
                "markdown_path": "documents/sample_nested_sections.md",
                "sha256": "",
                "byte_count": 0,
                "provenance": {
                    "source_kind": "committed_curated_snippet",
                    "normalization": "curated_markdown_excerpt_v1",
                    "raw_text_sha256": "0" * 64,
                    "raw_line_count": 12,
                    "selected_line_numbers": list(range(1, 13)),
                    "omitted_line_ranges": [],
                    "selected_block_count": 6,
                },
            },
            {
                "fixture_id": "sample_nested_sections_peer",
                "source_catalog_id": "manulife_universal_life",
                "product_name": "Sample nested sections",
                "region_family": "north_america",
                "jurisdiction": "CA",
                "product_class_primary": "traditional_life",
                "product_class_secondary": ["term_life"],
                "document_role": "product_marketing_page",
                "authority_level": "official_public",
                "source_url": "https://example.com/sample-nested-sections-peer",
                "retrieval_date": "2026-05-10",
                "source_type": "html_page_excerpt",
                "markdown_path": "documents/sample_nested_sections_peer.md",
                "sha256": "",
                "byte_count": 0,
                "provenance": {
                    "source_kind": "committed_curated_snippet",
                    "normalization": "curated_markdown_excerpt_v1",
                    "raw_text_sha256": "1" * 64,
                    "raw_line_count": 12,
                    "selected_line_numbers": list(range(1, 13)),
                    "omitted_line_ranges": [],
                    "selected_block_count": 6,
                },
            },
        ],
        "paired_source_scenarios": [
            {
                "scenario_id": "sample_nested_sections_overlap",
                "product_name": "Sample nested sections",
                "relation": "known_overlap",
                "fixture_ids": ["sample_nested_sections", "sample_nested_sections_peer"],
                "source_catalog_ids": ["manulife_family_term_life", "manulife_universal_life"],
                "rationale": "Synthetic overlap for sectionization tests.",
            }
        ],
    }
    markdown = (
        "# Product overview\n"
        "\n"
        "Landing overview & <unsafe> note.\n"
        "\n"
        "## Benefits\n"
        "\n"
        "Core benefit summary.\n"
        "\n"
        "## Benefits\n"
        "\n"
        "Speak with an advisor\n"
        "\n"
        "| Option | Value |\n"
        "| --- | --- |\n"
        "| Base | Included |\n"
    )
    markdown_path = documents_dir / "sample_nested_sections.md"
    markdown_path.write_text(markdown, encoding="utf-8")
    peer_markdown_path = documents_dir / "sample_nested_sections_peer.md"
    peer_markdown_path.write_text(markdown, encoding="utf-8")
    markdown_bytes = markdown.encode("utf-8")
    manifest["documents"][0]["sha256"] = hashlib.sha256(markdown_bytes).hexdigest()
    manifest["documents"][0]["byte_count"] = len(markdown_bytes)
    manifest["documents"][1]["sha256"] = hashlib.sha256(markdown_bytes).hexdigest()
    manifest["documents"][1]["byte_count"] = len(markdown_bytes)
    (fixture_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    sectionized = sectionize_fixture_manifest_from_path(fixture_dir / "manifest.json")
    document = next(item for item in sectionized if item["document_id"] == "sample_nested_sections")
    sections = document["sections"]

    assert [section["heading_path"] for section in sections] == [
        ["Product overview"],
        ["Product overview", "Benefits"],
        ["Product overview", "Benefits"],
    ]
    assert sections[0]["source_quote"] == "# Product overview\n\nLanding overview &amp; &lt;unsafe&gt; note."
    assert sections[1]["labels"] == ["primary_content"]
    assert sections[2]["labels"] == ["contains_low_value_lines", "primary_content"]
    assert sections[2]["source_quote"] == (
        "## Benefits\n\nSpeak with an advisor\n\n| Option | Value |\n| --- | --- |\n| Base | Included |"
    )
    assert document["table_artifacts"] == [
        {
            "table_id": "sample_nested_sections-table-0013-table",
            "section_id": "sample_nested_sections-sec-0009-product-overview-benefits",
            "artifact_type": "markdown_table",
            "line_start": 13,
            "line_end": 15,
            "source_quote": "| Option | Value |\n| --- | --- |\n| Base | Included |",
            "rows": [["Option", "Value"], ["Base", "Included"]],
        }
    ]


def test_validate_sections_document_rejects_duplicate_section_ids() -> None:
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
                "section_id": "dup",
                "heading": {"text": "One", "level": 1},
                "heading_path": ["One"],
                "line_start": 1,
                "line_end": 2,
                "body_line_start": 2,
                "body_line_end": 2,
                "content_types": ["paragraph"],
                "labels": ["primary_content"],
                "table_artifact_ids": [],
                "source_quote": "# One\nBody",
            },
            {
                "section_id": "dup",
                "heading": {"text": "Two", "level": 1},
                "heading_path": ["Two"],
                "line_start": 3,
                "line_end": 4,
                "body_line_start": 4,
                "body_line_end": 4,
                "content_types": ["paragraph"],
                "labels": ["primary_content"],
                "table_artifact_ids": [],
                "source_quote": "# Two\nBody",
            },
        ],
        "table_artifacts": [],
    }

    with pytest.raises(SectionContractError, match="duplicate section_id"):
        validate_sections_document(document)


def test_validate_sections_document_rejects_unknown_declared_table_artifact_id() -> None:
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
                "section_id": "sample_fixture-sec-0001-one",
                "heading": {"text": "One", "level": 1},
                "heading_path": ["One"],
                "line_start": 1,
                "line_end": 4,
                "body_line_start": 2,
                "body_line_end": 4,
                "content_types": ["paragraph"],
                "labels": ["primary_content"],
                "table_artifact_ids": ["missing-table"],
                "source_quote": "# One\nBody",
            }
        ],
        "table_artifacts": [],
    }

    with pytest.raises(SectionContractError, match="references unknown table_artifact_ids"):
        validate_sections_document(document)


def test_validate_sections_document_rejects_missing_reverse_table_reference() -> None:
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
            "raw_line_count": 5,
            "selected_line_numbers": [1, 2, 3, 4, 5],
            "omitted_line_ranges": [],
        },
        "sections": [
            {
                "section_id": "sample_fixture-sec-0001-one",
                "heading": {"text": "One", "level": 1},
                "heading_path": ["One"],
                "line_start": 1,
                "line_end": 5,
                "body_line_start": 2,
                "body_line_end": 5,
                "content_types": ["paragraph", "table"],
                "labels": ["primary_content"],
                "table_artifact_ids": [],
                "source_quote": "# One\nBody\n| A | B |\n| - | - |",
            }
        ],
        "table_artifacts": [
            {
                "table_id": "sample_fixture-table-0003-table",
                "section_id": "sample_fixture-sec-0001-one",
                "artifact_type": "markdown_table",
                "line_start": 3,
                "line_end": 4,
                "source_quote": "| A | B |\n| - | - |",
                "rows": [["A", "B"]],
            }
        ],
    }

    with pytest.raises(SectionContractError, match="missing referenced table_artifact_ids"):
        validate_sections_document(document)


def test_validate_sections_document_rejects_cross_section_table_reference() -> None:
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
            "raw_line_count": 8,
            "selected_line_numbers": [1, 2, 3, 4, 5, 6, 7, 8],
            "omitted_line_ranges": [],
        },
        "sections": [
            {
                "section_id": "sample_fixture-sec-0001-one",
                "heading": {"text": "One", "level": 1},
                "heading_path": ["One"],
                "line_start": 1,
                "line_end": 4,
                "body_line_start": 2,
                "body_line_end": 4,
                "content_types": ["paragraph"],
                "labels": ["primary_content"],
                "table_artifact_ids": ["sample_fixture-table-0006-table"],
                "source_quote": "# One\nBody",
            },
            {
                "section_id": "sample_fixture-sec-0005-two",
                "heading": {"text": "Two", "level": 1},
                "heading_path": ["Two"],
                "line_start": 5,
                "line_end": 8,
                "body_line_start": 6,
                "body_line_end": 8,
                "content_types": ["table"],
                "labels": ["primary_content"],
                "table_artifact_ids": ["sample_fixture-table-0006-table"],
                "source_quote": "# Two\n| A | B |\n| - | - |",
            },
        ],
        "table_artifacts": [
            {
                "table_id": "sample_fixture-table-0006-table",
                "section_id": "sample_fixture-sec-0005-two",
                "artifact_type": "markdown_table",
                "line_start": 6,
                "line_end": 7,
                "source_quote": "| A | B |\n| - | - |",
                "rows": [["A", "B"]],
            }
        ],
    }

    with pytest.raises(SectionContractError, match="owned by another section"):
        validate_sections_document(document)


def test_validate_sections_document_rejects_table_artifact_range_outside_section() -> None:
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
            "raw_line_count": 6,
            "selected_line_numbers": [1, 2, 3, 4, 5, 6],
            "omitted_line_ranges": [],
        },
        "sections": [
            {
                "section_id": "sample_fixture-sec-0001-one",
                "heading": {"text": "One", "level": 1},
                "heading_path": ["One"],
                "line_start": 1,
                "line_end": 4,
                "body_line_start": 2,
                "body_line_end": 4,
                "content_types": ["paragraph", "table"],
                "labels": ["primary_content"],
                "table_artifact_ids": ["sample_fixture-table-0005-table"],
                "source_quote": "# One\nBody",
            }
        ],
        "table_artifacts": [
            {
                "table_id": "sample_fixture-table-0005-table",
                "section_id": "sample_fixture-sec-0001-one",
                "artifact_type": "markdown_table",
                "line_start": 5,
                "line_end": 6,
                "source_quote": "| A | B |\n| - | - |",
                "rows": [["A", "B"]],
            }
        ],
    }

    with pytest.raises(SectionContractError, match="must stay within referenced section line range"):
        validate_sections_document(document)


def test_validate_sections_document_rejects_raw_angle_brackets_in_source_quote() -> None:
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
            "raw_line_count": 2,
            "selected_line_numbers": [1, 2],
            "omitted_line_ranges": [],
        },
        "sections": [
            {
                "section_id": "sample_fixture-sec-0001-one",
                "heading": {"text": "One", "level": 1},
                "heading_path": ["One"],
                "line_start": 1,
                "line_end": 2,
                "body_line_start": 2,
                "body_line_end": 2,
                "content_types": ["paragraph"],
                "labels": ["primary_content"],
                "table_artifact_ids": [],
                "source_quote": "# One\n<unsafe>",
            }
        ],
        "table_artifacts": [],
    }

    with pytest.raises(SectionContractError, match="sections_structured.schema.json"):
        validate_sections_document(document)


def test_load_sections_jsonl_validates_each_line(tmp_path: Path) -> None:
    manifest = load_fixture_manifest_document(CANONICAL_FIXTURE_DIR / "manifest.json")
    sectionized = sectionize_fixture_manifest(manifest, base_dir=CANONICAL_FIXTURE_DIR)
    out_path = tmp_path / "sections.jsonl"
    out_path.write_text("\n".join(json.dumps(document) for document in sectionized) + "\n", encoding="utf-8")

    loaded = load_sections_jsonl(out_path)

    assert loaded == sectionized
