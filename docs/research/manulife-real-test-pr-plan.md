# Manulife Real-Product Test Corpus and PR Plan

## 1. Purpose

This note turns the initial architecture research into a real-data development plan. The goal is to avoid building `life_product_extractor` only against toy examples. Starting from the first implementation PRs, the project should use as many real Manulife product pages and documents as practical, converted to Markdown and referenced through manifests, so the CLI/API, taxonomy router, decrement/benefit schema, AI review, and human review bundle are forced to handle real carrier language.

This plan is intentionally test-first. Each implementation slice should introduce or exercise a small part of the Manulife corpus, run local tests, then run a separate Codex CLI review of the diff before a PR is opened or updated.

---

## 2. Pre-PR Codex Review Gate

For this project and the other project-isolated agents, development must use the following mandatory pre-PR gate:

1. Implement the scoped change on a task branch.
2. Run focused and full local verification for that scope.
3. Run a separate Codex CLI review against the current branch/diff before PR creation or PR update.
4. Accept only technically correct, in-scope Codex findings.
5. Apply fixes and rerun verification.
6. Only then commit/push/open or update the PR.
7. After the remote PR exists, continue the normal remote review loop: fetch checks, PR comments, and inline review comments; judge each comment on merit; fix only confirmed in-scope issues.

Suggested review command shape:

```bash
codex exec "Review the current branch before PR creation. Inspect git diff against origin/main. Focus on correctness, contract drift, missing tests, security/safety, source handling, and scope creep. Return actionable findings only."
```

If Codex CLI is blocked by auth/tooling, the blocker must be recorded in the final report before proceeding.

---

## 3. Manulife source discovery snapshot

This is a planning snapshot from public Manulife Canada pages and public search results. Each source should be revalidated by the source-catalog PR before it becomes a committed fixture. Prefer official `manulife.ca`, `advisor.manulife.ca`, `funds.manulife.ca`, or `manulifeim.com` sources. Third-party mirrored PDFs are useful for discovery but should not become authoritative fixtures unless no official public source is available and the license/terms are acceptable.

Before PR A, the source catalog must use stable routing fields rather than ad hoc labels. Recommended source-catalog fields:

```yaml
product_name: Family Term Life Insurance Plan
region_family: north_america
jurisdiction: CA
product_class_primary: traditional_life
product_class_secondary: [term_life]
document_role: product_marketing_page
authority_level: official_public
allowed_as_fixture: true
fixture_tier: 1
source_url: https://www.manulife.ca/...
```

Allowed `product_class_primary` values should stay aligned with `product-taxonomy-and-skill-map.md`: `traditional_life`, `ltc_di`, `ul_iul`, `deferred_annuity`, `immediate_annuity`, `multi_state`, `participating_life`, and `other`. `unknown_region` is only a `region_family` fallback and must not be used as a product class. Use secondary tags for modifiers such as `term_life`, `critical_illness`, `disability`, `long_term_care`, `vitality`, `simplified_issue`, `guaranteed_issue`, `combination_product`, `educational_context`, `segregated_fund_adjacent`, or `gic_adjacent`.

`document_role`, `authority_level`, and `allowed_as_fixture` are mandatory because a source can be useful for discovery without being valid ground truth. Suggested `authority_level` values are `official_public`, `official_advisor`, `official_investment_affiliate`, `third_party_mirror`, and `unknown`. Suggested `document_role` values are `product_marketing_page`, `client_guide`, `product_guide`, `investment_account_table`, `educational_page`, `mirror_discovery_only`, and `adjacent_context`. Mirror and educational sources default to `allowed_as_fixture: false` unless an explicit override and rationale are reviewed.

### 3.1 Term / traditional life candidates

