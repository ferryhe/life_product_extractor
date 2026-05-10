from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from . import __version__
from .catalog import SourceCatalogError, load_source_catalog_document, validate_source_catalog_document
from .resources import resource_path


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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    try:
        return int(args.func(args))
    except SourceCatalogError as exc:
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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
