from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import jsonschema

from .resources import resource_text
from .review import validate_reviewed_product_document


class LearningContractError(ValueError):
    """Raised when skill-improvement proposal inputs or outputs violate contracts."""


def build_skill_improvement_candidates_from_reviewed(reviewed: Mapping[str, Any]) -> dict[str, Any]:
    """Build a proposed-only skill improvement artifact from one reviewed product.

    A single reviewed run is enough to produce a valid artifact, but not enough
    evidence to propose a skill change. Recurring corrections are emitted by
    build_skill_improvement_candidates_from_reviewed_runs.
    """

    return build_skill_improvement_candidates_from_reviewed_runs([reviewed])


def build_skill_improvement_candidates_from_reviewed_runs(
    reviewed_runs: list[Mapping[str, Any]], *, min_evidence_runs: int = 2
) -> dict[str, Any]:
    """Build proposed-only skill improvement candidates from reviewed product outputs.

    The learning loop is intentionally conservative: it converts human review
    decisions into auditable proposal artifacts only after recurring corrections
    are observed, and never mutates active skill-pack files.
    """

    if not reviewed_runs:
        raise LearningContractError("at least one reviewed product is required")
    if min_evidence_runs < 1:
        raise LearningContractError("min_evidence_runs must be at least 1")

    normalized_runs = [_validated_reviewed_product(reviewed) for reviewed in reviewed_runs]
    run_ids = sorted(str(reviewed["review_metadata"]["run_id"]) for reviewed in normalized_runs)
    fixture_set_ids = sorted(str(reviewed["fixture_set_id"]) for reviewed in normalized_runs)
    run_id = _aggregate_id("learn-propose", run_ids)
    fixture_set_id = _aggregate_id("fixture-set", fixture_set_ids)

    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for reviewed in normalized_runs:
        review_metadata = reviewed["review_metadata"]
        products = reviewed["products"]
        for decision in review_metadata["decisions_applied"]:
            path = str(decision["path"])
            decision_value = str(decision["decision"])
            product_index = _product_index_from_decision_path(path)
            if product_index is None or product_index >= len(products) or not isinstance(products[product_index], Mapping):
                raise LearningContractError(f"review_metadata decision path does not target a reviewed product finding: {path}")
            product = products[product_index]
            target_skillpack = _target_skillpack(product)
            finding = _finding_at_decision_path(product, path)
            finding_key = _finding_key(path, finding)
            scope = f"{path.split('/')[3]}/{finding_key}" if len(path.split("/")) >= 4 else finding_key
            change_type = _change_type_for_path(path, decision_value)
            evidence_run = {
                "run_id": str(review_metadata["run_id"]),
                "fixture_set_id": str(reviewed["fixture_set_id"]),
                "product_id": str(product.get("product_id") or f"product_{product_index}"),
                "decision_path": path,
                "decision": decision_value,
                **_finding_provenance(product, finding),
                **({"reviewer_note": str(decision["reviewer_note"])} if "reviewer_note" in decision else {}),
                **({"source_quote": _source_quote(product, finding)} if finding is not None else {}),
            }
            grouped.setdefault((target_skillpack, scope, decision_value, change_type), []).append(evidence_run)

    candidates: list[dict[str, Any]] = []
    for (target_skillpack, scope, decision_value, change_type), evidence_runs in sorted(grouped.items()):
        evidence_runs = sorted(evidence_runs, key=lambda evidence: (str(evidence["run_id"]), str(evidence["product_id"])))
        distinct_run_ids = {str(evidence["run_id"]) for evidence in evidence_runs}
        if len(distinct_run_ids) < min_evidence_runs:
            continue
        first_evidence = evidence_runs[0]
        candidates.append(
            {
                "id": f"skill_candidate_{len(candidates) + 1:03d}",
                "target_skillpack": target_skillpack,
                "evidence_runs": evidence_runs,
                "proposed_change": {
                    "change_type": change_type,
                    "scope": scope,
                    "rationale": _proposal_rationale(decision_value, scope, first_evidence),
                    "status": "proposed_only",
                },
                "required_fixture": {
                    "fixture_set_id": f"{fixture_set_id}-skill-candidate-{len(candidates) + 1:03d}",
                    "description": (
                        f"Add a regression fixture proving {target_skillpack} handles recurring {scope} "
                        "corrections before activating this proposed skill change."
                    ),
                    "must_fail_before_activation": True,
                },
            }
        )

    target_skillpacks = {candidate["target_skillpack"] for candidate in candidates}
    proposal = {
        "schema_version": "0.1",
        "run_id": run_id,
        "fixture_set_id": fixture_set_id,
        "source": "reviewed_product",
        "summary": {
            "candidate_count": len(candidates),
            "target_skillpack_count": len(target_skillpacks),
            "requires_fixture_count": len(candidates),
            "auto_applied_count": 0,
        },
        "candidates": candidates,
    }
    validate_skill_improvement_candidates_document(proposal)
    return proposal


def build_skill_improvement_candidates_from_reviewed_path(reviewed_path: Path | list[Path]) -> dict[str, Any]:
    paths = [Path(path) for path in reviewed_path] if isinstance(reviewed_path, list) else [Path(reviewed_path)]
    reviewed_runs = [_load_reviewed_product_document(path) for path in paths]
    return build_skill_improvement_candidates_from_reviewed_runs(reviewed_runs)


