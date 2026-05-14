# Agent Triage Labels

Use these labels when converting work into GitHub Issues, markdown backlog items, or PR plans. Labels should clarify priority, scope, verification, and human-decision boundaries.

## Priority

- `priority:p0` — urgent correctness, data integrity, security, or production-blocking issue.
- `priority:p1` — important next roadmap work or regression with clear user/operator impact.
- `priority:p2` — useful improvement that can wait behind current roadmap slices.
- `priority:p3` — cleanup, polish, or exploratory work with no immediate delivery pressure.

## Work Type

- `type:feature` — new user/operator-visible behavior.
- `type:bug` — incorrect behavior against current contracts.
- `type:docs` — documentation-only change.
- `type:test` — test coverage, fixtures, smoke harnesses, or verification infrastructure.
- `type:refactor` — internal structure change with no intended behavior change.
- `type:research` — investigation or plan before implementation.
- `type:ops` — packaging, release, CI, or operational workflow.

## Domain Area

- `area:routing` — taxonomy, source classification, region/product-class handling.
- `area:sectionization` — Markdown parsing, section IDs, evidence spans, table artifacts.
- `area:extraction` — candidate JSON generation and field extraction.
- `area:validation` — schema and deterministic domain validation.
- `area:ai-review` — review rubrics, materiality, escalation decisions.
- `area:human-review` — review bundle, review decisions, reviewed JSON application.
- `area:status` — status reports and readiness summaries.
- `area:learning` — skill improvement candidates and promotion workflow.
- `area:api` — FastAPI wrapper and HTTP contracts.
- `area:cli` — `life-extract` command behavior and CLI UX.
- `area:schemas` — JSON schemas and bundled schema resources.
- `area:fixtures` — source catalog, curated fixtures, examples, and provenance.
- `area:agents` — AGENTS/CONTEXT/ADR/workflow docs for AI-assisted development.

## Execution Mode

- `mode:afk` — agent can complete with existing repo context and deterministic verification.
- `mode:hitl` — needs user/business/maintainer decision before or during implementation.
- `mode:mixed` — AFK implementation is possible after a clearly named HITL decision.

## Risk / Contract Impact

- `risk:public-contract` — changes schemas, CLI args, API endpoints, artifact names, or output semantics.
- `risk:source-authority` — changes source catalog authority or fixture eligibility policy.
- `risk:high-materiality` — affects benefit calculations, exclusions, limits/caps, triggers, or termination effects.
- `risk:provider-leakage` — risks exposing provider/model/embedding complexity through product-facing contracts.
- `risk:low` — local docs/tests/internal implementation only.

## Verification Labels

- `verify:pytest` — requires `python -m pytest`.
- `verify:cli-smoke` — requires `life-extract --help` or a representative CLI command.
- `verify:pipeline-smoke` — requires bundled fixture pipeline run.
- `verify:api-service-smoke` — requires real local API service + HTTP requests.
- `verify:markdown-smoke` — requires markdown trailing-newline check and `git diff --check`.
- `verify:schema-contract` — requires schema validation or contract fixtures.

## Status Labels

- `status:backlog` — accepted candidate, not started.
- `status:planned` — scoped and ready for branch/PR work.
- `status:in-progress` — active local branch or PR exists.
- `status:blocked` — waiting on named blocker.
- `status:needs-review` — implementation complete, awaiting review/checks.
- `status:done` — merged or otherwise completed.
