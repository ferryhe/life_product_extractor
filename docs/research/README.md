# Research Notes

This directory records the domain and architecture research that shaped the implemented MVP pipeline. The notes are still useful as design rationale, even though the CLI/API/schema slices described in the roadmap have now been implemented in code.

Current notes:

1. `product-taxonomy-and-skill-map.md` — region/product-class taxonomy and how extractor/reviewer skills should be organized.
2. `decrement-and-benefit-decomposition.md` — domain decomposition around decrements, benefits, triggers, calculation methods, evidence, and review routing.
3. `architecture-and-pr-roadmap.md` — CLI/API architecture, AI review flow, skill-pack lifecycle, and staged PR plan.
4. `manulife-real-test-pr-plan.md` — Manulife real-product source catalog, fixture tiers, and implementation PR sequence grounded in real products.

Working assumptions that remain active in the implementation:

- Markdown source plus manifest is the canonical input contract for this repo.
- Candidate/reviewed JSON and status reports are the canonical output contracts.
- HTML review bundles are an interaction layer only; downstream systems must not parse HTML as product data.
- AI review should reduce human review volume by classifying fields into accepted/needs-human/blocked buckets, but must not silently finalize uncertain or unsupported fields.
- Skill improvement proposals are maintainer-reviewed artifacts and do not automatically mutate active extraction/review behavior.
