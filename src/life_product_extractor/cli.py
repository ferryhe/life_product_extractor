from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from ._version import __version__
from .catalog import SourceCatalogError, load_source_catalog_document, validate_source_catalog_document
from .extract import CandidateContractError, extract_candidate_bundle_from_paths
from .fixtures import (
    DEFAULT_FIXTURE_SPEC_RESOURCE,
    FixtureContractError,
    build_fixture_bundle_from_paths,
)
from .resources import resource_path
from .review import (
    ReviewContractError,
    apply_review_decisions_from_paths,
    build_ai_review_from_paths,
    build_human_review_html_from_paths,
    build_validation_report_from_path,
)
from .routing import RoutingContractError, classify_fixture_manifest_from_path
from .sections import SectionContractError, sectionize_fixture_manifest_from_path
from .orchestration import render_status_report_markdown, run_pipeline_from_path
from .learn import LearningContractError, build_skill_improvement_candidates_from_reviewed_path
from .status import (
    StatusContractError,
    build_status_report_from_artifact_paths,
    build_status_report_from_reviewed_path,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="life-extract",
        description="Auditable life insurance product extraction from Markdown to reviewed JSON.",
    )
    parser.add_argument("--version", action="version", version=f"life-extract {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    validate_catalog = subparsers.add_parser(
        "validate-catalog",
        help="Validate a source catalog YAML file against the project contract.",
    )
    validate_catalog.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="Path to a source catalog YAML file. Defaults to the bundled Manulife source catalog.",
    )
    validate_catalog.set_defaults(func=_cmd_validate_catalog)

    build_fixtures = subparsers.add_parser(
        "build-fixtures",
        help="Build deterministic curated Markdown fixtures and manifest from committed fixture data.",
    )
    build_fixtures.add_argument(
        "--spec",
        type=Path,
        default=None,
        help="Path to a fixture builder YAML spec. Defaults to the bundled Manulife fixture spec.",
    )
    build_fixtures.add_argument(
        "--out-dir",
        type=Path,
        required=True,
        help="Directory where the manifest and Markdown fixture files will be written.",
    )
    build_fixtures.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="Optional path to a source catalog YAML file. Defaults to the bundled Manulife source catalog.",
    )
    build_fixtures.set_defaults(func=_cmd_build_fixtures)

    classify = subparsers.add_parser(
        "classify",
        help="Classify a curated fixture manifest into deterministic routing.json output.",
    )
    classify.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to a curated fixture manifest JSON file.",
    )
    classify.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Path where routing.json will be written.",
    )
    classify.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="Optional path to a source catalog YAML file. Defaults to the catalog referenced by the manifest.",
    )
    classify.set_defaults(func=_cmd_classify)

    sectionize = subparsers.add_parser(
        "sectionize",
        help="Sectionize a curated fixture manifest into deterministic sections_structured.jsonl output.",
    )
    sectionize.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to a curated fixture manifest JSON file.",
    )
    sectionize.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Path where sections_structured.jsonl will be written.",
    )
    sectionize.set_defaults(func=_cmd_sectionize)

    extract = subparsers.add_parser(
        "extract",
        help="Extract deterministic candidate.json output from manifest, routing, and sectionized inputs.",
    )
    extract.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to a curated fixture manifest JSON file.",
    )
    extract.add_argument(
        "--routing",
        type=Path,
        required=True,
        help="Path to routing.json produced by life-extract classify.",
    )
    extract.add_argument(
        "--sections",
        type=Path,
        required=True,
        help="Path to sections_structured.jsonl produced by life-extract sectionize.",
    )
    extract.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Path where candidate.json will be written.",
    )
    extract.set_defaults(func=_cmd_extract)

    validate = subparsers.add_parser(
        "validate",
        help="Validate candidate.json and write validation_report.json output.",
    )
    validate.add_argument(
        "--candidate",
        type=Path,
        required=True,
        help="Path to candidate.json produced by life-extract extract.",
    )
    validate.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Path where validation_report.json will be written.",
    )
    validate.set_defaults(func=_cmd_validate)

    ai_review = subparsers.add_parser(
        "ai-review",
        help="Run deterministic AI-review stub and write ai_review.json output.",
    )
    ai_review.add_argument(
        "--candidate",
        type=Path,
        required=True,
        help="Path to candidate.json produced by life-extract extract.",
    )
    ai_review.add_argument(
        "--validation",
        type=Path,
        required=True,
        help="Path to validation_report.json produced by life-extract validate.",
    )
    ai_review.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Path where ai_review.json will be written.",
    )
    ai_review.set_defaults(func=_cmd_ai_review)

    review = subparsers.add_parser(
        "review",
        help="Build human review bundles and apply review_decisions.json.",
    )
    review_subparsers = review.add_subparsers(dest="review_command")

    review_build_html = review_subparsers.add_parser(
        "build-html",
        help="Write a static HTML bundle for fields that need human review.",
    )
    review_build_html.add_argument(
        "--candidate",
        type=Path,
        required=True,
        help="Path to candidate.json produced by life-extract extract.",
    )
    review_build_html.add_argument(
        "--ai-review",
        dest="ai_review",
        type=Path,
        required=True,
        help="Path to ai_review.json produced by life-extract ai-review.",
    )
    review_build_html.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Path where review.html will be written.",
    )
    review_build_html.set_defaults(func=_cmd_review_build_html)

    review_apply = review_subparsers.add_parser(
        "apply",
        help="Apply authoritative review_decisions.json to candidate.json and write reviewed.json.",
    )
    review_apply.add_argument(
        "--candidate",
        type=Path,
        required=True,
        help="Path to candidate.json produced by life-extract extract.",
    )
    review_apply.add_argument(
        "--decisions",
        type=Path,
        required=True,
        help="Path to review_decisions.json provided by human review.",
    )
    review_apply.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Path where reviewed.json will be written.",
    )
    review_apply.set_defaults(func=_cmd_review_apply)

    run = subparsers.add_parser(
        "run",
        help="Run classify -> sectionize -> extract -> validate -> ai-review -> review HTML/status artifacts.",
    )
    run.add_argument("--manifest", type=Path, required=True, help="Path to a curated fixture manifest JSON file.")
    run.add_argument("--out", type=Path, required=True, help="Directory where pipeline artifacts will be written.")
    run.set_defaults(func=_cmd_run)

    status = subparsers.add_parser(
        "status",
        help="Build status_report.json and status_report.md from reviewed JSON or run artifacts.",
    )
    status.add_argument("--reviewed", type=Path, default=None, help="Path to reviewed.json produced by review apply.")
    status.add_argument("--candidate", type=Path, default=None, help="Path to candidate.json for no-human-decision run status.")
    status.add_argument("--validation", type=Path, default=None, help="Path to validation_report.json for run status.")
    status.add_argument("--ai-review", dest="ai_review", type=Path, default=None, help="Path to ai_review.json for run status.")
    status.add_argument("--out-json", type=Path, required=True, help="Path where status_report.json will be written.")
    status.add_argument("--out-md", type=Path, required=True, help="Path where status_report.md will be written.")
    status.set_defaults(func=_cmd_status)

    learn = subparsers.add_parser(
        "learn",
        help="Generate proposed-only skill improvement artifacts from reviewed runs.",
    )
    learn_subparsers = learn.add_subparsers(dest="learn_command")
    learn_propose = learn_subparsers.add_parser(
        "propose",
        help="Write skill_improvement_candidates.json without mutating active skill packs.",
    )
    learn_propose.add_argument(
        "--reviewed",
        type=Path,
        required=True,
        nargs="+",
        help="One or more reviewed.json files produced by review apply.",
    )
    learn_propose.add_argument("--out", type=Path, required=True, help="Path where skill_improvement_candidates.json will be written.")
    learn_propose.set_defaults(func=_cmd_learn_propose)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    try:
        return int(args.func(args))
    except (
        SourceCatalogError,
        FixtureContractError,
        RoutingContractError,
        SectionContractError,
        CandidateContractError,
        ReviewContractError,
        StatusContractError,
        LearningContractError,
    ) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2