| Candidate | Primary class | Secondary tags | Source type | URL | Test value |
|---|---|---|---|---|---|
| Family Term Life Insurance Plan | `traditional_life` | `term_life` | official product page | https://www.manulife.ca/personal/insurance/our-products/life-insurance/term-life-insurance/family-term-life.html | Term product identity, death benefit, renewal/conversion/protection language. |
| Family Term with Vitality Plus | `traditional_life` | `term_life`, `vitality` | official product page | https://www.manulife.ca/personal/insurance/our-products/life-insurance/term-life-insurance/vitality-family-term-life.html | Same base term concepts plus Vitality program text that should not pollute core benefit extraction. |
| CoverMe Term Life | `traditional_life` | `term_life`, `direct_to_consumer` | official product page | https://www.manulife.ca/personal/insurance/our-products/life-insurance/term-life-insurance/coverme-term-life.html | Direct-to-consumer wording; useful for simpler page extraction. |
| CoverMe Term 20 Life | `traditional_life` | `term_life`, `direct_to_consumer` | official product page | https://www.manulife.ca/personal/insurance/our-products/life-insurance/term-life-insurance/coverme-term-20-life.html | Term-duration normalization and issue/coverage limits if present. |
| CoverMe Easy Issue Life | `traditional_life` | `term_life`, `simplified_issue`, `direct_to_consumer` | official product page | https://www.manulife.ca/personal/insurance/our-products/life-insurance/term-life-insurance/coverme-easy-issue-life.html | Simplified underwriting language and exclusions. |

### 3.2 Permanent / participating / UL candidates

| Candidate | Primary class | Secondary tags | Source type | URL | Test value |
|---|---|---|---|---|---|
| Manulife Universal Life | `ul_iul` | `universal_life` | official product page | https://www.manulife.ca/personal/insurance/our-products/life-insurance/permanent-life-insurance/manulife-universal-life.html | Account value, charges, investment/account options, death benefit options. |
| Manulife UL with Vitality Plus | `ul_iul` | `universal_life`, `vitality` | official product page | https://www.manulife.ca/personal/insurance/our-products/life-insurance/permanent-life-insurance/manulife-universal-life-vitality.html | UL plus program overlay; tests secondary tags. |
| Manulife UL investment account PDF/API output | `ul_iul` | `investment_account_table` | official PDF-like source | https://funds.manulife.ca/ul/api/pdf/ma808-ul100-en-us-904 | Investment-account/table extraction and table-artifact handling. |
| Manulife Par Whole Life | `participating_life` | `whole_life`, `dividend` | official product page | https://www.manulife.ca/personal/insurance/our-products/life-insurance/permanent-life-insurance/manulife-par-whole-life.html | Participating/dividend language; guaranteed vs non-guaranteed distinction. |
| Manulife Par with Vitality Plus | `participating_life` | `whole_life`, `dividend`, `vitality` | official product page | https://www.manulife.ca/personal/insurance/our-products/life-insurance/permanent-life-insurance/manulife-par-vitality.html | Participating life plus wellness-program overlay. |
| Manulife Guaranteed Issue Life | `traditional_life` | `permanent_life`, `guaranteed_issue` | official product page | https://www.manulife.ca/personal/insurance/our-products/life-insurance/permanent-life-insurance/manulife-guaranteed-issue-life.html | Guaranteed-issue underwriting, graded/limited benefits if present. |
| CoverMe Guaranteed Issue Life | `traditional_life` | `permanent_life`, `guaranteed_issue`, `direct_to_consumer` | official product page | https://www.manulife.ca/personal/insurance/our-products/life-insurance/permanent-life-insurance/coverme-guaranteed-issue-life.html | Direct-to-consumer guaranteed issue language. |
| Manulife Par Client Guide | `participating_life` | `whole_life`, `dividend` | discovered PDF mirror; official copy needed | https://cdn.heyzine.com/flip-book/pdf/13b7fb31ce140b350aec2783420072cb686f1599.pdf | Rich participating-life brochure. Use only if official source cannot be found and terms allow. |

### 3.3 CI / LTC / DI / combination candidates

