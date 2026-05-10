"""Auditable life insurance product extraction toolkit."""

from ._version import __version__
from .catalog import (
    ALLOWED_AUTHORITY_LEVELS,
    ALLOWED_DOCUMENT_ROLES,
    ALLOWED_JURISDICTIONS,
    ALLOWED_PRIMARY_CLASSES,
    ALLOWED_REGION_FAMILIES,
    ALLOWED_SECONDARY_TAGS,
    SourceCatalogError,
    load_source_catalog,
    validate_source_catalog,
)
from .fixtures import (
    FixtureContractError,
    build_fixture_bundle,
    build_fixture_bundle_from_paths,
    load_fixture_manifest_document,
    validate_fixture_manifest_document,
)
from .routing import (
    RoutingContractError,
    classify_fixture_manifest,
    classify_fixture_manifest_from_path,
    load_routing_document,
    validate_routing_document,
)

__all__ = [
    "ALLOWED_AUTHORITY_LEVELS",
    "ALLOWED_DOCUMENT_ROLES",
    "ALLOWED_JURISDICTIONS",
    "ALLOWED_PRIMARY_CLASSES",
    "ALLOWED_REGION_FAMILIES",
    "ALLOWED_SECONDARY_TAGS",
    "FixtureContractError",
    "RoutingContractError",
    "SourceCatalogError",
    "build_fixture_bundle",
    "build_fixture_bundle_from_paths",
    "classify_fixture_manifest",
    "classify_fixture_manifest_from_path",
    "load_fixture_manifest_document",
    "load_routing_document",
    "load_source_catalog",
    "validate_routing_document",
    "validate_fixture_manifest_document",
    "validate_source_catalog",
]
