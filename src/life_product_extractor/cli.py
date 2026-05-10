from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from ._version import __version__
from .catalog import SourceCatalogError, load_source_catalog_document, validate_source_catalog_document
from .fixtures import (
    DEFAULT_FIXTURE_SPEC_RESOURCE,
    FixtureContractError,
    build_fixture_bundle_from_paths,
)
from .resources import resource_path
from .routing import RoutingContractError, classify_fixture_manifest_from_path
from .sections import SectionContractError, sectionize_fixture_manifest_from_path


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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    try:
        return int(args.func(args))
    except (SourceCatalogError, FixtureContractError, RoutingContractError, SectionContractError) as exc:
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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