| Candidate | Primary class | Secondary tags | Source type | URL | Test value |
|---|---|---|---|---|---|
| Manulife Synergy combination insurance | `traditional_life` | `combination_product`, `critical_illness`, `disability` | official product page | https://www.manulife.ca/personal/insurance/our-products/manulife-synergy-combination-insurance.html | Combined life, disability, and critical illness responsibilities; strong test for decrement/benefit linking. |
| Lifecheque critical illness insurance | `traditional_life` | `critical_illness` | official product page | https://www.manulife.ca/personal/insurance/our-products/health-insurance/critical-illness/lifecheque.html | CI trigger definitions, covered conditions, survival/waiting-period language. |
| Lifecheque Basic | `traditional_life` | `critical_illness`, `simplified_issue` | official product page | https://www.manulife.ca/personal/insurance/our-products/health-insurance/critical-illness/lifecheque-basic.html | Simplified CI product variant. |
| CoverMe critical illness | `traditional_life` | `critical_illness`, `direct_to_consumer` | official product page | https://www.manulife.ca/personal/insurance/our-products/health-insurance/critical-illness/coverme.html | Consumer-facing CI wording. |
| LivingCare product guide | `ltc_di` | `long_term_care` | official PDF | https://www.manulife.ca/content/dam/manulife-advisor-portal/documents/en/marketing-materials/insurance/livingcare/manulife-livingcare-product-guide.pdf | Long-term-care triggers, benefit periods, eligibility, elimination periods. |
| Proguard Series disability insurance client guide | `ltc_di` | `disability` | official advisor PDF | https://advisor.manulife.ca/content/dam/manulife-advisor-portal/documents/en/marketing-materials/insurance/proguard-series/manulife-insurance-disability-insurance-client-guidee.pdf | Disability definitions, elimination periods, benefit amount/duration, riders. |
| Personal Accident Insurance | `ltc_di` | `accident`, `disability_adjacent` | official product page | https://www.manulife.ca/personal/insurance/our-products/health-insurance/disability/personal-accident-insurance.html | Accident/disability-adjacent product with different trigger wording. |
| Lifecheque brochure / definition PDFs | `traditional_life` | `critical_illness`, `mirror_discovery_only` | discovered mirrors; official copy needed | multiple discovered third-party mirrors | Rich CI condition definitions. Use only after source validation. |

### 3.4 Annuity / retirement-income candidates

| Candidate | Primary class | Secondary tags | Source type | URL | Test value |
|---|---|---|---|---|---|
| Annuities for retirement planning | `immediate_annuity` | `educational_context`, `deferred_annuity_adjacent` | official educational page | https://www.manulife.ca/personal/plan-and-learn/healthy-finances/saving/annuities-for-retirement-planning.html | Basic annuity concepts; useful as discovery context but not product ground truth. |
| Manulife annuities brochure | `immediate_annuity` | `mirror_discovery_only` | discovered PDF mirror; official copy needed | https://lifeannuities.com/brochures/manulife-annuity-brochure.pdf | Payout options and annuity income language if official/public rights are acceptable. |
| Manulife Investments Guaranteed Interest Contract product guide | `deferred_annuity` | `gic_adjacent`, `investment_contract` | official PDF | https://www.manulifeim.com/content/dam/mim-ca/landing-page/product/pdf/inv_gic_productguide.pdf | Guaranteed-interest/investment contract language; not necessarily an insurance annuity but useful for table/guarantee parsing. |
| Insurance Investments: the facts | `deferred_annuity` | `segregated_fund_adjacent`, `educational_context` | official PDF | https://www.manulifeim.com/content/dam/mim-ca/landing-page/product/pdf/insurance-investments-the-facts-en.pdf | Insurance-investment framing and deferred accumulation language. |

---

## 4. Fixture tiers

Do not put every source into every test immediately. Use tiers.

### Tier 0 — source catalog only

Store metadata only: product name, product class, URL, source type, expected document kind, priority, and validation status. No large fixture snapshots yet.

### Tier 1 — small Markdown fixtures

Convert selected official product pages into small deterministic Markdown fixtures. Do not silently hand-edit away provenance. Each Tier 1 fixture should keep either:

1. a raw source snapshot plus a deterministic normalized Markdown file; or
2. a normalized Markdown file plus a manifest-level trimming map that records removed line ranges/DOM selectors and original source offsets.

This allows later sectionization tests to prove source provenance, line ranges, and source quotes even when navigation/footer noise is removed. These fixtures should be committed only when they are stable, small, and permitted by the source policy.

Initial Tier 1 set:

