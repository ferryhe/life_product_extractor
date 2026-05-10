# life_product_extractor

CLI + API toolkit for auditable life insurance product field extraction, AI review, selective human review, and reviewed JSON/status output from Markdown source documents.

This repository is in its early architecture/research phase. Initial design notes live under `docs/research/`.

Current implemented CLI slices:

- `life-extract validate-catalog`
- `life-extract build-fixtures`
- `life-extract classify --manifest ... --out routing.json`
- `life-extract sectionize --manifest ... --out sections_structured.jsonl`
- `life-extract extract --manifest ... --routing ... --sections ... --out candidate.json`

`sections_structured.jsonl` is a JSONL artifact with one structured document record per line. Each record preserves deterministic `section_id` values, heading hierarchy, Markdown line ranges, HTML-escaped `source_quote` strings, curated-source provenance, and any detected `table_artifacts`.
