# Product Taxonomy and Skill Map Research

## 1. Purpose

This note proposes the first product taxonomy for `life_product_extractor` and explains how that taxonomy should drive both extraction logic and reusable AI review skills. The key design objective is not to create an academically exhaustive insurance ontology. The objective is to create a stable, coarse taxonomy that is useful for agentic extraction, selective human review, and later programmatic improvement.

The project should treat product taxonomy as a routing layer. It tells the CLI/API which schema profile, extraction prompts/rules, validation checks, AI review rubric, and human review bundle to use. It should not become a deeply nested product-management catalog. Over-classification will create unnecessary maintenance cost and reduce reusability.

---

## 2. Region-first taxonomy

Insurance contracts and marketing brochures are written differently across jurisdictions. Even when two products share the same actuarial concept, the disclosure conventions, statutory language, tax terminology, rider names, guarantee wording, and exclusions may differ. Therefore, the first taxonomy axis should be region/jurisdiction family.

Recommended top-level region families:

| Region family | Suggested key | Rationale |
|---|---:|---|
| North America | `north_america` | Initial target. Similar enough to share many life/annuity concepts; still allow U.S./Canada subprofiles later. |
| United Kingdom / Ireland | `uk_ireland` | Different policy language, tax wrappers, with-profits conventions, pension/annuity framing. |
| Continental Europe | `europe` | Often different guaranteed-rate, unit-linked, and regulatory disclosure structure. Keep coarse until real examples accumulate. |
| Asia-Pacific | `apac` | Broad category, but useful because products often combine savings, protection, participating, CI, and medical riders differently. |
| Other / unknown | `unknown_region` | Safe fallback when manifest/source does not support routing. |

Implementation implication: every extraction run should include `region_family` in the manifest or infer it conservatively with low confidence. Inference should never override an explicit manifest value unless the AI reviewer flags a contradiction.

---

## 3. North America product classes

For the first version, use a compact North America product-class taxonomy. The names below are intended to become stable profile keys used by CLI/API arguments, schema profiles, skill names, and test fixtures.

| Product class | Suggested key | Includes | Why separate |
|---|---:|---|---|
| Traditional life | `traditional_life` | Term life, whole life, non-par UL-like simple life, CI attached to life where contract language is protection-first | Core death-benefit and premium/renewal/conversion/exclusion language is different from investment-style policies. CI can be included when presented as rider/benefit under life protection. |
| LTC / DI | `ltc_di` | Long-term care, disability income, waiver/disability-style living benefits | Claims triggers and benefit period/elimination-period language differ materially from mortality-only life. |
| UL / IUL | `ul_iul` | Universal life, indexed universal life, flexible premium adjustable life, account-value products | Requires account value, charges, interest crediting, index strategy, lapse/no-lapse, loan/withdrawal concepts. |
| Deferred annuity | `deferred_annuity` | Fixed deferred, fixed indexed, variable deferred where supported later | Accumulation phase, surrender charges, annuitization options, GMxB riders, and tax language differ from life. |
| Immediate annuity | `immediate_annuity` | SPIA, immediate income annuity, payout annuity | Benefit is payout stream; decrement/exposure framing differs from deferred annuity. |
| Multi-state / filing wrapper | `multi_state` | Product packets containing state variations, endorsements, jurisdiction-specific riders | Must preserve state-specific variants and avoid collapsing mutually exclusive state language into one product field. |
| Participating life | `participating_life` | Participating whole life, dividend-paying life, with dividend options | Dividend scale, non-guaranteed elements, paid-up additions, dividend options need separate handling. |
| Other / unknown | `other` | Products not fitting above or insufficient evidence | Avoid false precision; route to heavier AI/human review. |

The taxonomy intentionally overlaps at the real-world edge cases. For example, participating whole life is also traditional life; a CI rider may appear under traditional life or living benefits; an indexed annuity may share concepts with IUL. The profile router should support both a primary class and secondary tags.

Recommended JSON routing fields:

```json
{
  "region_family": "north_america",
  "jurisdiction": "US",
  "product_class_primary": "traditional_life",
  "product_class_secondary": ["ci_rider"],
  "routing_confidence": 0.82,
  "routing_evidence": [
    {
      "source_section_id": "sec_004",
      "source_quote": "Term Life Insurance with optional Critical Illness Benefit Rider"
    }
  ]
}
```

---

## 4. Skill organization

The project should use “skill” in two related but separate senses:

1. **Extractor/reviewer skill pack inside this repo**: versioned prompt/rule/rubric assets that the CLI/API can load at runtime.
2. **Hermes/agent skill generated from experience**: procedural instructions for future agents when a product class repeatedly causes issues.

