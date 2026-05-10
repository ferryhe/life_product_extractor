"""Auditable life insurance product extraction toolkit."""

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

__all__ = [
    "ALLOWED_AUTHORITY_LEVELS",
    "ALLOWED_DOCUMENT_ROLES",
    "ALLOWED_JURISDICTIONS",
    "ALLOWED_PRIMARY_CLASSES",
    "ALLOWED_REGION_FAMILIES",
    "ALLOWED_SECONDARY_TAGS",
    "SourceCatalogError",
    "load_source_catalog",
    "validate_source_catalog",
]

__version__ = "0.1.0"
