from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from ..catalog import SourceCatalogError, load_source_catalog_document, validate_source_catalog_document
from ..extract import CandidateContractError, extract_candidate_bundle_from_paths
from ..fixtures import DEFAULT_FIXTURE_SPEC_RESOURCE, FixtureContractError, build_fixture_bundle_from_paths
from ..learn import LearningContractError, build_skill_improvement_candidates_from_reviewed_path
from ..orchestration import render_status_report_markdown, run_pipeline_from_path
from ..resources import resource_path
from ..review import (
    ReviewContractError,
    apply_review_decisions_from_paths,
    build_ai_review_from_paths,
    build_human_review_html_from_paths,
    build_validation_report_from_path,
)
from ..routing import RoutingContractError, classify_fixture_manifest_from_path
from ..sections import SectionContractError, sectionize_fixture_manifest_from_path
from ..status import StatusContractError, build_status_report_from_artifact_paths, build_status_report_from_reviewed_path

_CONTRACT_ERRORS = (
    SourceCatalogError,
    FixtureContractError,
    RoutingContractError,
    SectionContractError,
    CandidateContractError,
    ReviewContractError,
    StatusContractError,
    LearningContractError,
)


def create_app() -> FastAPI:
    """Create the API app over the same deterministic service layer used by the CLI."""

    app = FastAPI(
        title="life_product_extractor API",
        version="0.1.0",
        description="API wrapper for auditable life insurance product extraction pipeline artifacts.",
    )

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/v1/runs/validate-catalog")
    def validate_catalog(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            catalog_path = payload.get("catalog_path")
            if catalog_path is None:
                with resource_path("examples/sources/manulife_sources.yaml") as default_catalog_path:
                    catalog = load_source_catalog_document(default_catalog_path)
            else:
                catalog = load_source_catalog_document(_path(catalog_path, "catalog_path"))
            validate_source_catalog_document(catalog)
            return {"ok": True, "source_count": len(catalog["sources"])}
        except _CONTRACT_ERRORS as exc:
            raise _contract_http_error(exc) from exc

    @app.post("/v1/runs/build-fixtures")
    def build_fixtures(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            out_dir = _path(_required(payload, "out_dir"), "out_dir")
            catalog_path = _optional_path(payload.get("catalog_path"), "catalog_path")
            spec_path = _optional_path(payload.get("spec_path"), "spec_path")
            if spec_path is None:
                with resource_path(DEFAULT_FIXTURE_SPEC_RESOURCE) as default_spec_path:
                    manifest = build_fixture_bundle_from_paths(
                        spec_path=default_spec_path,
                        output_dir=out_dir,
                        catalog_path=catalog_path,
                    )
            else:
                manifest = build_fixture_bundle_from_paths(spec_path=spec_path, output_dir=out_dir, catalog_path=catalog_path)
            return {
                "ok": True,
                "fixture_set_id": manifest["fixture_set_id"],
                "document_count": len(manifest["documents"]),
                "scenario_count": len(manifest["paired_source_scenarios"]),
                "manifest_path": str(out_dir / "manifest.json"),
            }
        except _CONTRACT_ERRORS as exc:
            raise _contract_http_error(exc) from exc

    @app.post("/v1/runs/classify")
    def classify(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return classify_fixture_manifest_from_path(
                _path(_required(payload, "manifest_path"), "manifest_path"),
                catalog_path=_optional_path(payload.get("catalog_path"), "catalog_path"),
            )
        except _CONTRACT_ERRORS as exc:
            raise _contract_http_error(exc) from exc

    @app.post("/v1/runs/sectionize")
    def sectionize(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            documents = sectionize_fixture_manifest_from_path(_path(_required(payload, "manifest_path"), "manifest_path"))
            return {"ok": True, "documents": documents}
        except _CONTRACT_ERRORS as exc:
            raise _contract_http_error(exc) from exc

    @app.post("/v1/runs/extract")
    def extract(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return extract_candidate_bundle_from_paths(
                _path(_required(payload, "manifest_path"), "manifest_path"),
                routing_path=_path(_required(payload, "routing_path"), "routing_path"),
                sections_path=_path(_required(payload, "sections_path"), "sections_path"),
            )
        except _CONTRACT_ERRORS as exc:
            raise _contract_http_error(exc) from exc

    @app.post("/v1/runs/validate")
    def validate(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return build_validation_report_from_path(_path(_required(payload, "candidate_path"), "candidate_path"))
        except _CONTRACT_ERRORS as exc:
            raise _contract_http_error(exc) from exc

    @app.post("/v1/runs/ai-review")
    def ai_review(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return build_ai_review_from_paths(
                _path(_required(payload, "candidate_path"), "candidate_path"),
                validation_path=_path(_required(payload, "validation_path"), "validation_path"),
            )
        except _CONTRACT_ERRORS as exc:
            raise _contract_http_error(exc) from exc

    @app.post("/v1/runs/review-bundle")
    def review_bundle(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            html = build_human_review_html_from_paths(
                _path(_required(payload, "candidate_path"), "candidate_path"),
                ai_review_path=_path(_required(payload, "ai_review_path"), "ai_review_path"),
            )
            return {"ok": True, "html": html}
        except _CONTRACT_ERRORS as exc:
            raise _contract_http_error(exc) from exc

    @app.post("/v1/runs/apply-review")
    def apply_review(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return apply_review_decisions_from_paths(
                _path(_required(payload, "candidate_path"), "candidate_path"),
                decisions_path=_path(_required(payload, "decisions_path"), "decisions_path"),
            )
        except _CONTRACT_ERRORS as exc:
            raise _contract_http_error(exc) from exc

    @app.post("/v1/runs/status")
    def status(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            if payload.get("reviewed_path") is not None:
                report = build_status_report_from_reviewed_path(_path(payload["reviewed_path"], "reviewed_path"))
            else:
                report = build_status_report_from_artifact_paths(
                    candidate_path=_path(_required(payload, "candidate_path"), "candidate_path"),
                    validation_path=_path(_required(payload, "validation_path"), "validation_path"),
                    ai_review_path=_path(_required(payload, "ai_review_path"), "ai_review_path"),
                )
            include_markdown = bool(payload.get("include_markdown", False))
            if include_markdown:
                return {"ok": True, "report": report, "markdown": render_status_report_markdown(report)}
            return report
        except _CONTRACT_ERRORS as exc:
            raise _contract_http_error(exc) from exc

    @app.post("/v1/runs/learn/propose")
    def learn_propose(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            reviewed_paths = payload.get("reviewed_paths")
            if not isinstance(reviewed_paths, list) or not reviewed_paths:
                raise LearningContractError("reviewed_paths must be a non-empty list")
            return build_skill_improvement_candidates_from_reviewed_path(
                [_path(path, "reviewed_paths[]") for path in reviewed_paths]
            )
        except _CONTRACT_ERRORS as exc:
            raise _contract_http_error(exc) from exc

    @app.post("/v1/runs/run")
    def run(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return run_pipeline_from_path(
                _path(_required(payload, "manifest_path"), "manifest_path"),
                out_dir=_path(_required(payload, "out_dir"), "out_dir"),
            )
        except _CONTRACT_ERRORS as exc:
            raise _contract_http_error(exc) from exc

    return app


def _contract_http_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=422, detail={"ok": False, "error": str(exc)})


def _required(payload: dict[str, Any], key: str) -> Any:
    value = payload.get(key)
    if value in (None, ""):
        raise HTTPException(status_code=422, detail={"ok": False, "error": f"{key} is required"})
    return value


def _path(value: Any, field_name: str) -> Path:
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail={"ok": False, "error": f"{field_name} must be a string path"})
    return Path(value)


def _optional_path(value: Any, field_name: str) -> Path | None:
    if value in (None, ""):
        return None
    return _path(value, field_name)


app = create_app()