The repo-internal skill pack should be data/config first, not free-form agent memory. A suggested path layout:

```text
skills/
  north_america/
    traditional_life/
      extraction_profile.yaml
      ai_review_rubric.md
      normalization_rules.yaml
      human_review_policy.yaml
      examples/
    ltc_di/
    ul_iul/
    deferred_annuity/
    immediate_annuity/
    multi_state/
    participating_life/
  unknown_region/
    other/
```

Each skill pack should define:

- `schema_profile`: which fields are expected and which are optional.
- `section_hints`: headings and phrases likely to identify relevant source sections.
- `field_rules`: extraction constraints for each field.
- `normalization_rules`: unit, amount, duration, age, date, and option normalization.
- `ai_review_rubric`: how AI decides accepted / needs human / blocked.
- `human_review_policy`: which uncertainty types must be escalated.
- `negative_examples`: common hallucinations or invalid inferences.
- `improvement_notes`: structured output from post-review learning, subject to maintainer approval before promotion into rules.

---

## 5. AI review and skill improvement loop

The user requirement is that AI should review extraction results first, route only uncertain cases to humans, and then use outcomes to improve both program behavior and agent skills. This requires a controlled feedback loop.

Recommended review states:

| State | Meaning | Human required? |
|---|---|---:|
| `ai_accepted` | Field is supported by direct source quote, passes schema and domain checks, and matches profile rubric. | No by default. |
| `needs_human_review` | Field has ambiguous wording, multiple candidate values, weak evidence, missing normalization, or material model impact. | Yes. |
| `blocked` | Field is unsupported, contradictory, impossible to normalize, or violates schema. | Yes before use. |
| `not_applicable` | Field is not relevant for this product profile and evidence supports omission. | No, but visible in status. |
| `unknown` | No reliable evidence found. | Human only if required by model-readiness policy. |

Skill improvement should be event-driven but gated:

1. Extraction produces `candidate.json` with evidence and confidence.
2. AI reviewer produces `ai_review.json` with per-field decision, rationale, and escalation reason.
3. Human reviewer only sees fields marked `needs_human_review`, `blocked`, or required unknowns.
4. Human decisions produce `review_decisions.json`.
5. A learning job summarizes recurring corrections into `skill_improvement_candidates.json`.
6. Maintainer/AI review decides whether to promote candidates into repo skill packs.
7. Tests are added before a promoted skill change is accepted.

Important guardrail: human corrections should not automatically rewrite extraction rules. They should produce proposed changes plus regression fixtures. Otherwise the system may overfit one carrier’s language or one jurisdiction’s contract style.

---

## 6. Recommended architecture impact

The CLI/API should expose taxonomy and skill routing explicitly.

Suggested CLI shape:

```bash
life-extract classify --manifest input/manifest.json --out out/routing.json
life-extract extract --manifest input/manifest.json --routing out/routing.json --out out/candidate.json
life-extract ai-review --candidate out/candidate.json --out out/ai_review.json
life-extract review build-html --candidate out/candidate.json --ai-review out/ai_review.json --out out/review.html
life-extract review apply --candidate out/candidate.json --decisions out/review_decisions.json --out out/reviewed.json
life-extract learn propose-skill-updates --reviewed out/reviewed.json --out out/skill_improvement_candidates.json
```

Suggested API resources:

- `POST /runs/classify`
- `POST /runs/extract`
- `POST /runs/ai-review`
- `POST /runs/review-bundle`
- `POST /runs/apply-review`
- `POST /runs/propose-skill-updates`

The API should be machine-first and deterministic in contract. It can call LLM providers internally, but provider/model details should not leak into the product-facing interface.

---

## 7. Open questions for later PRs

1. Should `traditional_life` and `participating_life` share a base profile with additive dividend fields, or should participating life be fully separate from the start?
2. Should CI be a secondary tag under `traditional_life`, or a separate product class once enough examples exist?
3. How should multi-state packets represent mutually exclusive state variants in reviewed JSON?
4. Should `region_family` be mandatory in the manifest for production runs, with inference allowed only in exploratory mode?
5. What minimum AI review confidence is sufficient for `ai_accepted`, and should thresholds differ by field materiality?

---

## 8. Initial recommendation

Start with region-first, product-class-second routing. Implement North America profiles first, using the seven coarse product classes above plus `other`. Store repo-internal skill packs under `skills/<region_family>/<product_class>/`. Keep skill improvement as a proposed, test-gated workflow rather than automatic rule mutation. This satisfies the requirement to reduce human review while preserving auditability and avoiding uncontrolled self-modification.