1. Family Term Life
2. Manulife Universal Life
3. Manulife Par Whole Life
4. Lifecheque
5. Manulife Synergy
6. LivingCare product guide excerpt
7. Proguard Series product guide excerpt

### Tier 2 — full-document regression fixtures

Store downloaded or converted full documents only if size, licensing, and update stability are acceptable. Prefer checksummed external source manifests over committing large PDFs.

### Tier 3 — live-source smoke

Optional non-deterministic smoke that fetches current Manulife pages in a temporary directory, converts them to Markdown, and compares high-level invariants. This should not be required for normal CI unless network is explicitly allowed.

---

## 5. Revised implementation PR sequence

This sequence incorporates the real Manulife test corpus. It supersedes the purely abstract implementation order where needed.

### PR A — project skeleton, contracts, and source catalog

Scope:

- Add Python package skeleton, CLI placeholder, and base schemas.
- Add `examples/sources/manulife_sources.yaml` with the Tier 0 source catalog above.
- Add tests that validate source catalog shape and taxonomy keys.
- Add local docs describing source validation rules.

Acceptance criteria:

- `python -m pytest` passes.
- `life-extract --help` works.
- Source catalog entries include region, jurisdiction, `product_class_primary`, `product_class_secondary`, URL, `document_role`, `authority_level`, `allowed_as_fixture`, and intended fixture tier.
- Tests reject invalid primary-class values and unknown secondary tags unless explicitly marked experimental.
- Tests prove mirror or educational sources cannot be promoted to Tier 1 authoritative fixtures without `allowed_as_fixture: true` and an override rationale.
- Pre-PR Codex review is run and accepted findings are resolved before PR creation.

### PR B — fixture builder and Markdown fixture contract

Scope:

- Add manifest schema for local Markdown fixtures.
- Add a deterministic fixture-builder utility that can create manifests from local Markdown files while preserving raw/normalized provenance.
- Add Tier 1 curated Markdown snapshots for Family Term, Manulife UL, Manulife Par, Lifecheque, Synergy, LivingCare excerpt, and Proguard excerpt.
- Add at least one paired same-product fixture scenario, preferably Manulife UL product page plus investment-account/table source, or Manulife Par product page plus an official client/product guide if available. At least one paired scenario must be labelled `potentially_contradictory` or `known_overlap`; a purely complementary pair is not sufficient for this acceptance gate.

Acceptance criteria:

- No test depends on live network.
- Each fixture has source URL, retrieval date, source type, primary class, secondary tags, `document_role`, `authority_level`, checksum, and provenance/trimming metadata.
- Fixtures are small and reviewed for copyright-sensitive over-copying; large PDFs stay as external references unless explicitly allowed.
- Paired-source fixture manifests identify whether sources are complementary, overlapping, or potentially contradictory.
- At least one paired-source fixture is explicitly `known_overlap` or `potentially_contradictory` so PR G has a real disagreement/escalation regression case.

### PR C — taxonomy router against Manulife fixtures

Scope:

- Implement `life-extract classify`.
- Route the Manulife fixture set into stable `product_class_primary` values and secondary tags such as `critical_illness`, `disability`, `long_term_care`, `vitality`, `combination_product`, `educational_context`, `gic_adjacent`, or `segregated_fund_adjacent`.
- Preserve explicit manifest taxonomy over inferred taxonomy.

Acceptance criteria:

- All Tier 1 fixtures produce deterministic `routing.json`.
- Synergy routes as composite/multi-benefit rather than a single simple life product.
- Ambiguous annuity/investment sources are marked with safe uncertainty or adjacent-context tags instead of forced authoritative classification.
- Pure CI pages route to an allowed primary class plus `critical_illness` secondary tag until the taxonomy intentionally introduces a separate CI primary class.

### PR D — Markdown sectionization against real Manulife pages/PDF excerpts

Scope:

- Implement `sectionize`.
- Preserve heading hierarchy, line ranges, tables as table artifacts, and source quotes.
- Use Manulife fixtures that include navigation noise, benefit headings, tables, repeated sections, raw/normalized provenance, and paired overlapping same-product sources.

Acceptance criteria:

