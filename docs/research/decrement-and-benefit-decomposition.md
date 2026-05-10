# Decrement and Benefit Decomposition Research

## 1. Purpose

This note studies how `life_product_extractor` should decompose insurance products for actuarial and review use. The user’s proposed split is the right starting point: product understanding should be organized around (1) decrements, meaning events or transitions that reduce or change policy exposure/value, and (2) benefits, meaning obligations paid or provided by the insurer, including how they are triggered and calculated.

The extraction system should not merely collect marketing labels such as “death benefit” or “income benefit.” It should identify the conditions under which a benefit is payable, the calculation base, the timing, limits, exclusions, and the decrement/benefit interactions. This is essential because downstream actuarial modeling needs event-driven product semantics, not just descriptive text.

---

## 2. Core concepts

### 2.1 Decrement

A decrement is any event, state transition, or utilization path that changes the active in-force exposure or account value path. In classic actuarial modeling this often means death, lapse/surrender, disability, morbidity, withdrawal, annuitization, or maturity. In this project, the definition should be broad enough to include living-benefit triggers and policyholder options.

Recommended first decrement categories:

| Category | Suggested key | Meaning |
|---|---:|---|
| Death | `death` | Insured dies; can trigger death benefit, terminate policy, or reduce account exposure. |
| Surrender / lapse | `surrender_lapse` | Policyholder terminates, stops paying, or policy lapses due to insufficient value/premium. |
| Annuitization / income start | `annuitization` | Contract converts from accumulation or deferred state into payout state. |
| Critical illness | `critical_illness` | Covered diagnosis/event triggers lump-sum or acceleration benefit. |
| Disability / income loss | `disability` | Disability event triggers waiver, income benefit, or DI payments. |
| Long-term care / care need | `long_term_care` | ADL/cognitive impairment/care eligibility triggers LTC benefit. |
| Withdrawal / partial surrender | `withdrawal` | Policyholder removes value without full termination; may reduce benefits/value. |
| Maturity / expiry | `maturity_expiry` | Contract reaches maturity, term expiry, or end of benefit period. |
| Other benefit trigger | `other_benefit` | Product-specific covered event not captured above. |

### 2.2 Benefit

A benefit is a contractual payment, waiver, service, credit, or option value made available under specified conditions. It should be modeled as a structured object connected to one or more decrement/trigger categories.

Recommended first benefit categories:

| Category | Suggested key | Examples |
|---|---:|---|
| Death benefit | `death_benefit` | Level face amount, increasing death benefit, return of premium, account value plus face amount. |
| Living benefit / CI | `critical_illness_benefit` | Lump-sum CI payment, accelerated death benefit. |
| Disability benefit | `disability_benefit` | DI monthly income, waiver of premium, disability waiver of monthly deduction. |
| LTC benefit | `ltc_benefit` | Monthly reimbursement/indemnity, acceleration/extension of benefits. |
| Surrender benefit | `surrender_benefit` | Cash surrender value, surrender value less charge. |
| Maturity benefit | `maturity_benefit` | Endowment/maturity value, return of premium. |
| Income/annuity benefit | `annuity_income_benefit` | Life income, period certain, joint survivor, guaranteed withdrawal/income. |
| Account value / crediting benefit | `account_value_crediting` | Guaranteed interest, index credit, dividend/PUA value. |
| Rider option / conversion benefit | `rider_option_benefit` | Conversion privilege, guaranteed insurability, paid-up option. |
| Other benefit | `other_benefit` | Product-specific benefit not yet classified. |

---

## 3. Proposed data model

The product schema should separate decrement definitions from benefit definitions, then link them through trigger/eligibility references. This avoids duplicating event logic across many benefit fields.

Suggested top-level structure:

```json
{
  "product_identity": {},
  "taxonomy": {},
  "decrements": [
    {
      "id": "dec_death_001",
      "type": "death",
      "covered_person": "primary_insured",
      "trigger_definition": {
        "value": "Death of the insured while the policy is in force",
        "source_quote": "If the insured dies while this policy is in force...",
        "confidence": 0.91,
        "review_status": "ai_accepted"
      },
      "termination_effect": "policy_terminates",
      "interactions": ["ben_death_001"]
    }
  ],
  "benefits": [
    {
      "id": "ben_death_001",
      "type": "death_benefit",
      "trigger_decrement_ids": ["dec_death_001"],
      "calculation_method": {
        "kind": "face_amount",
        "formula_text": "face amount less outstanding policy debt",
        "source_quote": "We will pay the face amount minus any policy debt...",
        "confidence": 0.86,
        "review_status": "needs_human_review"
      },
      "payment_timing": {},
      "limits": [],
      "exclusions": [],
      "evidence": []
    }
  ]
}
```

