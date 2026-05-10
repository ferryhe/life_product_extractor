# Research Notes

This directory records early domain and architecture research before implementation PRs are cut. The goal is to freeze a practical extraction taxonomy first, so later CLI/API/schema work has a stable target.

Current notes:

1. `product-taxonomy-and-skill-map.md` — region/product-class taxonomy and how extractor/reviewer skills should be organized.
2. `decrement-and-benefit-decomposition.md` — domain decomposition around decrements, benefits, triggers, calculation methods, evidence, and review routing.
3. `architecture-and-pr-roadmap.md` — CLI/API architecture, AI review flow, skill-pack lifecycle, and staged PR plan.

Working assumptions:

- Markdown source plus manifest is the canonical input contract for this repo.
- Candidate/reviewed JSON and status reports are the canonical output contracts.
- HTML review bundles are an interaction layer only; downstream systems must not parse HTML as product data.
- AI review should reduce human review volume by classifying fields into accepted/needs-human/blocked buckets, but must not silently finalize uncertain or unsupported fields.
