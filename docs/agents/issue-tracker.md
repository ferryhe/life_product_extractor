# Agent Issue Tracker

This file is a lightweight markdown backlog for future `life_product_extractor` work when GitHub Issues is not the active tracker. Each item should be a vertical slice: narrow, end-to-end, independently verifiable, and explicit about AFK/HITL boundaries.

## Template

```markdown
## <Status> — <Title>

Outcome:

Scope:
- In:
- Out:

Implementation notes:
- Files/modules likely touched:
- Existing conventions to follow:

Verification:
- Focused tests:
- CLI/API/service smoke:
- Regression checks:

AFK/HITL:
- AFK-safe:
- HITL decisions:

Done when:
- [ ] Behavior works end to end
- [ ] Tests/checks pass
- [ ] `CONTEXT.md` / ADR updated if durable terms or decisions changed
```

## Candidate Backlog

### Backlog — Productization roadmap refresh

Outcome: Create the next post-MVP roadmap after the initial architecture-to-API wrapper rollout, based on current code, schemas, README, and research docs.

Scope:
- In: inspect current CLI/API capabilities, identify gaps toward production use, propose a small PR sequence.
- Out: implementation changes, public contract changes, source authority changes.

Implementation notes:
- Likely touches `docs/plans/` or `docs/agents/issue-tracker.md` only.
- Use `CONTEXT.md` vocabulary and preserve the existing pipeline boundary.

Verification:
- Markdown smoke check.
- `git diff --check`.

AFK/HITL:
- AFK-safe: repo inspection and draft plan.
- HITL decisions: approving roadmap priority and public contract changes.

Done when:
- [ ] Roadmap is split into vertical PR slices.
- [ ] Each slice lists verification gates and non-goals.

### Backlog — Architecture deepening review

Outcome: Identify up to three concrete architecture deepening candidates after the MVP pipeline and API wrapper are complete.

Scope:
- In: inspect module boundaries, service sharing between CLI/API, schema/resource layout, and tests.
- Out: refactoring implementation unless separately approved.

Implementation notes:
- Output should be a short review doc or issue list, not a broad rewrite.
- Prefer candidates that improve locality, public contracts, or agent navigability.

Verification:
- Markdown smoke check.
- `git diff --check`.

AFK/HITL:
- AFK-safe: analysis and candidate drafting.
- HITL decisions: choosing which candidate becomes an implementation PR.

Done when:
- [ ] No more than three candidates are documented.
- [ ] Each candidate has minimal change, verification, risks, and non-goals.

### Backlog — API real-service smoke harness

Outcome: Add a deterministic local API smoke check that starts the real FastAPI service and exercises representative endpoints against the bundled fixture.

Scope:
- In: service startup instructions or test helper, `GET /health`, one full-run or representative endpoint smoke.
- Out: API contract redesign, provider/model integrations, browser UI.

Implementation notes:
- Preserve shared service-layer behavior.
- Avoid relying only on TestClient for the acceptance gate.

Verification:
- `python -m pytest`.
- `life-extract --help`.
- Real local Uvicorn + HTTP smoke.

AFK/HITL:
- AFK-safe: implementation and tests.
- HITL decisions: whether this belongs in CI or remains local/manual.

Done when:
- [ ] Real service smoke is documented and repeatable.
- [ ] Existing API tests still pass.

### Backlog — Skill improvement promotion policy

Outcome: Define the maintainer workflow for promoting `skill_improvement_candidates.json` into repo-internal skill packs.

Scope:
- In: policy doc and test-gated promotion checklist.
- Out: automatic mutation of active skill packs.

Implementation notes:
- Must preserve proposed-only learning invariant.
- Should require regression fixtures for any promoted rule/rubric change.

Verification:
- Markdown smoke check.
- `git diff --check`.

AFK/HITL:
- AFK-safe: draft policy from existing docs and code.
- HITL decisions: approval thresholds and maintainer responsibilities.

Done when:
- [ ] Promotion steps and non-goals are explicit.
- [ ] Review roles and regression fixture requirements are clear.