This structure should be applied consistently across product types. A deferred annuity may have `annuitization`, `withdrawal`, `death`, and `surrender_lapse` decrements; a traditional life product may have `death`, `surrender_lapse`, `critical_illness`, and `maturity_expiry` decrements; an LTC/DI product may emphasize morbidity/disability benefit triggers.

---

## 4. Benefit extraction dimensions

Every benefit should be extracted along several dimensions. These are more useful than a single free-text field.

| Dimension | Purpose | Review importance |
|---|---|---:|
| `benefit_type` | Identifies what obligation is being described. | High |
| `trigger_decrement_ids` | Links benefit to event/state transition. | High |
| `eligibility_conditions` | Defines who/when qualifies. | High |
| `calculation_method` | Defines amount/formula/basis. | Very high |
| `payment_form` | Lump sum, monthly income, reimbursement, account credit, waiver. | High |
| `payment_timing` | When benefit starts, waiting period, proof requirements, settlement timing. | Medium-high |
| `duration_or_period` | Benefit period, period certain, lifetime, term expiry. | High for annuity/LTC/DI |
| `limits_and_caps` | Maximum benefit, percentages, aggregate limits. | Very high |
| `offsets_and_reductions` | Policy debt, prior withdrawals, acceleration effects, other insurance offsets. | Very high |
| `exclusions` | When the benefit is not payable. | Very high |
| `termination_effect` | Whether payment ends policy, reduces face, changes premium, etc. | Very high |
| `evidence` | Source section/quote for audit. | Required |

The AI reviewer should treat calculation methods, limits/caps, exclusions, and termination effects as high materiality. These should require stronger evidence and lower tolerance for ambiguity than product descriptions or marketing labels.

---

## 5. Decrement/benefit interaction patterns by product class

### 5.1 Traditional life

Common decrements:

- `death`
- `surrender_lapse`
- `maturity_expiry` for term expiry/endowment-like products
- `critical_illness` when CI rider or accelerated benefit exists
- `disability` for waiver of premium or disability rider

Common benefits:

- `death_benefit`
- `surrender_benefit` for permanent products
- `critical_illness_benefit` when applicable
- `disability_benefit` or waiver benefit
- `rider_option_benefit` for conversion/guaranteed insurability

Design note: term conversion is not a benefit payment, but it is a valuable contractual option. It should be modeled as `rider_option_benefit` or `policy_option` linked to `maturity_expiry`/term period constraints.

### 5.2 LTC / DI

Common decrements/triggers:

- `long_term_care`
- `disability`
- `death`
- `surrender_lapse`
- `maturity_expiry` / benefit-period exhaustion

Common benefits:

- `ltc_benefit`
- `disability_benefit`
- `waiver_of_premium`
- `return_of_premium` or nonforfeiture benefits where present

Design note: eligibility triggers may involve ADLs, cognitive impairment, physician certification, elimination periods, own occupation / any occupation definitions, or recurrent disability. These should be structured rather than stored as one prose paragraph.

### 5.3 UL / IUL

Common decrements:

- `death`
- `surrender_lapse`
- `withdrawal`
- `loan` (not a decrement in the same sense, but affects account value and benefit)
- `maturity_expiry`

Common benefits:

- `death_benefit`
- `account_value_crediting`
- `surrender_benefit`
- `loan_withdrawal_option`
- `no_lapse_guarantee` where present

Design note: account value, index crediting, cost of insurance, charges, and loans interact with lapse and death benefit. The first version should capture these as separate structured sections; it should not attempt to project values unless rates/tables are validated.

### 5.4 Deferred annuity

Common decrements/events:

- `death`
- `surrender_lapse`
- `withdrawal`
- `annuitization`
- `maturity_expiry`

Common benefits:

- `account_value_crediting`
- `surrender_benefit`
- `death_benefit`
- `annuity_income_benefit`
- `guaranteed_withdrawal_or_income_benefit` where present

Design note: surrender charges, market value adjustments, index formulas, free withdrawal provisions, and rider guarantees require strong evidence and frequent human review.

### 5.5 Immediate annuity

Common decrements/events:

- `death`
- `annuitization` / income commencement
- `maturity_expiry` for period certain ending

Common benefits:

- `annuity_income_benefit`
- `death_benefit` or refund/commutation value when guaranteed period/refund applies

Design note: payout option selection is central. The schema should represent life-only, period-certain, joint survivor, cash refund, installment refund, and guaranteed period options as benefit variants.

### 5.6 Multi-state

Common issue:

- A multi-state packet may contain conflicting provisions that are not true conflicts; they are jurisdiction-specific variants.

Design note: each decrement/benefit object may need a `jurisdiction_scope` field. AI review must not merge a California endorsement and a generic base form into one final field without preserving scope.

### 5.7 Participating life

