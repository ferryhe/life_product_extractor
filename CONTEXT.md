# Context

## Project Purpose

`life_product_extractor` turns curated life-insurance Markdown source documents plus a manifest into auditable extraction artifacts. The project is not a generic PDF scraper or a free-form LLM summarizer. Its output must be contract-shaped JSON with evidence, validation, AI review, human review routing, and status reporting.

## Domain Vocabulary

- **Manifest**: The run input that lists source Markdown documents and product metadata. It anchors routing and provenance for downstream artifacts.
- **Curated Markdown fixture**: A committed, deterministic Markdown source bundle used for tests and local smoke runs. Fixtures should preserve source metadata, relative paths, and checksums; they should not depend on live fetching.
- **Source catalog**: Metadata about candidate official sources, source authority, fixture eligibility, product taxonomy, and provenance. It prevents weak sources from becoming accidental ground truth.
- **Routing / classification**: The stage that assigns `region_family`, jurisdiction, primary product class, optional secondary classes/tags, confidence, and evidence. Explicit manifest taxonomy should not be overridden by inference unless surfaced for review.
- **Region family**: Coarse jurisdiction grouping used as the first routing axis, such as `north_america`, `uk_ireland`, `europe`, `apac`, or `unknown_region`.
- **Product class**: Coarse product profile used as the second routing axis. Current North America classes are `traditional_life`, `ltc_di`, `ul_iul`, `deferred_annuity`, `immediate_annuity`, `multi_state`, `participating_life`, and `other`.
- **Secondary product class / tag**: A modifier such as `critical_illness`, `disability`, `long_term_care`, `vitality`, `direct_to_consumer`, or `gic_adjacent`. These should not become primary classes without evidence and an explicit design decision.
- **Sectionization**: The deterministic conversion of Markdown documents into structured section records with stable `section_id`, heading hierarchy, line ranges, source quote, provenance, and table artifact hints.
- **Evidence span**: The source-linked quote or section reference that supports a routed or extracted value. Every known extracted field must preserve evidence: source document, section/span, quote, confidence, and review status.
- **Candidate JSON**: The extracted product proposal before validation, AI review, and human decisions. It may contain uncertain or incomplete fields, but uncertainty must be explicit.
- **Validation report**: Deterministic schema/domain checks over candidate or reviewed JSON. Validation is separate from AI review.
- **AI review**: A separate review stage that evaluates candidate evidence and materiality. It may accept, block, or route fields to human review; it is not the same as extraction.
- **Human review bundle**: An interaction layer, currently HTML, that should focus humans on `needs_human_review`, `blocked`, or required unknown fields. JSON artifacts remain authoritative.
- **Review decisions**: Human-provided corrections or confirmations, captured as structured JSON and applied to produce reviewed output.
- **Reviewed JSON**: The post-review product artifact intended for downstream consumption.
- **Status report**: JSON/Markdown summary of extraction, validation, review, and readiness state.
- **Skill pack**: Repo-internal versioned prompt/rule/rubric assets that guide routing, extraction, normalization, AI review, and human review policy. These are project assets, not opaque memory.
- **Skill improvement candidate**: Proposed change derived from recurring review outcomes. It must remain proposed-only until reviewed and backed by regression fixtures.
- **Decrement**: An event, transition, or utilization path that changes in-force exposure, account value, or benefit eligibility, such as death, surrender/lapse, annuitization, critical illness, disability, long-term care, withdrawal, maturity/expiry, or other benefit triggers.
- **Benefit**: A contractual payment, waiver, service, credit, or option value made available under specified conditions. Benefits should be linked to decrements/triggers and preserve calculation, timing, limits, exclusions, and evidence.
- **High materiality field**: A field where incorrect extraction can materially affect actuarial interpretation or review readiness, especially calculation methods, limits/caps, exclusions, termination effects, offsets/reductions, and benefit triggers.

## Project Invariants

- CLI and API must share the same service layer; do not duplicate business logic between interfaces.
- JSON schemas and JSON artifacts are authoritative. HTML review output is only an interaction layer.
- Every known extracted field must preserve evidence, confidence, and review status.
- Unknown, unsupported, contradictory, or not-applicable fields must be explicit; do not silently omit material fields.
- AI review must remain separate from extraction and must route uncertain or high-materiality issues to humans.
- Human corrections must not automatically mutate active skill packs. They should produce proposed improvements plus regression fixtures.
- Product routing is region-first and product-class-second.
- Decrements and benefits are first-class domain concepts in the schema and review process.
- Provider/model/embedding details should not leak into ordinary product-facing API or CLI contracts.
- Source authority and fixture eligibility rules must not be weakened without explicit review.

## External Systems and Interfaces

- **GitHub**: Remote repository is `git@github.com:ferryhe/life_product_extractor.git`; origin/main is the source of truth for new work.
- **CLI**: `life-extract` is the primary agent-friendly production interface.
- **API**: FastAPI wrapper under `life_product_extractor.api`; it must wrap shared services rather than implement separate business logic.
- **Fixtures**: `examples/fixtures/manulife_tier1_curated/` is the current bundled deterministic smoke fixture set.
- **Schemas**: `schemas/` and bundled package resources define authoritative artifact contracts.

## Verification Commands

Run these for documentation-only changes:

```bash
python - <<'PY'
from pathlib import Path
for p in Path('.').rglob('*.md'):
    if '.git' in p.parts:
        continue
    text = p.read_text()
    assert text.endswith('\n'), f'missing trailing newline: {p}'
print('markdown smoke checks passed')
PY
git diff --check
git status --short --branch
```

Run these before code/API/CLI PRs:

```bash
python -m pytest
life-extract --help
life-extract run --help
life-extract status --help
git diff --check
```

For API behavior changes, start the real local API service and exercise key endpoints with HTTP/browser tooling rather than relying only on TestClient.
