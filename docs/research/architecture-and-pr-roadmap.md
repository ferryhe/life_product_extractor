# Architecture and PR Roadmap Research

## 1. Objective

This note converts the initial domain research into an implementation architecture and staged PR plan for `life_product_extractor`. The project must support both CLI and API usage, include an AI review stage that reduces human review volume, and maintain skill packs that can improve extraction/review behavior over time without uncontrolled self-modification.

The architectural principle is simple: every stage should have an explicit file/API contract, every extracted value should carry evidence, and every automated improvement should be test-gated before it changes production behavior.

---

## 2. Target pipeline

Recommended end-to-end pipeline:

```text
manifest.json + Markdown documents
  -> classify/routing
  -> sectionization with evidence spans
  -> candidate extraction
  -> schema/domain validation
  -> AI review
  -> selective human review bundle
  -> review application
  -> reviewed product JSON
  -> status report
  -> skill improvement proposal
```

The important distinction is that AI review is not the same as extraction. Extraction proposes structured product data. AI review independently evaluates whether the proposed data is adequately supported, material, contradictory, or human-review-worthy.

---

## 3. CLI and API boundaries

### 3.1 CLI

The CLI should be the first production interface because it is easy for agents, batch jobs, and CI to call. Suggested CLI commands:

```bash
life-extract classify --manifest input/manifest.json --out out/routing.json
life-extract sectionize --manifest input/manifest.json --out out/sections_structured.jsonl
life-extract extract --manifest input/manifest.json --routing out/routing.json --sections out/sections_structured.jsonl --out out/candidate.json
life-extract validate --candidate out/candidate.json --out out/validation_report.json
life-extract ai-review --candidate out/candidate.json --validation out/validation_report.json --out out/ai_review.json
life-extract review build-html --candidate out/candidate.json --ai-review out/ai_review.json --out out/review.html
life-extract review apply --candidate out/candidate.json --decisions out/review_decisions.json --out out/reviewed.json
life-extract status --reviewed out/reviewed.json --out out/status_report.md
life-extract learn propose --reviewed out/reviewed.json --out out/skill_improvement_candidates.json
```

For MVP usability, also provide a single orchestration command:

```bash
life-extract run --manifest input/manifest.json --out out/
```

### 3.2 API

The API should wrap the same service layer as the CLI. It should not contain separate business logic.

Suggested endpoints:

- `POST /v1/runs/classify`
- `POST /v1/runs/sectionize`
- `POST /v1/runs/extract`
- `POST /v1/runs/validate`
- `POST /v1/runs/ai-review`
- `POST /v1/runs/review-bundle`
- `POST /v1/runs/apply-review`
- `POST /v1/runs/status`
- `POST /v1/runs/learn/propose`

The API should return JSON contract objects and artifact paths/IDs. It should not expose provider/model/embedding complexity to ordinary callers.

---

## 4. Internal module architecture

Recommended package layout:

```text
src/life_product_extractor/
  __init__.py
  cli.py
  api/
    app.py
    routes.py
    schemas.py
  contracts/
    manifest.py
    routing.py
    sections.py
    product.py
    review.py
    status.py
  taxonomy/
    classifier.py
    profiles.py
  sections/
    markdown_parser.py
    evidence.py
  extractors/
    base.py
    rule_based.py
    llm_assisted.py
  validation/
    schema_validator.py
    domain_checks.py
  review/
    ai_reviewer.py
    escalation.py
    html_bundle.py
    apply_decisions.py
  skillpacks/
    loader.py
    validator.py
  learning/
    propose_updates.py
  orchestration/
    run_pipeline.py
```

Recommended repo data layout:

```text
schemas/
  manifest.schema.json
  routing.schema.json
  candidate_product.schema.json
  ai_review.schema.json
  review_decisions.schema.json
  reviewed_product.schema.json
  status_report.schema.json
skills/
  north_america/
    traditional_life/
      extraction_profile.yaml
      ai_review_rubric.md
      normalization_rules.yaml
      human_review_policy.yaml
examples/
  north_america_traditional_life_minimal/
    input/
      manifest.json
      documents/product.md
    expected/
      routing.json
      candidate.json
      ai_review.json
docs/
  research/
  plans/
tests/
```

---

## 5. AI review design

AI review should produce a separate `ai_review.json` artifact. It should include per-field and per-benefit/decrement decisions.

Suggested review output shape:

```json
{
  "run_id": "run_001",
  "reviewer": {
    "type": "ai",
    "skillpack": "north_america/traditional_life",
    "version": "0.1.0"
  },
  "summary": {
    "ai_accepted_count": 18,
    "needs_human_review_count": 4,
    "blocked_count": 1
  },
  "field_reviews": [
    {
      "path": "/benefits/0/calculation_method",
      "decision": "needs_human_review",
      "materiality": "high",
      "reason_code": "formula_references_unparsed_table",
      "rationale": "The quote references a rate table that was not parsed into structured evidence.",
      "required_human_action": "Confirm formula and table scope."
    }
  ]
}
```

