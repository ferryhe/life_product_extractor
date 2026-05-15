# Agent Workflow

## Purpose

This document converts the project boundary in `AGENTS.md` and the domain language in `CONTEXT.md` into a practical workflow for Hermes, Codex, and other project-scoped agents working on `life_product_extractor`.

## Startup Routine

Every agent run must begin by reading:

1. `AGENTS.md`
2. `.hermes/project-status.md` if present
3. `README.md`
4. `CONTEXT.md`
5. Relevant docs under `docs/research/`, `docs/plans/`, or `docs/agents/`
6. Current git state via `git status --short --branch`

Then restate the active project, branch, task scope, likely files/directories to touch, and verification commands planned.

## Branch and PR Rules

- Treat `origin/main` as source of truth.
- Do not implement directly on `main` except for read-only inspection or explicit sync operations.
- Before new work, check dirty state. Preserve unrelated local edits instead of overwriting them.
- Create a focused branch using `feat/`, `fix/`, `docs/`, `refactor/`, `test/`, or `chore/`.
- Keep each PR narrow: one logical change per PR, but complete enough to run and test.
- Do not rename paths, outputs, public contracts, or compatibility behavior unless explicitly in scope.
- Do not perform opportunistic refactors.

## Planning Rules

Before implementation, write or maintain a compact plan using vertical slices:

```markdown
## Goal
One sentence: what product/operator-visible behavior changes?

## Domain Terms / Assumptions
- Term or assumption: source or status.

## Non-Goals
- Explicitly list what not to touch.

## Vertical Slices
### Slice 1: <name>
Behavior delivered:
Files likely touched:
Verification:
AFK/HITL:
```

A valid slice should produce an end-to-end behavior that can be verified independently. Avoid layer-only slices such as “add models”, “add API”, or “add tests” unless the slice itself is a complete behavior.

## AFK vs HITL

Mark work as **AFK-safe** when it can be completed from existing repo context and deterministic tests. Mark work as **HITL** when it requires user/business judgment, such as changing taxonomy policy, promoting source authority, accepting high-materiality human-review rules, or changing public artifact contracts.

## Diagnosis Workflow

For bugs, smoke failures, API failures, or extraction regressions:

1. Reproduce the exact failure signal.
2. Minimise to the smallest deterministic command, fixture, HTTP request, or test.
3. Form hypotheses tied to evidence.
4. Instrument with logs, one-off scripts, focused tests, or HTTP/browser checks.
5. Fix narrowly.
6. Rerun the original failure signal plus nearby regression checks.

Do not patch by guessing. Do not stop at import or route existence when the acceptance criterion is CLI/API behavior.

## TDD and Verification

For logic changes, prefer one behavior at a time:

1. Add one failing test through the public CLI/API/service contract.
2. Implement the smallest change to pass.
3. Refactor only inside scope.
4. Repeat.

Tests should assert behavior and contracts, not private helper implementation details, unless the helper is itself the stable public interface.

## API Change Policy

API endpoints must wrap the shared service layer. For API PRs:

- Preserve CLI/API equivalence where applicable.
- Validate examples with import checks and real local service requests.
- Start the actual API service and exercise key endpoints using HTTP tooling.
- Do not expose provider/model/embedding complexity to ordinary callers.

## Documentation Policy

Use:

- `CONTEXT.md` for durable domain vocabulary and invariants.
- `docs/adr/` for important, hard-to-reverse architecture decisions.
- `docs/agents/issue-tracker.md` for markdown backlog or future PR slices when GitHub Issues is not the active tracker.
- `docs/agents/triage-labels.md` for priority and label semantics.

Do not store secrets, credentials, tokens, private keys, or transient task progress in docs.

## Verification Gates

Documentation-only changes:

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

Code changes:

```bash
python -m pytest
life-extract --help
life-extract run --help
life-extract status --help
git diff --check
```

API changes additionally require a real local service smoke, for example:

```bash
uvicorn life_product_extractor.api.app:app --host 127.0.0.1 --port 8000
curl -s http://127.0.0.1:8000/health
```

## Reporting Format

Final reports should be in Chinese and include:

- Project and branch
- Files changed
- Tests/checks run and results
- PR URL if created/updated
- Review comments/checks status if applicable
- Blockers or decisions needed
- Next safe action