Common decrements:

- `death`
- `surrender_lapse`
- `withdrawal` / loan
- `maturity_expiry`

Common benefits/features:

- `death_benefit`
- `surrender_benefit`
- `dividend_option`
- `paid_up_additions`
- `account_value_crediting` or cash value accumulation

Design note: dividends are usually non-guaranteed. The extractor must distinguish guaranteed values from non-guaranteed/dividend-scale illustrations.

---

## 6. AI review routing rules

The AI review layer should focus on materiality and evidence strength. It should not send every field to humans. It should escalate fields that materially affect downstream actuarial interpretation or lack clear evidence.

Recommended auto-accept criteria:

1. The field has a direct source quote.
2. The quote unambiguously supports the normalized value.
3. The field passes schema validation.
4. The field is consistent with product taxonomy.
5. No conflicting source section exists.
6. The field is not marked high-materiality or, if high-materiality, evidence confidence exceeds a stricter threshold.

Recommended mandatory escalation criteria:

- Multiple conflicting candidate values exist.
- A calculation formula is incomplete or references an external table not parsed.
- A benefit amount can change by state, option, age, class, underwriting, or rider election and the scope is unclear.
- Exclusions or limitations appear to modify the benefit but were not linked.
- A product appears multi-state but jurisdiction scope is missing.
- A field was inferred from product name only without contract/prospectus evidence.
- The AI proposes a skill/rule update that would change extraction behavior.

Suggested materiality tiers:

| Tier | Fields | Default review behavior |
|---|---|---|
| High | Benefit formula, caps, exclusions, termination effects, surrender charge, index/crediting formula, annuity payout option | Require strong evidence; escalate ambiguity. |
| Medium | Eligibility, issue age, premium mode, renewal/conversion windows, waiting periods | Auto-accept if clearly quoted; escalate conflicts. |
| Low | Product marketing description, carrier name, document date, brochure audience | Auto-accept with quote unless contradicted. |

---

## 7. Skill feedback design

Skill feedback should be generated from patterns across reviewed runs, not from a single correction alone. The learning system should produce proposed changes in a structured format.

Suggested `skill_improvement_candidate` shape:

```json
{
  "target_skill": "skills/north_america/traditional_life/ai_review_rubric.md",
  "issue_type": "recurring_missing_decrement",
  "observed_pattern": "Accelerated death benefit sections were repeatedly extracted as general riders instead of critical illness/living benefit triggers.",
  "evidence_runs": ["run_2026_05_09_001", "run_2026_05_10_003"],
  "proposed_change": "Add heading hints: 'Accelerated Benefit', 'Living Benefit', 'Terminal Illness', 'Critical Illness'. Require linkage to death benefit reduction when quoted.",
  "required_regression_fixture": "tests/fixtures/north_america/traditional_life/accelerated_benefit_001/",
  "review_status": "proposed"
}
```

Promotion rule: no skill update should become active unless a regression fixture is added and the relevant extraction/review tests pass.

---

## 8. Architecture implications

Recommended modules:

```text
src/life_product_extractor/
  taxonomy/          # region/product classification and routing
  sections/          # Markdown sectionization and evidence spans
  schema/            # product, decrement, benefit, review schemas
  extractors/        # profile-specific candidate extraction
  review/            # AI review, human review bundle, review application
  skills/            # skill-pack loading and validation
  learning/          # skill improvement proposal generation
  api/               # FastAPI or equivalent machine API
  cli.py             # Typer/Click CLI entrypoint
```

Recommended first contracts:

1. `routing.json`
2. `sections_structured.jsonl`
3. `candidate.json`
4. `ai_review.json`
5. `review_bundle.json`
6. `review_decisions.json`
7. `reviewed.json`
8. `status_report.json` / `status_report.md`
9. `skill_improvement_candidates.json`

---

## 9. Open questions for implementation planning

1. Should decrements and benefits be first-class top-level arrays from v0.1, or should they be embedded under product-class-specific fields first and normalized later?
2. Should policy options, loans, and withdrawals be separate from decrements, or included as broad decrement/event categories for modeling convenience?
3. Should AI review be per-field, per-benefit, or both? Initial recommendation: both, because a benefit-level formula can be uncertain even when component fields look valid.
4. What fields are required for “model-ready” status by product class?
5. How should the project represent “not applicable” versus “unknown” for high-materiality benefits?

---

## 10. Initial recommendation

Use decrements and benefits as first-class concepts in the v0.1 schema. Each benefit should link to one or more decrement/trigger objects and preserve evidence for trigger, eligibility, formula, limits, exclusions, and termination effects. AI review should route only uncertain or high-materiality ambiguous fields to humans, and post-review learning should generate test-gated skill improvement proposals rather than directly mutating extraction rules.