def validate_skill_improvement_candidates_document(document: Mapping[str, Any]) -> None:
    schema = json.loads(resource_text("schemas/skill_improvement_candidates.schema.json"))
    try:
        jsonschema.Draft202012Validator(schema).validate(document)
    except jsonschema.ValidationError as exc:
        raise LearningContractError(
            f"skill improvement candidates do not match skill_improvement_candidates.schema.json: {exc.message}"
        ) from exc


def _load_reviewed_product_document(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LearningContractError(f"could not read reviewed product {path}: {exc.strerror or exc}") from exc
    except json.JSONDecodeError as exc:
        raise LearningContractError(f"could not parse reviewed product JSON {path}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise LearningContractError("reviewed product must be a JSON object")
    return _validated_reviewed_product(data)


def _validated_reviewed_product(reviewed: Mapping[str, Any]) -> dict[str, Any]:
    reviewed_document = dict(reviewed)
    try:
        validate_reviewed_product_document(reviewed_document)
    except ValueError as exc:
        raise LearningContractError(f"reviewed product does not match reviewed_product.schema.json: {exc}") from exc
    return reviewed_document


def _product_index_from_decision_path(path: str) -> int | None:
    parts = path.split("/")
    if len(parts) < 3 or parts[1] != "products":
        return None
    try:
        return int(parts[2])
    except ValueError:
        return None


def _target_skillpack(product: Mapping[str, Any]) -> str:
    identity = product.get("product_identity")
    if not isinstance(identity, Mapping):
        return "unknown_region/other"
    region = str(identity.get("region_family") or "unknown_region")
    product_class = str(identity.get("product_class_primary") or "other")
    return f"{region}/{product_class}"


def _aggregate_id(prefix: str, values: list[str]) -> str:
    payload = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _finding_key(path: str, finding: Mapping[str, Any] | None) -> str:
    if finding is None:
        return path.strip("/").replace("/", "_") or "unknown"
    for key in ("benefit_type", "decrement_type", "path", "id", "label"):
        value = str(finding.get(key) or "").strip()
        if value:
            return _slug(value)
    return path.strip("/").replace("/", "_") or "unknown"


def _slug(value: str) -> str:
    chars = [char.lower() if char.isalnum() else "_" for char in value]
    slug = "_".join(part for part in "".join(chars).split("_") if part)
    return slug or "unknown"


def _finding_at_decision_path(product: Mapping[str, Any], path: str) -> Mapping[str, Any] | None:
    parts = path.split("/")
    if len(parts) != 5:
        return None
    collection_name = parts[3]
    try:
        item_index = int(parts[4])
    except ValueError:
        return None
    collection = product.get(collection_name)
    if not isinstance(collection, list) or item_index >= len(collection):
        return None
    item = collection[item_index]
    return item if isinstance(item, Mapping) else None


def _source_quote(product: Mapping[str, Any], finding: Mapping[str, Any]) -> str:
    evidence_refs = finding.get("evidence_refs", [])
    evidence_ref = evidence_refs[0] if isinstance(evidence_refs, list) and evidence_refs else None
    evidence = product.get("evidence", [])
    if evidence_ref is not None and isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, Mapping) and item.get("id") == evidence_ref:
                return str(item.get("source_quote") or "")
    return ""


def _finding_provenance(product: Mapping[str, Any], finding: Mapping[str, Any] | None) -> dict[str, Any]:
    if finding is None:
        return {
            "finding_id": "unknown",
            "finding_label": "unknown",
            "confidence": 0,
            "review_status": "blocked",
            "evidence_refs": [],
            "evidence_spans": [],
        }
    evidence_refs = [str(ref) for ref in finding.get("evidence_refs", []) if str(ref)]
    evidence_spans = _evidence_spans(product, evidence_refs)
    return {
        "finding_id": str(finding.get("id") or "unknown"),
        "finding_label": str(finding.get("label") or finding.get("path") or "unknown"),
        "confidence": float(finding.get("confidence", 0)),
        "review_status": str(finding.get("review_status") or "blocked"),
        "evidence_refs": evidence_refs,
        "evidence_spans": evidence_spans,
    }


def _evidence_spans(product: Mapping[str, Any], evidence_refs: list[str]) -> list[dict[str, Any]]:
    evidence = product.get("evidence", [])
    if not isinstance(evidence, list):
        return []
    evidence_by_id = {str(item.get("id")): item for item in evidence if isinstance(item, Mapping)}
    spans: list[dict[str, Any]] = []
    for evidence_ref in evidence_refs:
        item = evidence_by_id.get(evidence_ref)
        if item is None:
            continue
        spans.append(
            {
                "id": str(item["id"]),
                "source_id": str(item["source_id"]),
                "document_id": str(item["document_id"]),
                "section_id": str(item["section_id"]),
                "line_start": int(item["line_start"]),
                "line_end": int(item["line_end"]),
                "span_start": int(item["span_start"]),
                "span_end": int(item["span_end"]),
                "source_quote": str(item["source_quote"]),
            }
        )
    return spans


def _change_type_for_path(path: str, decision: str) -> str:
    if "/explicit_unknowns/" in path:
        return "fixture_gap"
    if decision in {"needs_human_review", "blocked"}:
        return "human_review_policy"
    return "extraction_rule"


def _proposal_rationale(decision: str, scope: str, decision_payload: Mapping[str, Any]) -> str:
    note = str(decision_payload.get("reviewer_note") or "").strip()
    if note:
        return f"Recurring human corrections marked {scope} as {decision}: {note}"
    return f"Recurring human corrections marked {scope} as {decision}; review before changing active skill-pack behavior."
