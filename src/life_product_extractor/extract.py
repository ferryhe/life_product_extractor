from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource

from .fixtures import load_fixture_manifest_document, validate_fixture_manifest_document
from .resources import resource_text
from .routing import load_routing_document, validate_routing_document
from .sections import load_sections_jsonl, validate_sections_document


SUPPORTED_FIXTURE_IDS: tuple[str, ...] = (
    "family_term_life",
    "manulife_par_whole_life",
    "manulife_universal_life_page",
    "manulife_universal_life_investment_accounts",
)
SUPPORTED_PRIMARY_CLASSES: tuple[str, ...] = ("traditional_life", "participating_life", "ul_iul")


class CandidateContractError(ValueError):
    """Raised when candidate extraction inputs or outputs violate the PR E contract."""


def load_candidate_bundle_document(path: str | Path) -> dict[str, Any]:
    candidate_path = Path(path)
    try:
        data = json.loads(candidate_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CandidateContractError(f"could not read candidate bundle {candidate_path}: {exc.strerror or exc}") from exc
    except json.JSONDecodeError as exc:
        raise CandidateContractError(f"could not parse candidate bundle JSON {candidate_path}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise CandidateContractError("candidate bundle must be a JSON object")
    bundle = dict(data)
    validate_candidate_bundle_document(bundle)
    return bundle


def validate_candidate_bundle_document(
    bundle: Mapping[str, Any],
    *,
    paired_source_scenarios: Mapping[str, set[str]] | None = None,
) -> None:
    candidate_schema = json.loads(resource_text("schemas/candidate_product.schema.json"))
    bundle_schema = json.loads(resource_text("schemas/candidate_bundle.schema.json"))
    registry = Registry().with_resource(candidate_schema["$id"], Resource.from_contents(candidate_schema))
    try:
        jsonschema.Draft202012Validator(bundle_schema, registry=registry).validate(bundle)
    except jsonschema.ValidationError as exc:
        raise CandidateContractError(f"candidate bundle does not match candidate_bundle.schema.json: {exc.message}") from exc
    _validate_candidate_bundle_semantics(bundle, paired_source_scenarios=paired_source_scenarios)


def extract_candidate_bundle_from_paths(
    manifest_path: str | Path,
    *,
    routing_path: str | Path,
    sections_path: str | Path,
) -> dict[str, Any]:
    fixture_manifest_path = Path(manifest_path)
    manifest = load_fixture_manifest_document(fixture_manifest_path)
    validate_fixture_manifest_document(manifest, base_dir=fixture_manifest_path.parent)
    routing = load_routing_document(routing_path)
    validate_routing_document(routing)
    sections_documents = load_sections_jsonl(sections_path)
    return extract_candidate_bundle(
        manifest,
        base_dir=fixture_manifest_path.parent,
        routing=routing,
        sections_documents=sections_documents,
    )


def extract_candidate_bundle(
    manifest: Mapping[str, Any],
    *,
    base_dir: str | Path,
    routing: Mapping[str, Any],
    sections_documents: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    validate_fixture_manifest_document(manifest, base_dir=base_dir)
    validate_routing_document(routing)
    for sections_document in sections_documents:
        validate_sections_document(sections_document)

    fixture_set_id = str(manifest["fixture_set_id"])
    if str(routing["fixture_set_id"]) != fixture_set_id:
        raise CandidateContractError("routing fixture_set_id does not match manifest fixture_set_id")
    if any(str(document["fixture_set_id"]) != fixture_set_id for document in sections_documents):
        raise CandidateContractError("sections fixture_set_id does not match manifest fixture_set_id")

    manifest_docs = {str(document["fixture_id"]): dict(document) for document in manifest["documents"]}
    routing_docs = {str(document["document_id"]): dict(document) for document in routing["documents"]}
    sections_by_doc = {str(document["document_id"]): dict(document) for document in sections_documents}
    _validate_required_pr_e_fixture_ids(manifest_docs)

    missing_routing = sorted(document_id for document_id in manifest_docs if document_id not in routing_docs)
    if missing_routing:
        raise CandidateContractError(f"routing document is missing fixture ids {missing_routing!r}")
    missing_sections = sorted(document_id for document_id in manifest_docs if document_id not in sections_by_doc)
    if missing_sections:
        raise CandidateContractError(f"sections JSONL is missing fixture ids {missing_sections!r}")

    family_term = _extract_family_term(
        manifest_doc=manifest_docs["family_term_life"],
        route=routing_docs["family_term_life"],
        sections_document=sections_by_doc["family_term_life"],
    )
    par = _extract_manulife_par(
        manifest_doc=manifest_docs["manulife_par_whole_life"],
        route=routing_docs["manulife_par_whole_life"],
        sections_document=sections_by_doc["manulife_par_whole_life"],
    )
    ul = _extract_manulife_ul(
        manifest_docs=[
            manifest_docs["manulife_universal_life_page"],
            manifest_docs["manulife_universal_life_investment_accounts"],
        ],
        routes=[
            routing_docs["manulife_universal_life_page"],
            routing_docs["manulife_universal_life_investment_accounts"],
        ],
        sections_documents=[
            sections_by_doc["manulife_universal_life_page"],
            sections_by_doc["manulife_universal_life_investment_accounts"],
        ],
        scenarios=manifest["paired_source_scenarios"],
    )

    unsupported_documents = []
    for document_id, document in sorted(manifest_docs.items()):
        if document_id in SUPPORTED_FIXTURE_IDS:
            continue
        unsupported_documents.append(
            {
                "document_id": document_id,
                "product_name": document["product_name"],
                "product_class_primary": document["product_class_primary"],
                "reason": "not_in_pr_e_scope",
            }
        )

    bundle = {
        "schema_version": "0.1",
        "fixture_set_id": fixture_set_id,
        "extraction_strategy": {
            "deterministic": True,
            "supported_product_classes": list(SUPPORTED_PRIMARY_CLASSES),
            "supported_fixture_ids": list(SUPPORTED_FIXTURE_IDS),
        },
        "summary": {
            "product_count": 3,
            "supported_document_count": len(SUPPORTED_FIXTURE_IDS),
            "unsupported_document_count": len(unsupported_documents),
        },
        "products": [family_term, par, ul],
        "unsupported_documents": unsupported_documents,
    }
    validate_candidate_bundle_document(
        bundle,
        paired_source_scenarios=_paired_source_scenarios_from_manifest(manifest),
    )
    return bundle


def _extract_family_term(
    *,
    manifest_doc: Mapping[str, Any],
    route: Mapping[str, Any],
    sections_document: Mapping[str, Any],
) -> dict[str, Any]:
    builder = _CandidateBuilder(
        product_id="family_term_life",
        product_identity=_product_identity_from_route(route),
        source_document_ids=[str(manifest_doc["fixture_id"])],
    )
    overview_ref = builder.add_evidence(
        sections_document=sections_document,
        phrase="temporary life insurance coverage",
    )
    renewal_ref = builder.add_evidence(
        sections_document=sections_document,
        phrase="Coverage can be renewed after the initial term.",
    )
    conversion_ref = builder.add_evidence(
        sections_document=sections_document,
        phrase="You may be able to convert to eligible permanent life insurance.",
    )

    builder.add_decrement(
        item_id="family_term_life-dec-death",
        label="Death decrement",
        evidence_refs=[overview_ref],
        confidence=0.72,
        review_status="needs_human_review",
        decrement_type="death",
        inference_basis="life_insurance_product_identity",
    )
    builder.add_decrement(
        item_id="family_term_life-dec-maturity-expiry",
        label="Initial term expiry",
        evidence_refs=[renewal_ref],
        confidence=0.9,
        review_status="ai_accepted",
        decrement_type="maturity_expiry",
    )
    builder.add_benefit(
        item_id="family_term_life-ben-death-benefit",
        label="Life coverage benefit",
        evidence_refs=[overview_ref],
        confidence=0.72,
        review_status="needs_human_review",
        benefit_type="death_benefit",
        trigger_decrement_ids=["family_term_life-dec-death"],
        inference_basis="life_insurance_product_identity",
    )
    builder.add_benefit(
        item_id="family_term_life-ben-renewal-option",
        label="Coverage renewal option",
        evidence_refs=[renewal_ref],
        confidence=0.97,
        review_status="ai_accepted",
        benefit_type="policy_option",
        option_type="renewal_option",
        trigger_decrement_ids=["family_term_life-dec-maturity-expiry"],
    )
    builder.add_benefit(
        item_id="family_term_life-ben-conversion-option",
        label="Permanent conversion option",
        evidence_refs=[conversion_ref],
        confidence=0.96,
        review_status="ai_accepted",
        benefit_type="policy_option",
        option_type="conversion_option",
        trigger_decrement_ids=["family_term_life-dec-maturity-expiry"],
    )
    builder.add_unknown(
        item_id="family_term_life-unknown-surrender-lapse",
        path="/decrements/surrender_lapse",
        label="Surrender or lapse decrement",
        status="not_in_excerpt",
        reason="The Family Term curated excerpt does not describe surrender or lapse mechanics.",
        evidence_refs=[overview_ref],
    )
    return builder.build()


def _extract_manulife_par(
    *,
    manifest_doc: Mapping[str, Any],
    route: Mapping[str, Any],
    sections_document: Mapping[str, Any],
) -> dict[str, Any]:
    builder = _CandidateBuilder(
        product_id="manulife_par_whole_life",
        product_identity=_product_identity_from_route(route),
        source_document_ids=[str(manifest_doc["fixture_id"])],
    )
    title_ref = builder.add_evidence(sections_document=sections_document, phrase="Participating whole life insurance")
    cash_value_ref = builder.add_evidence(sections_document=sections_document, phrase="Guaranteed cash values can build over time.")
    dividend_ref = builder.add_evidence(
        sections_document=sections_document,
        phrase="Dividends are not guaranteed and depend on the performance of the participating account.",
    )

    builder.add_decrement(
        item_id="manulife_par_whole_life-dec-death",
        label="Death decrement",
        evidence_refs=[title_ref],
        confidence=0.72,
        review_status="needs_human_review",
        decrement_type="death",
        inference_basis="life_insurance_product_identity",
    )
    builder.add_benefit(
        item_id="manulife_par_whole_life-ben-death-benefit",
        label="Whole life coverage benefit",
        evidence_refs=[title_ref],
        confidence=0.72,
        review_status="needs_human_review",
        benefit_type="death_benefit",
        trigger_decrement_ids=["manulife_par_whole_life-dec-death"],
        inference_basis="life_insurance_product_identity",
    )
    builder.add_benefit(
        item_id="manulife_par_whole_life-ben-cash-value",
        label="Guaranteed cash value accumulation",
        evidence_refs=[cash_value_ref],
        confidence=0.98,
        review_status="ai_accepted",
        benefit_type="cash_value_accumulation",
        guarantee_status="guaranteed",
    )
    builder.add_benefit(
        item_id="manulife_par_whole_life-ben-dividend-option",
        label="Participating dividend option",
        evidence_refs=[dividend_ref],
        confidence=0.99,
        review_status="ai_accepted",
        benefit_type="dividend_option",
        guarantee_status="non_guaranteed",
    )
    builder.add_unknown(
        item_id="manulife_par_whole_life-unknown-surrender-lapse",
        path="/decrements/surrender_lapse",
        label="Surrender or lapse decrement",
        status="not_in_excerpt",
        reason="The Manulife Par curated excerpt mentions guaranteed cash values but does not describe surrender or lapse mechanics.",
        evidence_refs=[cash_value_ref],
    )
    return builder.build()


def _extract_manulife_ul(
    *,
    manifest_docs: Sequence[Mapping[str, Any]],
    routes: Sequence[Mapping[str, Any]],
    sections_documents: Sequence[Mapping[str, Any]],
    scenarios: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    route_by_id = {str(route["document_id"]): route for route in routes}
    sections_by_id = {str(document["document_id"]): document for document in sections_documents}
    builder = _CandidateBuilder(
        product_id="manulife_universal_life",
        product_identity=_product_identity_from_route(route_by_id["manulife_universal_life_page"]),
        source_document_ids=["manulife_universal_life_page", "manulife_universal_life_investment_accounts"],
    )
    page_document = sections_by_id["manulife_universal_life_page"]
    table_document = sections_by_id["manulife_universal_life_investment_accounts"]

    death_ref = builder.add_evidence(
        sections_document=page_document,
        phrase="Choose death benefit options that align with long-term protection goals.",
    )
    cost_structure_ref = builder.add_evidence(
        sections_document=page_document,
        phrase="Available cost structures may include Level COI and yearly renewable term.",
    )
    account_value_ref = builder.add_evidence(
        sections_document=page_document,
        phrase="Investment account selections can affect account value growth.",
    )
    account_options_ref = builder.add_evidence(
        sections_document=table_document,
        artifact_id="manulife_universal_life_investment_accounts-table-0005-bullet-list",
    )

    builder.add_decrement(
        item_id="manulife_universal_life-dec-death",
        label="Death decrement",
        evidence_refs=[death_ref],
        confidence=0.97,
        review_status="ai_accepted",
        decrement_type="death",
    )
    builder.add_benefit(
        item_id="manulife_universal_life-ben-death-benefit",
        label="Configurable death benefit",
        evidence_refs=[death_ref],
        confidence=0.97,
        review_status="ai_accepted",
        benefit_type="death_benefit",
        trigger_decrement_ids=["manulife_universal_life-dec-death"],
    )
    builder.add_benefit(
        item_id="manulife_universal_life-ben-account-value-crediting",
        label="Account value growth tied to investment account selection",
        evidence_refs=[account_value_ref],
        confidence=0.95,
        review_status="ai_accepted",
        benefit_type="account_value_crediting",
    )
    builder.add_benefit(
        item_id="manulife_universal_life-ben-cost-structure-options",
        label="Available cost structure options",
        evidence_refs=[cost_structure_ref],
        confidence=0.96,
        review_status="ai_accepted",
        benefit_type="policy_charge_structure",
        options=["Level COI", "yearly renewable term"],
    )
    builder.add_benefit(
        item_id="manulife_universal_life-ben-investment-account-options",
        label="Investment account options",
        evidence_refs=[account_options_ref],
        confidence=0.97,
        review_status="ai_accepted",
        benefit_type="investment_account_option",
        options=["Fixed Account", "Daily Interest Account", "Index Account"],
        availability_scope="varies_by_policy_series",
    )
    builder.add_unknown(
        item_id="manulife_universal_life-unknown-crediting-formula",
        path="/benefits/account_value_crediting/calculation_method",
        label="Account value crediting formula",
        status="not_in_excerpt",
        reason="The UL curated excerpts identify account options and account value growth, but they do not include a formula or rate calculation method.",
        evidence_refs=[account_value_ref, account_options_ref],
    )
    builder.add_unknown(
        item_id="manulife_universal_life-unknown-surrender-lapse",
        path="/decrements/surrender_lapse",
        label="Surrender or lapse decrement",
        status="not_in_excerpt",
        reason="The UL curated excerpts do not describe surrender or lapse mechanics.",
        evidence_refs=[account_value_ref],
    )
    scenario_ids = [
        str(scenario["scenario_id"])
        for scenario in scenarios
        if list(scenario["fixture_ids"]) == [
            "manulife_universal_life_page",
            "manulife_universal_life_investment_accounts",
        ]
        or set(scenario["fixture_ids"]) == {
            "manulife_universal_life_page",
            "manulife_universal_life_investment_accounts",
        }
    ]
    candidate = builder.build()
    if scenario_ids:
        candidate["paired_source_scenario_ids"] = scenario_ids
    return candidate


def _product_identity_from_route(route: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "product_name": route["product_name"],
        "region_family": route["region_family"],
        "jurisdiction": route["jurisdiction"],
        "product_class_primary": route["product_class_primary"],
        "product_class_secondary": list(route["product_class_secondary"]),
    }


def _validate_candidate_bundle_semantics(
    bundle: Mapping[str, Any],
    *,
    paired_source_scenarios: Mapping[str, set[str]] | None = None,
) -> None:
    for product in bundle["products"]:
        evidence_ids = {str(item["id"]) for item in product["evidence"]}
        source_document_ids = set(str(document_id) for document_id in product["source_document_ids"])
        decrement_ids = {str(item["id"]) for item in product["decrements"]}
        for key in ("benefits", "decrements"):
            for finding in product[key]:
                missing_refs = sorted(str(ref) for ref in finding["evidence_refs"] if str(ref) not in evidence_ids)
                if missing_refs:
                    raise CandidateContractError(
                        f"{product['product_id']}: {key} entry {finding['id']} references unknown evidence ids {missing_refs!r}"
                    )
        for benefit in product["benefits"]:
            missing_trigger_decrement_ids = sorted(
                str(ref) for ref in benefit.get("trigger_decrement_ids", []) if str(ref) not in decrement_ids
            )
            if missing_trigger_decrement_ids:
                raise CandidateContractError(
                    f"{product['product_id']}: benefit {benefit['id']} references unknown trigger_decrement_ids {missing_trigger_decrement_ids!r}"
                )
        for unknown in product["explicit_unknowns"]:
            missing_refs = sorted(
                str(ref) for ref in unknown.get("evidence_refs", []) if str(ref) not in evidence_ids
            )
            if missing_refs:
                raise CandidateContractError(
                    f"{product['product_id']}: explicit unknown {unknown['id']} references unknown evidence ids {missing_refs!r}"
                )
        for evidence in product["evidence"]:
            if int(evidence["line_start"]) > int(evidence["line_end"]):
                raise CandidateContractError(f"{product['product_id']}: evidence {evidence['id']} has invalid line range")
            if int(evidence["span_start"]) > int(evidence["span_end"]):
                raise CandidateContractError(f"{product['product_id']}: evidence {evidence['id']} has invalid span range")
            if str(evidence["document_id"]) not in source_document_ids:
                raise CandidateContractError(
                    f"{product['product_id']}: evidence {evidence['id']} document_id is not listed in source_document_ids"
                )
        if paired_source_scenarios is not None:
            unknown_scenario_ids = sorted(
                str(scenario_id)
                for scenario_id in product.get("paired_source_scenario_ids", [])
                if str(scenario_id) not in paired_source_scenarios
            )
            if unknown_scenario_ids:
                raise CandidateContractError(
                    f"{product['product_id']}: paired_source_scenario_ids reference unknown manifest scenario ids {unknown_scenario_ids!r}"
                )
            mismatched_scenario_ids = sorted(
                str(scenario_id)
                for scenario_id in product.get("paired_source_scenario_ids", [])
                if set(paired_source_scenarios[str(scenario_id)]) != source_document_ids
            )
            if mismatched_scenario_ids:
                raise CandidateContractError(
                    f"{product['product_id']}: paired_source_scenario_ids reference scenarios that do not match source_document_ids {mismatched_scenario_ids!r}"
                )


def _validate_required_pr_e_fixture_ids(manifest_docs: Mapping[str, Mapping[str, Any]]) -> None:
    missing_fixture_ids = sorted(fixture_id for fixture_id in SUPPORTED_FIXTURE_IDS if fixture_id not in manifest_docs)
    if missing_fixture_ids:
        raise CandidateContractError(f"manifest is missing required PR E fixture ids {missing_fixture_ids!r}")


def _paired_source_scenarios_from_manifest(manifest: Mapping[str, Any]) -> dict[str, set[str]]:
    return {
        str(scenario["scenario_id"]): {str(fixture_id) for fixture_id in scenario["fixture_ids"]}
        for scenario in manifest["paired_source_scenarios"]
    }


class _CandidateBuilder:
    def __init__(
        self,
        *,
        product_id: str,
        product_identity: Mapping[str, Any],
        source_document_ids: Sequence[str],
    ) -> None:
        self.product_id = product_id
        self.product_identity = dict(product_identity)
        self.source_document_ids = list(source_document_ids)
        self.decrements: list[dict[str, Any]] = []
        self.benefits: list[dict[str, Any]] = []
        self.explicit_unknowns: list[dict[str, Any]] = []
        self.evidence: list[dict[str, Any]] = []

    def add_evidence(
        self,
        *,
        sections_document: Mapping[str, Any],
        phrase: str | None = None,
        artifact_id: str | None = None,
    ) -> str:
        evidence_id = f"{self.product_id}-evidence-{len(self.evidence) + 1:04d}"
        record = _locate_evidence(sections_document=sections_document, phrase=phrase, artifact_id=artifact_id)
        record["id"] = evidence_id
        self.evidence.append(record)
        return evidence_id

    def add_decrement(
        self,
        *,
        item_id: str,
        label: str,
        evidence_refs: Sequence[str],
        confidence: float,
        review_status: str,
        **extra: Any,
    ) -> None:
        payload = {
            "id": item_id,
            "label": label,
            "evidence_refs": list(evidence_refs),
            "confidence": confidence,
            "review_status": review_status,
        }
        payload.update(extra)
        self.decrements.append(payload)

    def add_benefit(
        self,
        *,
        item_id: str,
        label: str,
        evidence_refs: Sequence[str],
        confidence: float,
        review_status: str,
        **extra: Any,
    ) -> None:
        payload = {
            "id": item_id,
            "label": label,
            "evidence_refs": list(evidence_refs),
            "confidence": confidence,
            "review_status": review_status,
        }
        payload.update(extra)
        self.benefits.append(payload)

    def add_unknown(
        self,
        *,
        item_id: str,
        path: str,
        label: str,
        status: str,
        reason: str,
        evidence_refs: Sequence[str] = (),
        confidence: float = 1.0,
        review_status: str = "blocked",
        **extra: Any,
    ) -> None:
        payload = {
            "id": item_id,
            "path": path,
            "label": label,
            "status": status,
            "reason": reason,
            "evidence_refs": list(evidence_refs),
            "confidence": confidence,
            "review_status": review_status,
        }
        payload.update(extra)
        self.explicit_unknowns.append(payload)

    def build(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1",
            "product_id": self.product_id,
            "product_identity": self.product_identity,
            "source_document_ids": self.source_document_ids,
            "decrements": self.decrements,
            "benefits": self.benefits,
            "explicit_unknowns": self.explicit_unknowns,
            "evidence": self.evidence,
        }


def _locate_evidence(
    *,
    sections_document: Mapping[str, Any],
    phrase: str | None,
    artifact_id: str | None,
) -> dict[str, Any]:
    document_id = str(sections_document["document_id"])
    source_id = str(sections_document["source_catalog_id"])

    if artifact_id is not None:
        for artifact in sections_document["table_artifacts"]:
            if str(artifact["table_id"]) != artifact_id:
                continue
            source_quote = str(artifact["source_quote"])
            span_start, span_end = _span_for_phrase(source_quote, phrase)
            return {
                "source_id": source_id,
                "document_id": document_id,
                "section_id": str(artifact["section_id"]),
                "line_start": int(artifact["line_start"]),
                "line_end": int(artifact["line_end"]),
                "span_start": span_start,
                "span_end": span_end,
                "source_quote": source_quote,
                "artifact_id": str(artifact["table_id"]),
                "artifact_type": str(artifact["artifact_type"]),
            }
        raise CandidateContractError(f"{document_id}: table artifact {artifact_id!r} not found for candidate extraction")

    for section in sections_document["sections"]:
        source_quote = str(section["source_quote"])
        if phrase is None or phrase.casefold() in source_quote.casefold():
            span_start, span_end = _span_for_phrase(source_quote, phrase)
            return {
                "source_id": source_id,
                "document_id": document_id,
                "section_id": str(section["section_id"]),
                "line_start": int(section["line_start"]),
                "line_end": int(section["line_end"]),
                "span_start": span_start,
                "span_end": span_end,
                "source_quote": source_quote,
            }
    raise CandidateContractError(f"{document_id}: phrase {phrase!r} not found in sectionized document")


def _span_for_phrase(source_quote: str, phrase: str | None) -> tuple[int, int]:
    if phrase is None:
        return (0, len(source_quote))
    start = source_quote.casefold().find(phrase.casefold())
    if start < 0:
        raise CandidateContractError(f"phrase {phrase!r} not found inside source quote")
    return (start, start + len(phrase))
