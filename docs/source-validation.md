# Source validation rules

`examples/sources/manulife_sources.yaml` is the initial source catalog for the Manulife-driven implementation series. The catalog is intentionally metadata-only in PR A: it records candidate official sources, source authority, product taxonomy, and fixture eligibility before later PRs add converted Markdown fixtures.

## Required fields

Every source entry must include:

- `id` — a stable, unique source identifier used by tests and downstream provenance.
- `product_name`
- `region_family`
- `jurisdiction`
- `product_class_primary`
- `product_class_secondary`
- `document_role`
- `authority_level`
- `allowed_as_fixture`
- `fixture_tier`
- `source_url`

## Taxonomy discipline

`product_class_primary` must stay aligned with the research taxonomy:

- `traditional_life`
- `ltc_di`
- `ul_iul`
- `deferred_annuity`
- `immediate_annuity`
- `multi_state`
- `participating_life`
- `other`

Modifiers such as `critical_illness`, `disability`, `long_term_care`, `vitality`, `direct_to_consumer`, or `gic_adjacent` belong in `product_class_secondary`. `unknown_region` is a region-family fallback only; it is never a product class.

## Authority and fixture eligibility

`document_role`, `authority_level`, and `allowed_as_fixture` prevent discovery sources from becoming accidental ground truth. Product pages and official advisor/product guides can become Tier 1 or Tier 2 fixtures. Educational pages, adjacent investment materials, and third-party mirrors default to `allowed_as_fixture: false` and `fixture_tier: 0`.

If a mirror or educational source must be promoted into a fixture, the entry must carry explicit override review metadata:

- `override_rationale`
- `reviewed_by`
- `reviewed_at`

This rule is enforced by tests so later implementation PRs cannot silently weaken the source policy.

## PR B curated fixture contract

PR B adds a deterministic curated-fixture builder driven by committed YAML data under `examples/fixtures/`.

- `examples/fixtures/manulife_fixture_builder.yaml` is the canonical committed builder input.
- `examples/fixtures/manulife_tier1_curated/` is the canonical generated Tier 1 Markdown fixture bundle.
- `schemas/manifest.schema.json` is now the authoritative contract for curated Markdown fixture manifests.

The builder is intentionally offline and deterministic:

- it reads committed snippet lines only
- it joins those snippets with source-catalog metadata from the bundled Manulife catalog
- it writes relative Markdown paths, SHA-256 checksums, and trimming/provenance metadata
- it records paired-source scenarios so later extraction and AI-review PRs can test overlap and contradiction handling without live fetches

Tier 1 curated fixtures must stay small and provenance-aware. If a source is promoted into the committed fixture set, the corresponding source-catalog entry must remain `allowed_as_fixture: true` and `fixture_tier: 1` or higher.
