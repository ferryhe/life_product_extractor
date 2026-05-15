# ADR-0001: Use lightweight agent docs for domain grounding and vertical-slice work

## Status

Accepted

## Context

`life_product_extractor` has completed the initial CLI/API MVP rollout and now has enough domain vocabulary, artifact contracts, and agent workflow expectations that future work can drift if each session reconstructs the project from chat history. The project also has two different meanings of “skill”: repo-internal extractor/reviewer skill packs, and Hermes/agent procedural skills. That distinction needs to be visible to agents before they plan or edit.

The user also prefers narrow, verifiable PRs; cautious remote review handling; real service/browser checks for API or UI work; and explicit separation between autonomous agent work and human business decisions.

## Decision

Add lightweight project-level agent documentation:

- `CONTEXT.md` for durable domain vocabulary, invariants, external interfaces, and verification commands.
- `docs/agents/workflow.md` for startup, branch, planning, diagnosis, TDD, API, and reporting rules.
- `docs/agents/issue-tracker.md` for vertical-slice backlog items when GitHub Issues is not the active tracker.
- `docs/agents/triage-labels.md` for priority, domain area, execution mode, risk, verification, and status labels.

Future agents should read these files during startup alongside `AGENTS.md`, `.hermes/project-status.md`, `README.md`, and relevant research docs.

## Consequences

Benefits:

- Reduces cross-session drift in domain terms and project boundaries.
- Makes vertical-slice PR planning easier without requiring the user to repeat preferences.
- Separates durable vocabulary/decisions from transient task progress.
- Gives future Codex/Hermes workers a stable place to find verification gates and HITL/AFK boundaries.

Tradeoffs:

- Adds documentation that must be kept current when public contracts or workflow rules change.
- Agents must avoid treating backlog candidates as approved implementation orders; they are planning aids unless explicitly selected.
- `CONTEXT.md` must stay focused on durable vocabulary and invariants, not temporary TODO state.

## Alternatives Considered

- **Rely only on `AGENTS.md`**: Rejected because `AGENTS.md` is already a boundary and policy file; adding all domain glossary, labels, and issue templates there would make it too large and harder to scan.
- **Install Matt Pocock’s external skills wholesale**: Rejected because the repository needs project-specific Hermes/Codex conventions, insurance-domain vocabulary, and existing PR workflow rules rather than a generic external skill pack.
- **Use only GitHub Issues**: Deferred. A markdown tracker is useful for local planning and autonomous-agent handoff even if GitHub Issues are used later.