The human review HTML should show only escalated fields by default, with an option to inspect AI-accepted fields. This keeps review effort low while preserving auditability.

---

## 6. Skill-pack design

Skill packs should be versioned project assets, not opaque memory. They should guide classification, extraction, normalization, review, and learning.

Minimum v0.1 skill-pack files:

```text
skills/<region>/<product_class>/
  skillpack.yaml
  extraction_profile.yaml
  ai_review_rubric.md
  normalization_rules.yaml
  human_review_policy.yaml
  examples/README.md
```

`skillpack.yaml` should include:

```yaml
id: north_america/traditional_life
version: 0.1.0
region_family: north_america
product_class: traditional_life
schema_profile: traditional_life_v0_1
required_review_thresholds:
  high_materiality_min_confidence: 0.90
  medium_materiality_min_confidence: 0.80
```

Skill updates should be proposed through `skill_improvement_candidates.json`, reviewed, and merged only with regression fixtures.

---

## 7. Proposed PR sequence

### PR 1 — repository architecture, contracts, and research docs

Scope:

- Add project structure skeleton.
- Add `pyproject.toml`, package skeleton, and formatting/test tooling.
- Add initial JSON schemas for manifest, routing, candidate, AI review, review decisions, reviewed product, and status report.
- Keep implementation minimal; focus on contracts and importable package.

Acceptance criteria:

- `python -m pytest` runs, even if only schema/import tests exist.
- `life-extract --help` works.
- Research docs remain under `docs/research/`.

### PR 2 — taxonomy router and skill-pack loader

Scope:

- Implement region/product-class routing contract.
- Add initial North America skill-pack directories.
- Validate skill-pack structure.
- Add fixtures for `traditional_life`, `ul_iul`, and `deferred_annuity` routing.

Acceptance criteria:

- `life-extract classify --manifest ...` writes `routing.json`.
- Router preserves explicit manifest taxonomy over inferred values.
- Unknown/ambiguous products route safely to `other` or `unknown_region`.

### PR 3 — Markdown sectionization and evidence spans

Scope:

- Parse Markdown into stable sections.
- Preserve headings, section IDs, source quotes, and line ranges.
- Output `sections_structured.jsonl`.

Acceptance criteria:

- Section IDs are deterministic.
- Source quotes are escaped safely for later HTML review.
- Fixture tests cover headings, tables, and repeated headings.

### PR 4 — candidate extraction v0.1

Scope:

- Implement deterministic/rule-based extraction first.
- Produce candidate product JSON with taxonomy, decrements, benefits, and evidence.
- Add product-class-specific fixture tests.

Acceptance criteria:

- No field can be marked known without evidence.
- Unknown values are explicit, not omitted silently.
- Benefits link to decrement/trigger IDs where evidence supports the link.

### PR 5 — validation and AI review

Scope:

- Add schema validation and domain checks.
- Implement AI review interface and initial deterministic reviewer stub.
- Add review decisions: `ai_accepted`, `needs_human_review`, `blocked`, `not_applicable`, `unknown`.

Acceptance criteria:

- High-materiality ambiguous fields are escalated.
- AI review output is separate from candidate JSON.
- Tests prove that unsupported fields cannot be auto-accepted.

### PR 6 — selective HTML human review bundle and apply step

Scope:

- Generate static HTML review bundle for escalated fields.
- Export/import `review_decisions.json`.
- Apply human decisions to produce `reviewed.json`.

Acceptance criteria:

- HTML is not used as the authoritative data store.
- `reviewed.json` can only be produced by applying decisions to candidate JSON.
- Source quotes are safely escaped.

### PR 7 — run orchestration, status report, and examples

Scope:

- Add `life-extract run` orchestration command.
- Add `status_report.json` and `status_report.md`.
- Add end-to-end examples.

Acceptance criteria:

- One command can run classify -> sectionize -> extract -> validate -> AI review -> review bundle/status.
- Status clearly reports model-readiness blockers.

### PR 8 — learning loop for skill improvement proposals

Scope:

- Generate `skill_improvement_candidates.json` from reviewed runs.
- Add tests that proposed skill changes are not automatically activated.
- Document maintainer review and regression fixture requirement.

Acceptance criteria:

- Learning proposals include target skillpack, evidence runs, proposed change, and required fixture.
- No automatic mutation of active skill packs occurs.

### PR 9 — API wrapper over service layer

Scope:

- Add FastAPI app wrapping existing service functions.
- Add request/response tests.
- Keep API thin; no duplicate business logic.

Acceptance criteria:

- CLI and API produce equivalent artifacts for the same fixture.
- API hides provider/model details.

---

## 8. Near-term recommendation

Do not start with LLM-heavy extraction. Start with contracts, taxonomy routing, deterministic sectionization, and deterministic review stubs. This creates a stable architecture that later AI components can improve without changing artifact contracts. The first real implementation PR should therefore be contract/skeleton-focused, followed by taxonomy/skill-pack routing, then sectionization, then candidate extraction, then AI review and human review.