def _cmd_validate_catalog(args: argparse.Namespace) -> int:
    if args.catalog is not None:
        catalog = load_source_catalog_document(args.catalog)
        validate_source_catalog_document(catalog)
        print(json.dumps({"ok": True, "source_count": len(catalog["sources"])}, ensure_ascii=False, sort_keys=True))
        return 0

    with resource_path("examples/sources/manulife_sources.yaml") as default_catalog_path:
        catalog = load_source_catalog_document(default_catalog_path)
        validate_source_catalog_document(catalog)
        print(json.dumps({"ok": True, "source_count": len(catalog["sources"])}, ensure_ascii=False, sort_keys=True))
        return 0


def _cmd_build_fixtures(args: argparse.Namespace) -> int:
    if args.spec is not None:
        manifest = build_fixture_bundle_from_paths(spec_path=args.spec, output_dir=args.out_dir, catalog_path=args.catalog)
    else:
        with resource_path(DEFAULT_FIXTURE_SPEC_RESOURCE) as default_spec_path:
            manifest = build_fixture_bundle_from_paths(spec_path=default_spec_path, output_dir=args.out_dir, catalog_path=args.catalog)

    print(
        json.dumps(
            {
                "ok": True,
                "fixture_set_id": manifest["fixture_set_id"],
                "document_count": len(manifest["documents"]),
                "scenario_count": len(manifest["paired_source_scenarios"]),
                "manifest_path": str(args.out_dir / "manifest.json"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _cmd_classify(args: argparse.Namespace) -> int:
    routing = classify_fixture_manifest_from_path(args.manifest, catalog_path=args.catalog)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(routing, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "fixture_set_id": routing["fixture_set_id"],
                "document_count": routing["summary"]["document_count"],
                "scenario_count": routing["summary"]["scenario_count"],
                "routing_path": str(args.out),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _cmd_sectionize(args: argparse.Namespace) -> int:
    sections_documents = sectionize_fixture_manifest_from_path(args.manifest)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(document, ensure_ascii=False, sort_keys=False) for document in sections_documents) + "\n"
    args.out.write_text(payload, encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "document_count": len(sections_documents),
                "sections_path": str(args.out),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _cmd_extract(args: argparse.Namespace) -> int:
    candidate_bundle = extract_candidate_bundle_from_paths(
        args.manifest,
        routing_path=args.routing,
        sections_path=args.sections,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(candidate_bundle, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "fixture_set_id": candidate_bundle["fixture_set_id"],
                "product_count": candidate_bundle["summary"]["product_count"],
                "unsupported_document_count": candidate_bundle["summary"]["unsupported_document_count"],
                "candidate_path": str(args.out),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    validation_report = build_validation_report_from_path(args.candidate)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(validation_report, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "run_id": validation_report["run_id"],
                "status": validation_report["summary"]["status"],
                "issue_count": len(validation_report["issues"]),
                "validation_path": str(args.out),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _cmd_ai_review(args: argparse.Namespace) -> int:
    ai_review = build_ai_review_from_paths(args.candidate, validation_path=args.validation)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(ai_review, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "run_id": ai_review["run_id"],
                "field_review_count": len(ai_review["field_reviews"]),
                "needs_human_review_count": ai_review["summary"]["needs_human_review_count"],
                "blocked_count": ai_review["summary"]["blocked_count"],
                "ai_review_path": str(args.out),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _cmd_review_build_html(args: argparse.Namespace) -> int:
    review_html = build_human_review_html_from_paths(args.candidate, ai_review_path=args.ai_review)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(review_html, encoding="utf-8")
    print(json.dumps({"ok": True, "review_html_path": str(args.out)}, ensure_ascii=False, sort_keys=True))
    return 0


def _cmd_review_apply(args: argparse.Namespace) -> int:
    reviewed = apply_review_decisions_from_paths(args.candidate, decisions_path=args.decisions)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(reviewed, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "fixture_set_id": reviewed["fixture_set_id"],
                "decisions_applied_count": len(reviewed["review_metadata"]["decisions_applied"]),
                "reviewed_path": str(args.out),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    result = run_pipeline_from_path(args.manifest, out_dir=args.out)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    if args.reviewed is not None:
        report = build_status_report_from_reviewed_path(args.reviewed)
    elif args.candidate is not None and args.validation is not None and args.ai_review is not None:
        report = build_status_report_from_artifact_paths(
            candidate_path=args.candidate,
            validation_path=args.validation,
            ai_review_path=args.ai_review,
        )
    else:
        raise StatusContractError("status requires either --reviewed or all of --candidate --validation --ai-review")
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    args.out_md.write_text(render_status_report_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "fixture_set_id": report["fixture_set_id"],
                "status": report["summary"]["status"],
                "status_json_path": str(args.out_json),
                "status_md_path": str(args.out_md),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _cmd_learn_propose(args: argparse.Namespace) -> int:
    proposal = build_skill_improvement_candidates_from_reviewed_path(args.reviewed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(proposal, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "run_id": proposal["run_id"],
                "fixture_set_id": proposal["fixture_set_id"],
                "candidate_count": proposal["summary"]["candidate_count"],
                "auto_applied_count": proposal["summary"]["auto_applied_count"],
                "skill_improvement_candidates_path": str(args.out),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
