from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from life_product_extractor.api import create_app
from life_product_extractor.orchestration import run_pipeline_from_path
from life_product_extractor.routing import classify_fixture_manifest_from_path
from life_product_extractor.status import build_status_report_from_artifact_paths

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "examples" / "fixtures" / "manulife_tier1_curated" / "manifest.json"


def test_api_classify_wraps_shared_service_layer() -> None:
    client = TestClient(create_app())

    response = client.post("/v1/runs/classify", json={"manifest_path": str(MANIFEST)})

    assert response.status_code == 200
    assert response.json() == classify_fixture_manifest_from_path(MANIFEST)


def test_api_run_writes_standard_artifacts_and_matches_shared_pipeline(tmp_path: Path) -> None:
    client = TestClient(create_app())
    api_out = tmp_path / "api"
    service_out = tmp_path / "service"

    response = client.post("/v1/runs/run", json={"manifest_path": str(MANIFEST), "out_dir": str(api_out)})

    assert response.status_code == 200
    expected = run_pipeline_from_path(MANIFEST, out_dir=service_out)
    payload = response.json()
    assert payload["ok"] is True
    assert payload["fixture_set_id"] == expected["fixture_set_id"]
    assert payload["status"] == expected["status"]
    assert payload["needs_human_review_count"] == expected["needs_human_review_count"]
    assert payload["blocked_count"] == expected["blocked_count"]
    for artifact_path in payload["artifacts"].values():
        assert Path(artifact_path).exists()


def test_api_status_returns_contract_and_optional_markdown(tmp_path: Path) -> None:
    client = TestClient(create_app())
    out_dir = tmp_path / "run"
    run_pipeline_from_path(MANIFEST, out_dir=out_dir)

    response = client.post(
        "/v1/runs/status",
        json={
            "candidate_path": str(out_dir / "candidate.json"),
            "validation_path": str(out_dir / "validation_report.json"),
            "ai_review_path": str(out_dir / "ai_review.json"),
            "include_markdown": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    expected_report = build_status_report_from_artifact_paths(
        candidate_path=out_dir / "candidate.json",
        validation_path=out_dir / "validation_report.json",
        ai_review_path=out_dir / "ai_review.json",
    )
    assert payload["ok"] is True
    assert payload["report"] == expected_report
    assert "# Status report:" in payload["markdown"]


def test_api_contract_errors_are_wrapped_as_422(tmp_path: Path) -> None:
    client = TestClient(create_app())
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("not json\n", encoding="utf-8")

    response = client.post("/v1/runs/validate", json={"candidate_path": str(bad_json)})

    assert response.status_code == 422
    assert response.json()["detail"]["ok"] is False
    assert "could not parse candidate bundle JSON" in response.json()["detail"]["error"]