- Section IDs are deterministic.
- Navigation/footer noise is either filtered or labelled low-value.
- Source quotes are HTML-escaped for later review bundles.
- Real Manulife fixtures expose no absolute local paths in output.

### PR E — candidate extraction v0.1 for traditional life + participating life + UL

Scope:

- Implement first deterministic extraction rules for product identity, taxonomy, decrements, and core benefits.
- Use Family Term, Manulife Par, and Manulife UL fixtures.

Acceptance criteria:

- Death benefit, surrender/lapse, account-value/dividend concepts are separated where applicable.
- UL account value/crediting text is captured as structured evidence or table artifact, not hallucinated formulas.
- Participating dividend text is marked non-guaranteed when evidence supports that wording.

### PR F — candidate extraction v0.1 for CI / LTC / DI / Synergy

Scope:

- Extend decrement/benefit extraction to critical illness, disability, and long-term care triggers.
- Use Lifecheque, LivingCare, Proguard, and Synergy fixtures.

Acceptance criteria:

- CI, LTC, and DI triggers are first-class decrement/trigger objects.
- Synergy produces linked life/CI/DI benefits rather than one flattened marketing description.
- Elimination/waiting periods and benefit periods are captured as evidence-backed fields or explicit unknowns.

### PR G — validation and AI review using Manulife high-materiality cases

Scope:

- Implement schema validation and deterministic AI-review stub/interface.
- Add high-materiality review rules for benefit formula, caps, exclusions, termination effects, account-value formulas, and jurisdiction/product ambiguity.

Acceptance criteria:

- Unsupported Manulife fixture fields cannot be auto-accepted.
- Table-referenced formulas are escalated unless parsed evidence exists.
- Paired same-product Manulife sources with overlapping benefit/account language produce either reconciled evidence links or `needs_human_review`; the system must not silently prefer one source.
- Synergy composite responsibilities are escalated when trigger/benefit links are incomplete.

### PR H — selective HTML human review and apply step

Scope:

- Generate static HTML review bundle focused on escalated Manulife fields.
- Export/import `review_decisions.json`.
- Apply decisions to produce `reviewed.json`.

Acceptance criteria:

- HTML is never authoritative; reviewed JSON is produced only by applying decisions.
- Review UI defaults to escalated fields but can inspect AI-accepted fields.
- Source quotes are escaped and no remote scripts are loaded.

### PR I — end-to-end Manulife run and status report

Scope:

- Add `life-extract run` orchestration.
- Add status reports for all Tier 1 fixtures.
- Add model-readiness status by product class.

Acceptance criteria:

- One command runs classify -> sectionize -> extract -> validate -> AI review -> review bundle/status on all Tier 1 Manulife fixtures.
- Status report lists blockers by product and materiality.
- Runtime artifacts use stable relative names and do not expose local absolute paths.

### PR J — skill improvement proposal loop

Scope:

- Add `learn propose` against reviewed Manulife runs.
- Generate test-gated skill improvement candidates.

Acceptance criteria:

- Proposed skill changes include target skill pack, observed pattern, evidence runs, proposed change, and required regression fixture.
- No active skill pack is automatically mutated.
- A sample Manulife correction produces a proposed update and a test fixture requirement.

### PR K — API wrapper over the shared service layer

Scope:

- Add FastAPI wrapper around the same service functions used by CLI.
- Add API tests using Manulife fixture manifests.

Acceptance criteria:

- API and CLI produce equivalent artifacts for the same fixture.
- API hides provider/model configuration details.
- Real local API service is started and key endpoints are exercised before PR creation.

---

## 6. Immediate next implementation recommendation

Start with PR A only after PR #1 lands or is updated to include this plan. PR A should not attempt extraction. It should establish the package skeleton, JSON schema contracts, and `manulife_sources.yaml`. The Manulife source catalog will keep later work grounded and prevent abstract schemas from drifting away from real carrier documents.

The first development PR should therefore be:

```text
feat: add package skeleton and Manulife source catalog
```

with tests for:

- schema file loading;
- source catalog validation;
- taxonomy keys matching the research taxonomy;
- `life-extract --help`.

Only after that should PR B add local Markdown fixtures and fixture manifests.
