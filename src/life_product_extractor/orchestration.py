from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .extract import extract_candidate_bundle_from_paths
from .review import build_ai_review, build_human_review_html, build_validation_report
from .routing import classify_fixture_manifest_from_path
from .sections import sectionize_fixture_manifest_from_path
from .status import build_status_report_from_artifacts


def run_pipeline_from_path(manifest_path: str | Path, *, out_dir: str | Path) -> dict[str, Any]:
    """Run the deterministic no-human-decision pipeline and write standard artifacts."""
    manifest = Path(manifest_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    routing = classify_fixture_manifest_from_path(manifest)
    routing_path = out / "routing.json"
    routing_path.write_text(json.dumps(routing, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    sections_documents = sectionize_fixture_manifest_from_path(manifest)
    sections_path = out / "sections_structured.jsonl"
    sections_path.write_text(
        "\n".join(json.dumps(document, ensure_ascii=False, sort_keys=False) for document in sections_documents) + "\n",
        encoding="utf-8",
    )

    candidate = extract_candidate_bundle_from_paths(manifest, routing_path=routing_path, sections_path=sections_path)
    candidate_path = out / "candidate.json"
    candidate_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    validation = build_validation_report(candidate)
    validation_path = out / "validation_report.json"
    validation_path.write_text(json.dumps(validation, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    ai_review = build_ai_review(candidate, validation_report=validation)
    ai_review_path = out / "ai_review.json"
    ai_review_path.write_text(json.dumps(ai_review, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    review_html_path = out / "review.html"
    review_html_path.write_text(build_human_review_html(candidate, ai_review=ai_review), encoding="utf-8")

    status = build_status_report_from_artifacts(candidate_bundle=candidate, validation_report=validation, ai_review=ai_review)
    status_json_path = out / "status_report.json"
    status_md_path = out / "status_report.md"
    status_json_path.write_text(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    status_md_path.write_text(render_status_report_markdown(status), encoding="utf-8")

    return {
        "ok": True,
        "fixture_set_id": candidate["fixture_set_id"],
        "out_dir": str(out),
        "artifacts": {
            "routing": str(routing_path),
            "sections": str(sections_path),
            "candidate": str(candidate_path),
            "validation_report": str(validation_path),
            "ai_review": str(ai_review_path),
            "review_html": str(review_html_path),
            "status_report_json": str(status_json_path),
            "status_report_md": str(status_md_path),
        },
        "status": status["summary"]["status"],
        "needs_human_review_count": status["summary"]["needs_human_review_count"],
        "blocked_count": status["summary"]["blocked_count"],
    }


def render_status_report_markdown(status_report: dict[str, Any]) -> str:
    summary = status_report["summary"]
    lines = [
        f"# Status report: {status_report['fixture_set_id']}",
        "",
        f"- Run ID: `{status_report['run_id']}`",
        f"- Status: `{summary['status']}`",
        f"- Products: {summary['product_count']}",
        f"- Unsupported documents: {summary['unsupported_document_count']}",
        f"- Needs human review: {summary['needs_human_review_count']}",
        f"- Blocked: {summary['blocked_count']}",
        f"- Model ready: {str(summary['model_ready']).lower()}",
        "",
        "## Blockers",
        "",
    ]
    blockers = status_report.get("blockers", [])
    if blockers:
        lines.extend(f"- `{blocker['path']}`: {blocker['message']}" for blocker in blockers)
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)
