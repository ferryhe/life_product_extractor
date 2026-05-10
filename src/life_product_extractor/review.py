from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import html
import json
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource

from .extract import CandidateContractError, load_candidate_bundle_document, validate_candidate_bundle_document
from .resources import resource_text

REVIEW_DECISIONS: tuple[str, ...] = (
    "ai_accepted",
    "needs_human_review",
    "blocked",
    "not_applicable",
    "unknown",
)
HUMAN_REVIEW_DECISIONS: tuple[str, ...] = ("reviewed", "needs_human_review", "blocked")
HUMAN_REVIEWABLE_AI_DECISIONS: set[str] = {"needs_human_review", "blocked", "unknown"}


class ReviewContractError(ValueError):
    """Raised when validation or AI-review artifacts violate the PR F contract."""


def load_validation_report_document(path: str | Path) -> dict[str, Any]:
    report_path = Path(path)
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReviewContractError(f"could not read validation report {report_path}: {exc.strerror or exc}") from exc
    except json.JSONDecodeError as exc:
        raise ReviewContractError(f"could not parse validation report JSON {report_path}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise ReviewContractError("validation report must be a JSON object")
    report = dict(data)
    validate_validation_report_document(report)
    return report


def load_ai_review_document(path: str | Path) -> dict[str, Any]:
    review_path = Path(path)
    try:
        data = json.loads(review_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReviewContractError(f"could not read AI review {review_path}: {exc.strerror or exc}") from exc
    except json.JSONDecodeError as exc:
        raise ReviewContractError(f"could not parse AI review JSON {review_path}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise ReviewContractError("AI review must be a JSON object")
    review = dict(data)
    validate_ai_review_document(review)
    return review


def build_validation_report_from_path(candidate_path: str | Path) -> dict[str, Any]:
    candidate_bundle_path = Path(candidate_path)
    try:
        data = json.loads(candidate_bundle_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReviewContractError(f"could not read candidate bundle {candidate_bundle_path}: {exc.strerror or exc}") from exc
    except json.JSONDecodeError as exc:
        raise ReviewContractError(f"could not parse candidate bundle JSON {candidate_bundle_path}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise ReviewContractError("candidate bundle must be a JSON object")
    return build_validation_report(dict(data))


def build_validation_report(candidate_bundle: Mapping[str, Any]) -> dict[str, Any]:
    try:
        validate_candidate_bundle_document(candidate_bundle)
    except CandidateContractError as exc:
        issues = [
            _issue(
                path="/",
                severity="error",
                check="candidate_bundle_contract",
                message=str(exc),
                review_decision="blocked",
                materiality="high",
            )
        ]
        status = "blocked"
    else:
        issues = _domain_issues(candidate_bundle)
        status = (
            "blocked"
            if any(issue["severity"] == "error" or issue.get("review_decision") == "blocked" for issue in issues)
            else "valid_with_warnings"
        )
        if not issues:
            status = "valid"

    report = {
        "schema_version": "0.1",
        "run_id": _run_id(candidate_bundle),
        "candidate_fixture_set_id": _candidate_fixture_set_id(candidate_bundle),
        "candidate_digest": _candidate_digest(candidate_bundle),
        "validator": {"type": "deterministic", "version": "0.1.0"},
        "summary": {
            "status": status,
            "error_count": sum(1 for issue in issues if issue["severity"] == "error"),
            "warning_count": sum(1 for issue in issues if issue["severity"] == "warning"),
            "needs_human_review_count": sum(
                1 for issue in issues if issue.get("review_decision") == "needs_human_review"
            ),
            "blocked_count": sum(1 for issue in issues if issue.get("review_decision") == "blocked"),
        },
        "issues": issues,
    }
    validate_validation_report_document(report)
    return report


def build_ai_review_from_paths(candidate_path: str | Path, *, validation_path: str | Path) -> dict[str, Any]:
    candidate_bundle = load_candidate_bundle_document(candidate_path)
    validation_report = load_validation_report_document(validation_path)
    return build_ai_review(candidate_bundle, validation_report=validation_report)


def build_ai_review(candidate_bundle: Mapping[str, Any], *, validation_report: Mapping[str, Any]) -> dict[str, Any]:
    validate_candidate_bundle_document(candidate_bundle)
    validate_validation_report_document(validation_report)
    if str(validation_report["candidate_fixture_set_id"]) != str(candidate_bundle["fixture_set_id"]):
        raise ReviewContractError("validation report candidate_fixture_set_id does not match candidate bundle fixture_set_id")
    if str(validation_report["candidate_digest"]) != _candidate_digest(candidate_bundle):
        raise ReviewContractError("validation report candidate_digest does not match candidate bundle content")

    field_reviews = _deduplicate_field_reviews(
        _review_candidate_fields(candidate_bundle) + _review_validation_issues(validation_report)
    )
    if not field_reviews:
        field_reviews.append(
            _field_review(
                path="/products",
                decision="not_applicable",
                materiality="low",
                reason_code="no_reviewable_fields",
                rationale="The candidate bundle had no reviewable product fields.",
            )
        )

    summary = {
        "ai_accepted_count": sum(1 for review in field_reviews if review["decision"] == "ai_accepted"),
        "needs_human_review_count": sum(1 for review in field_reviews if review["decision"] == "needs_human_review"),
        "blocked_count": sum(1 for review in field_reviews if review["decision"] == "blocked"),
        "not_applicable_count": sum(1 for review in field_reviews if review["decision"] == "not_applicable"),
        "unknown_count": sum(1 for review in field_reviews if review["decision"] == "unknown"),
    }
    reviewer = _reviewer_descriptor(candidate_bundle)
    review = {
        "schema_version": "0.1",
        "run_id": str(validation_report["run_id"]),
        "candidate_fixture_set_id": str(candidate_bundle["fixture_set_id"]),
        "reviewer": reviewer,
        "summary": summary,
        "field_reviews": field_reviews,
    }
    validate_ai_review_document(review)
    return review


def build_human_review_html(candidate_bundle: Mapping[str, Any], *, ai_review: Mapping[str, Any]) -> str:
    validate_candidate_bundle_document(candidate_bundle)
    validate_ai_review_document(ai_review)
    if str(ai_review["candidate_fixture_set_id"]) != str(candidate_bundle["fixture_set_id"]):
        raise ReviewContractError("AI review candidate_fixture_set_id does not match candidate bundle fixture_set_id")

    evidence_by_id = _evidence_by_id(candidate_bundle)
    sections: list[str] = []
    for field_review in ai_review["field_reviews"]:
        if field_review["decision"] not in HUMAN_REVIEWABLE_AI_DECISIONS:
            continue
        candidate_item = _candidate_item_at_path(candidate_bundle, str(field_review["path"]))
        if not isinstance(candidate_item, Mapping) or "review_status" not in candidate_item:
            continue
        evidence_refs = candidate_item.get("evidence_refs", [])
        source_quotes = [str(evidence_by_id[ref].get("source_quote", "")) for ref in evidence_refs if ref in evidence_by_id]
        sections.append(
            "<article class=\"review-item\">"
            f"<h2>{html.escape(str(field_review['path']))}</h2>"
            f"<p><strong>AI decision:</strong> {html.escape(str(field_review['decision']))}</p>"
            f"<p><strong>Reason:</strong> {html.escape(str(field_review['reason_code']))}</p>"
            f"<p>{html.escape(str(field_review['rationale']))}</p>"
            f"<pre>{html.escape(json.dumps(candidate_item, ensure_ascii=False, indent=2, sort_keys=True))}</pre>"
            f"<blockquote>{html.escape(chr(10).join(source_quotes))}</blockquote>"
            "</article>"
        )
    body = "\n".join(sections) or "<p>No fields require human review.</p>"
    fixture_set_id = html.escape(str(candidate_bundle["fixture_set_id"]))
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        f"<title>Human review bundle {fixture_set_id}</title>\n"
        "</head>\n<body>\n"
        f"<h1>Human review bundle: {fixture_set_id}</h1>\n"
        "<p>This HTML is an interaction aid only. review_decisions.json is authoritative.</p>\n"
        f"{body}\n</body>\n</html>\n"
    )


def build_human_review_html_from_paths(candidate_path: str | Path, *, ai_review_path: str | Path) -> str:
    candidate_bundle = load_candidate_bundle_document(candidate_path)
    ai_review = load_ai_review_document(ai_review_path)
    return build_human_review_html(candidate_bundle, ai_review=ai_review)


def load_review_decisions_document(path: str | Path) -> dict[str, Any]:
    decisions_path = Path(path)
    try:
        data = json.loads(decisions_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReviewContractError(f"could not read review decisions {decisions_path}: {exc.strerror or exc}") from exc
    except json.JSONDecodeError as exc:
        raise ReviewContractError(f"could not parse review decisions JSON {decisions_path}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise ReviewContractError("review decisions must be a JSON object")
    decisions = dict(data)
    validate_review_decisions_document(decisions)
    return decisions


def apply_review_decisions(candidate_bundle: Mapping[str, Any], *, decisions: Mapping[str, Any]) -> dict[str, Any]:
    validate_candidate_bundle_document(candidate_bundle)
    validate_review_decisions_document(decisions)
    if str(decisions["candidate_fixture_set_id"]) != str(candidate_bundle["fixture_set_id"]):
        raise ReviewContractError("review decisions candidate_fixture_set_id does not match candidate bundle fixture_set_id")

    reviewed = deepcopy(dict(candidate_bundle))
    applied: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for decision in decisions["decisions"]:
        path = str(decision["path"])
        if path in seen_paths:
            raise ReviewContractError(f"duplicate review decision path: {path}")
        seen_paths.add(path)
        item = _candidate_item_at_path(reviewed, path)
        if not isinstance(item, dict) or "review_status" not in item:
            raise ReviewContractError(f"review decision path is not a reviewable candidate field: {path}")
        item["review_status"] = str(decision["decision"])
        if decision.get("reviewer_note"):
            item["reviewer_note"] = str(decision["reviewer_note"])
        applied.append({"path": path, "decision": str(decision["decision"])})
    reviewed["review_metadata"] = {
        "schema_version": "0.1",
        "source": "review_decisions",
        "reviewer": str(decisions.get("reviewer", "unknown")),
        "decisions_applied": applied,
    }
    validate_reviewed_product_document(reviewed)
    return reviewed


def apply_review_decisions_from_paths(candidate_path: str | Path, *, decisions_path: str | Path) -> dict[str, Any]:
    candidate_bundle = load_candidate_bundle_document(candidate_path)
    decisions = load_review_decisions_document(decisions_path)
    return apply_review_decisions(candidate_bundle, decisions=decisions)


def validate_validation_report_document(report: Mapping[str, Any]) -> None:
    schema = json.loads(resource_text("schemas/validation_report.schema.json"))
    try:
        jsonschema.Draft202012Validator(schema).validate(report)
    except jsonschema.ValidationError as exc:
        raise ReviewContractError(f"validation report does not match validation_report.schema.json: {exc.message}") from exc


def validate_ai_review_document(review: Mapping[str, Any]) -> None:
    schema = json.loads(resource_text("schemas/ai_review.schema.json"))
    try:
        jsonschema.Draft202012Validator(schema).validate(review)
    except jsonschema.ValidationError as exc:
        raise ReviewContractError(f"AI review does not match ai_review.schema.json: {exc.message}") from exc


def validate_review_decisions_document(decisions: Mapping[str, Any]) -> None:
    schema = json.loads(resource_text("schemas/review_decisions.schema.json"))
    try:
        jsonschema.Draft202012Validator(schema).validate(decisions)
    except jsonschema.ValidationError as exc:
        raise ReviewContractError(f"review decisions do not match review_decisions.schema.json: {exc.message}") from exc


def validate_reviewed_product_document(reviewed: Mapping[str, Any]) -> None:
    validate_candidate_bundle_document(reviewed)
    schema = json.loads(resource_text("schemas/reviewed_product.schema.json"))
    candidate_bundle_schema = json.loads(resource_text("schemas/candidate_bundle.schema.json"))
    candidate_product_schema = json.loads(resource_text("schemas/candidate_product.schema.json"))
    registry = Registry().with_resources(
        [
            (candidate_bundle_schema["$id"], Resource.from_contents(candidate_bundle_schema)),
            (candidate_product_schema["$id"], Resource.from_contents(candidate_product_schema)),
        ]
    )
    try:
        jsonschema.Draft202012Validator(schema, registry=registry).validate(reviewed)
    except jsonschema.ValidationError as exc:
        raise ReviewContractError(f"reviewed product does not match reviewed_product.schema.json: {exc.message}") from exc


def _domain_issues(candidate_bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for product_index, product in enumerate(candidate_bundle["products"]):
        product_path = f"/products/{product_index}"
        for collection_name in ("decrements", "benefits"):
            for item_index, item in enumerate(product[collection_name]):
                path = f"{product_path}/{collection_name}/{item_index}"
                if item["review_status"] == "ai_accepted" and float(item["confidence"]) < 0.8:
                    issues.append(
                        _issue(
                            path=path,
                            severity="error",
                            check="low_confidence_auto_acceptance",
                            message="ai_accepted fields must meet the deterministic confidence floor.",
                            review_decision="blocked",
                            materiality="high",
                        )
                    )
                if item["review_status"] == "needs_human_review":
                    issues.append(
                        _issue(
                            path=path,
                            severity="warning",
                            check="candidate_escalation_required",
                            message="Candidate extraction marked this field as requiring human review.",
                            review_decision="needs_human_review",
                            materiality=_materiality_for_item(collection_name, item),
                        )
                    )
        for unknown_index, unknown in enumerate(product["explicit_unknowns"]):
            if unknown["review_status"] == "reviewed":
                continue
            issues.append(
                _issue(
                    path=f"{product_path}/explicit_unknowns/{unknown_index}",
                    severity="warning",
                    check="explicit_unknown_not_auto_accepted",
                    message=str(unknown["reason"]),
                    review_decision="blocked" if unknown["review_status"] == "blocked" else "unknown",
                    materiality="high" if "decrements" in str(unknown["path"]) else "medium",
                )
            )
    for unsupported_index, unsupported in enumerate(candidate_bundle["unsupported_documents"]):
        issues.append(
            _issue(
                path=f"/unsupported_documents/{unsupported_index}",
                severity="warning",
                check="unsupported_document_not_auto_accepted",
                message=f"Unsupported document {unsupported['document_id']} remains outside deterministic extraction scope.",
                review_decision="blocked",
                materiality="high",
            )
        )
    return issues


def _review_candidate_fields(candidate_bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    for product_index, product in enumerate(candidate_bundle["products"]):
        product_id = str(product["product_id"])
        for collection_name in ("decrements", "benefits"):
            for item_index, item in enumerate(product[collection_name]):
                path = f"/products/{product_index}/{collection_name}/{item_index}"
                review_status = str(item["review_status"])
                if review_status == "ai_accepted":
                    reviews.append(
                        _field_review(
                            path=path,
                            decision="ai_accepted",
                            materiality=_materiality_for_item(collection_name, item),
                            reason_code="high_confidence_supported_field",
                            rationale=f"{product_id} {collection_name[:-1]} has evidence refs and sufficient deterministic confidence.",
                        )
                    )
                elif review_status == "needs_human_review":
                    reviews.append(
                        _field_review(
                            path=path,
                            decision="needs_human_review",
                            materiality=_materiality_for_item(collection_name, item),
                            reason_code="candidate_marked_needs_human_review",
                            rationale=f"{product_id} {collection_name[:-1]} is material but candidate extraction did not auto-accept it.",
                            required_human_action="Confirm the field against cited evidence before final review.",
                        )
                    )
                elif review_status == "blocked":
                    reviews.append(
                        _field_review(
                            path=path,
                            decision="blocked",
                            materiality=_materiality_for_item(collection_name, item),
                            reason_code="candidate_marked_blocked",
                            rationale=f"{product_id} {collection_name[:-1]} is blocked and requires human resolution before final review.",
                            required_human_action="Resolve the blocked candidate field against cited evidence or source gaps.",
                        )
                    )
                elif review_status == "reviewed":
                    reviews.append(
                        _field_review(
                            path=path,
                            decision="not_applicable",
                            materiality=_materiality_for_item(collection_name, item),
                            reason_code="candidate_already_reviewed",
                            rationale=f"{product_id} {collection_name[:-1]} already has reviewed candidate status.",
                        )
                    )
                else:
                    reviews.append(
                        _field_review(
                            path=path,
                            decision="unknown",
                            materiality=_materiality_for_item(collection_name, item),
                            reason_code="unsupported_candidate_review_status",
                            rationale=f"Candidate review_status {review_status!r} is not recognized by the deterministic reviewer.",
                            required_human_action="Inspect and assign a supported review decision.",
                        )
                    )
        for unknown_index, unknown in enumerate(product["explicit_unknowns"]):
            review_status = str(unknown["review_status"])
            if review_status == "reviewed":
                reviews.append(
                    _field_review(
                        path=f"/products/{product_index}/explicit_unknowns/{unknown_index}",
                        decision="not_applicable",
                        materiality="high" if "decrements" in str(unknown["path"]) else "medium",
                        reason_code="explicit_unknown_already_reviewed",
                        rationale=str(unknown["reason"]),
                    )
                )
                continue
            reviews.append(
                _field_review(
                    path=f"/products/{product_index}/explicit_unknowns/{unknown_index}",
                    decision="blocked" if review_status == "blocked" else "unknown",
                    materiality="high" if "decrements" in str(unknown["path"]) else "medium",
                    reason_code="explicit_unknown_requires_human_resolution",
                    rationale=str(unknown["reason"]),
                    required_human_action="Confirm whether the missing field is absent from source or requires additional source material.",
                )
            )
    return reviews


def _review_validation_issues(validation_report: Mapping[str, Any]) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    for issue_index, issue in enumerate(validation_report["issues"]):
        decision = str(issue.get("review_decision", "unknown"))
        if decision not in REVIEW_DECISIONS:
            decision = "unknown"
        reviews.append(
            _field_review(
                path=str(issue.get("path", f"/validation/issues/{issue_index}")),
                decision=decision,
                materiality=str(issue.get("materiality", "medium")),
                reason_code=f"validation_{issue['check']}",
                rationale=str(issue["message"]),
                required_human_action="Resolve the validation issue before final review." if decision != "ai_accepted" else None,
            )
        )
    return reviews


def _deduplicate_field_reviews(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for review in reviews:
        path = str(review["path"])
        existing = deduped.get(path)
        if existing is None or _decision_priority(review["decision"]) > _decision_priority(existing["decision"]):
            deduped[path] = review
    return list(deduped.values())


def _decision_priority(decision: str) -> int:
    priorities = {
        "not_applicable": 0,
        "ai_accepted": 1,
        "unknown": 2,
        "needs_human_review": 3,
        "blocked": 4,
    }
    return priorities.get(decision, 2)


def _evidence_by_id(candidate_bundle: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    evidence: dict[str, Mapping[str, Any]] = {}
    for product in candidate_bundle["products"]:
        for span in product.get("evidence", []):
            if isinstance(span, Mapping):
                evidence[str(span.get("id"))] = span
    return evidence


def _candidate_item_at_path(candidate_bundle: Mapping[str, Any], path: str) -> Any:
    if not path.startswith("/"):
        raise ReviewContractError(f"unsupported review path: {path}")
    current: Any = candidate_bundle
    for token in path.strip("/").split("/"):
        if isinstance(current, Mapping):
            if token not in current:
                raise ReviewContractError(f"review path does not exist: {path}")
            current = current[token]
        elif isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError) as exc:
                raise ReviewContractError(f"review path does not exist: {path}") from exc
        else:
            raise ReviewContractError(f"review path does not exist: {path}")
    return current


def _issue(
    *,
    path: str,
    severity: str,
    check: str,
    message: str,
    review_decision: str,
    materiality: str,
) -> dict[str, Any]:
    return {
        "path": path,
        "severity": severity,
        "check": check,
        "message": message,
        "review_decision": review_decision,
        "materiality": materiality,
    }


def _field_review(
    *,
    path: str,
    decision: str,
    materiality: str,
    reason_code: str,
    rationale: str,
    required_human_action: str | None = None,
) -> dict[str, Any]:
    review = {
        "path": path,
        "decision": decision,
        "materiality": materiality,
        "reason_code": reason_code,
        "rationale": rationale,
    }
    if decision in {"needs_human_review", "blocked", "unknown"}:
        review["required_human_action"] = required_human_action or "Inspect this field before final review."
    return review


def _materiality_for_item(collection_name: str, item: Mapping[str, Any]) -> str:
    if collection_name == "decrements" or item.get("benefit_type") == "death_benefit":
        return "high"
    if item.get("benefit_type") in {"cash_value_accumulation", "account_value_crediting", "investment_account_option"}:
        return "medium"
    return "low"


def _reviewer_descriptor(candidate_bundle: Mapping[str, Any]) -> dict[str, Any]:
    product_identities = [product["product_identity"] for product in candidate_bundle["products"]]
    region_families = sorted({str(identity["region_family"]) for identity in product_identities})
    product_classes = sorted({str(identity["product_class_primary"]) for identity in product_identities})
    if not region_families and not product_classes:
        skillpack = "unknown/unknown"
    elif len(region_families) == 1 and len(product_classes) == 1:
        skillpack = f"{region_families[0]}/{product_classes[0]}"
    elif len(region_families) == 1:
        skillpack = f"{region_families[0]}/mixed_" + "_".join(product_classes)
    else:
        skillpack = "mixed_regions/mixed_" + "_".join(product_classes)
    return {
        "type": "ai",
        "mode": "deterministic_stub",
        "skillpack": skillpack,
        "version": "0.1.0",
        "region_families": region_families,
        "product_classes": product_classes,
    }


def _candidate_digest(candidate_bundle: Mapping[str, Any]) -> str:
    canonical = json.dumps(candidate_bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _run_id(candidate_bundle: Mapping[str, Any]) -> str:
    return f"{_candidate_fixture_set_id(candidate_bundle)}-validation-v0-1"


def _candidate_fixture_set_id(candidate_bundle: Mapping[str, Any]) -> str:
    fixture_set_id = str(candidate_bundle.get("fixture_set_id") or "unknown")
    return fixture_set_id if fixture_set_id.strip() else "unknown"
