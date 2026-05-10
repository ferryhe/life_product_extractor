# life_product_extractor

CLI + API toolkit for auditable life insurance product field extraction, AI review, selective human review, and reviewed JSON/status output from Markdown source documents.

This repository is in its early architecture/research phase. Initial design notes live under `docs/research/`.

Current implemented CLI slices:

- `life-extract validate-catalog`
- `life-extract build-fixtures`
- `life-extract classify --manifest ... --out routing.json`
- `life-extract sectionize --manifest ... --out sections_structured.jsonl`
- `life-extract extract --manifest ... --routing ... --sections ... --out candidate.json`
- `life-extract validate --candidate ... --out validation_report.json`
- `life-extract ai-review --candidate ... --validation ... --out ai_review.json`
- `life-extract review build-html --candidate ... --ai-review ... --out review.html`
- `life-extract review apply --candidate ... --decisions ... --out reviewed.json`
- `life-extract run --manifest ... --out out/`
- `life-extract status --reviewed ... --out-json status_report.json --out-md status_report.md`
- `life-extract learn propose --reviewed reviewed_a.json reviewed_b.json --out skill_improvement_candidates.json`

API usage is available through the optional FastAPI wrapper over the same service layer as the CLI:

```bash
pip install '.[api]'
```

```python
from life_product_extractor.api import create_app

app = create_app()
```

The API exposes `/v1/runs/*` endpoints for classify, sectionize, extract, validate, AI review, review bundle, review apply, status, full run orchestration, and learning proposal requests.

Learning proposals are proposed-only artifacts for maintainer review; they summarize recurring corrections across reviewed runs, do not mutate active skill packs, and require regression fixtures before activation.

`sections_structured.jsonl` is a JSONL artifact with one structured document record per line. Each record preserves deterministic `section_id` values, heading hierarchy, Markdown line ranges, HTML-escaped `source_quote` strings, curated-source provenance, and any detected `table_artifacts`.
