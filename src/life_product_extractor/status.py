from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import jsonschema

from .extract import load_candidate_bundle_document, validate_candidate_bundle_document
from .resources import resource_text
from .review import (
    _candidate_digest,
    load_ai_review_document,
    load_validation_report_document,
    validate_ai_review_document,
    validate_reviewed_product_document,
    validate_validation_report_document,
)


class StatusContractError(ValueError):
    """Raised when status report inputs or outputs violate the PR G contract."""


def build_status_report_from_reviewed_path(reviewed_path: str | Path) -> dict[str, Any]:
    path = Path(reviewed_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise StatusContractError(f"could not read reviewed product {path}: {exc.strerror or exc}") from exc
    except json.JSONDecodeError as exc:
        raise StatusContractError(f"could not parse reviewed product JSON {path}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise StatusContractError("reviewed product must be a JSON object")
    reviewed = dict(data)
    validate_reviewed_product_document(reviewed)
    return build_status_report_from_reviewed(reviewed)


def build_status_report_from_artifact_paths(
    *, candidate_path: str | Path, validation_path: str | Path, ai_review_path: str | Path
) -> dict[str, Any]:
    candidate = load_candidate_bundle_document(candidate_path)
    validation = load_validation_report_document(validation_path)
    ai_review = load_ai_review_document(ai_review_path)
    return build_status_report_from_artifacts(candidate_bundle=candidate, validation_report=validation, ai_review=ai_review)


def build_status_report_from_reviewed(reviewed: Mapping[str, Any]) -> dict[str, Any]:
    validate_reviewed_product_document(reviewed)
    needs_human_review = 0
    blocked = 0
    blockers: list[dict[str, str]] = []
    for product_index, product in enumerate(reviewed["products"]):
        for collection_name in ("decrements", "benefits"):
            for item_index, item in enumerate(product[collection_name]):
                status = str(item["review_status"])
                path = f"/products/{product_index}/{collection_name}/{item_index}"
                if status == "needs_human_review":
                    needs_human_review += 1
                    blockers.append({"path": path, "message": "Field still needs human review."})
                elif status == "blocked":
                    blocked += 1
                    blockers.append({"path": path, "message": "Field remains blocked."})
        for unknown_index, unknown in enumerate(product["explicit_unknowns"]):
            status = str(unknown["review_status"])
            if status != "reviewed":
                path = f"/products/{product_index}/explicit_unknowns/{unknown_index}"
                if status == "blocked":
                    blocked += 1
                else:
                    needs_human_review += 1
                blockers.append({"path": path, "message": str(unknown["reason"])})
    for unsupported_index, unsupported in enumerate(reviewed["unsupported_documents"]):
        blocked += 1
        blockers.append(
            {"path": f"/unsupported_documents/{unsupported_index}", "message": str(unsupported["reason"])}
        )
    return _status_report(
        run_id=str(reviewed["review_metadata"].get("run_id") or f"{reviewed['fixture_set_id']}-reviewed-v0-1"),
        fixture_set_id=str(reviewed["fixture_set_id"]),
        product_count=int(reviewed["summary"]["product_count"]),
        unsupported_document_count=int(reviewed["summary"]["unsupported_document_count"]),
        needs_human_review_count=needs_human_review,
        blocked_count=blocked,
        blockers=blockers,
        source="reviewed",
    )


def build_status_report_from_artifacts(
    *, candidate_bundle: Mapping[str, Any], validation_report: Mapping[str, Any], ai_review: Mapping[str, Any]
) -> dict[str, Any]:
    validate_candidate_bundle_document(candidate_bundle)
    validate_validation_report_document(validation_report)
    validate_ai_review_document(ai_review)
    _validate_artifact_consistency(
        candidate_bundle=candidate_bundle,
        validation_report=validation_report,
        ai_review=ai_review,
    )
    blockers_by_path: dict[str, str] = {}
    blocked_paths: set[str] = set()
    needs_human_review_paths: set[str] = set()
    for issue in validation_report["issues"]:
        path = str(issue["path"])
        decision = str(issue.get("review_decision", "unknown"))
        if issue["severity"] == "error":
            blocked_paths.add(path)
            blockers_by_path.setdefault(path, str(issue["message"]))
        elif decision in {"blocked", "needs_human_review", "unknown"}:
            if decision == "blocked":
                blocked_paths.add(path)
            else:
                needs_human_review_paths.add(path)
            blockers_by_path.setdefault(path, str(issue["message"]))
    for field_review in ai_review["field_reviews"]:
        path = str(field_review["path"])
        decision = str(field_review["decision"])
        if decision == "blocked":
            blocked_paths.add(path)
            blockers_by_path.setdefault(path, str(field_review["rationale"]))
        elif decision in {"needs_human_review", "unknown"}:
            needs_human_review_paths.add(path)
            blockers_by_path.setdefault(path, str(field_review["rationale"]))
    needs_human_review_paths -= blocked_paths
    blockers = [{"path": path, "message": message} for path, message in blockers_by_path.items()]
    report = _status_report(
        run_id=str(validation_report["run_id"]),
        fixture_set_id=str(candidate_bundle["fixture_set_id"]),
        product_count=int(candidate_bundle["summary"]["product_count"]),
        unsupported_document_count=int(candidate_bundle["summary"]["unsupported_document_count"]),
        needs_human_review_count=len(needs_human_review_paths),
        blocked_count=len(blocked_paths),
        blockers=blockers,
        source="run_artifacts",
    )
    validate_status_report_document(report)
    return report


def validate_status_report_document(report: Mapping[str, Any]) -> None:
    schema = json.loads(resource_text("schemas/status_report.schema.json"))
    try:
        jsonschema.Draft202012Validator(schema).validate(report)
    except jsonschema.ValidationError as exc:
        raise StatusContractError(f"status report does not match status_report.schema.json: {exc.message}") from exc


def _validate_artifact_consistency(
    *, candidate_bundle: Mapping[str, Any], validation_report: Mapping[str, Any], ai_review: Mapping[str, Any]
) -> None:
    fixture_set_id = str(candidate_bundle["fixture_set_id"])
    if str(validation_report["candidate_fixture_set_id"]) != fixture_set_id:
        raise StatusContractError("validation report candidate_fixture_set_id does not match candidate bundle fixture_set_id")
    if str(ai_review["candidate_fixture_set_id"]) != fixture_set_id:
        raise StatusContractError("AI review candidate_fixture_set_id does not match candidate bundle fixture_set_id")
    if str(validation_report["candidate_digest"]) != _candidate_digest(candidate_bundle):
        raise StatusContractError("validation report candidate_digest does not match candidate bundle content")
    if str(ai_review["run_id"]) != str(validation_report["run_id"]):
        raise StatusContractError("AI review run_id does not match validation report run_id")
    if str(ai_review["candidate_digest"]) != str(validation_report["candidate_digest"]):
        raise StatusContractError("AI review candidate_digest does not match validation report candidate_digest")


def _status_report(
    *,
    run_id: str,
    fixture_set_id: str,
    product_count: int,
    unsupported_document_count: int,
    needs_human_review_count: int,
    blocked_count: int,
    blockers: list[dict[str, str]],
    source: str,
) -> dict[str, Any]:
    if blocked_count > 0 or unsupported_document_count > 0:
        status = "blocked"
    elif needs_human_review_count > 0:
        status = "needs_human_review"
    else:
        status = "ready"
    return {
        "schema_version": "0.1",
        "run_id": run_id,
        "fixture_set_id": fixture_set_id,
        "source": source,
        "summary": {
            "status": status,
            "model_ready": status == "ready",
            "product_count": product_count,
            "unsupported_document_count": unsupported_document_count,
            "needs_human_review_count": needs_human_review_count,
            "blocked_count": blocked_count,
        },
        "blockers": blockers,
    }
