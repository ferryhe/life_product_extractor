# life_product_extractor

`life_product_extractor` is a CLI + API toolkit for auditable life insurance product field extraction from Markdown source documents. It turns curated Markdown + manifest inputs into deterministic routing, section evidence, candidate product JSON, validation reports, AI review output, selective human-review artifacts, reviewed JSON, status reports, and proposed skill-improvement candidates.

The current MVP pipeline is implemented end to end. The research notes under `docs/research/` explain the architecture and domain assumptions that drove the staged PR rollout.

## What it does

```text
Markdown + manifest
  -> routing / classification
  -> sections_structured.jsonl
  -> candidate JSON
  -> validation report
  -> AI review JSON
  -> selective human review bundle
  -> review_decisions.json
  -> reviewed JSON
  -> status_report.json/md
  -> skill improvement candidates
```

Core guarantees:

- CLI and API call the same deterministic service layer.
- JSON schemas are the authoritative contracts for artifacts.
- Extracted fields preserve evidence: source document, section/span, quote, confidence, and review status.
- AI review is separate from extraction and can escalate uncertain, unsupported, or high-materiality fields to human review.
- Skill improvement output is proposed-only; it does not mutate active skill packs without maintainer review and regression fixtures.

## Installation

Requires Python 3.11+.

```bash
pip install -e '.[dev]'
```

For API runtime dependencies without the dev/test extras:

```bash
pip install -e '.[api]'
```

## Quickstart: run the bundled deterministic pipeline

The repository includes a curated Manulife fixture manifest for local smoke testing.

```bash
life-extract run \
  --manifest examples/fixtures/manulife_tier1_curated/manifest.json \
  --out /tmp/life_product_extractor_run
```

The command writes these artifacts:

- `routing.json`
- `sections_structured.jsonl`
- `candidate.json`
- `validation_report.json`
- `ai_review.json`
- `review.html`
- `status_report.json`
- `status_report.md`

Build or rebuild a status report from run artifacts:

```bash
life-extract status \
  --candidate /tmp/life_product_extractor_run/candidate.json \
  --validation /tmp/life_product_extractor_run/validation_report.json \
  --ai-review /tmp/life_product_extractor_run/ai_review.json \
  --out-json /tmp/life_product_extractor_run/status_report.json \
  --out-md /tmp/life_product_extractor_run/status_report.md
```

After human review decisions have been applied, rebuild status from `reviewed.json`:

```bash
life-extract status \
  --reviewed /tmp/life_product_extractor_run/reviewed.json \
  --out-json /tmp/life_product_extractor_run/status_report.json \
  --out-md /tmp/life_product_extractor_run/status_report.md
```

## CLI reference

Implemented CLI slices:

```bash
life-extract validate-catalog
life-extract build-fixtures --out-dir fixtures_out/
life-extract classify --manifest manifest.json --out routing.json
life-extract sectionize --manifest manifest.json --out sections_structured.jsonl
life-extract extract --manifest manifest.json --routing routing.json --sections sections_structured.jsonl --out candidate.json
life-extract validate --candidate candidate.json --out validation_report.json
life-extract ai-review --candidate candidate.json --validation validation_report.json --out ai_review.json
life-extract review build-html --candidate candidate.json --ai-review ai_review.json --out review.html
life-extract review apply --candidate candidate.json --decisions review_decisions.json --out reviewed.json
life-extract run --manifest manifest.json --out out/
life-extract status --reviewed reviewed.json --out-json status_report.json --out-md status_report.md
life-extract learn propose --reviewed reviewed_a.json reviewed_b.json --out skill_improvement_candidates.json
```

Use `--help` on any command for exact arguments:

```bash
life-extract --help
life-extract run --help
life-extract status --help
```

## API usage

The optional FastAPI wrapper exposes the same service layer as the CLI.

```python
from life_product_extractor.api import create_app

app = create_app()
```

Run locally with Uvicorn after installing the API extra:

```bash
uvicorn life_product_extractor.api.app:app --reload
```

Available endpoints include:

- `GET /health`
- `POST /v1/runs/validate-catalog`
- `POST /v1/runs/build-fixtures`
- `POST /v1/runs/classify`
- `POST /v1/runs/sectionize`
- `POST /v1/runs/extract`
- `POST /v1/runs/validate`
- `POST /v1/runs/ai-review`
- `POST /v1/runs/review-bundle`
- `POST /v1/runs/apply-review`
- `POST /v1/runs/status`
- `POST /v1/runs/learn/propose`
- `POST /v1/runs/run`

Example request for the full run endpoint:

```bash
curl -s http://127.0.0.1:8000/v1/runs/run \
  -H 'content-type: application/json' \
  -d '{
    "manifest_path": "examples/fixtures/manulife_tier1_curated/manifest.json",
    "out_dir": "/tmp/life_product_extractor_api_run"
  }'
```

## Repository layout

```text
docs/research/                         Architecture and domain research notes
examples/fixtures/manulife_tier1_curated/  Curated Markdown fixture set + manifest
examples/sources/manulife_sources.yaml     Source catalog example
examples/run_orchestration_minimal/        End-to-end local smoke example
schemas/                               Canonical JSON schemas
src/life_product_extractor/            CLI/API/shared service implementation
tests/                                 Contract, CLI, API, and pipeline tests
```

## Important artifact notes

- `sections_structured.jsonl` is one structured document record per line. Each record preserves deterministic `section_id` values, heading hierarchy, Markdown line ranges, HTML-escaped `source_quote` strings, curated-source provenance, and detected `table_artifacts`.
- `ai_review.json` is a deterministic review artifact, not extraction output. It records acceptance, human-review, and blocked decisions independently from candidate generation.
- `review.html` is only an interaction layer for human review. Downstream systems should consume JSON artifacts instead.
- `skill_improvement_candidates.json` is a proposal artifact for maintainers. It summarizes recurring corrections across reviewed runs and requires regression fixtures before activation.

## Development checks

Run the full local verification suite before opening or merging changes:

```bash
python -m pytest
life-extract --help
life-extract run --help
life-extract status --help
git diff --check
```

Markdown files should keep a trailing newline.
