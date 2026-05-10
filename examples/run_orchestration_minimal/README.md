# Run orchestration minimal example

This example uses the committed curated fixture manifest to exercise the deterministic pipeline without human decisions:

```bash
life-extract run \
  --manifest examples/fixtures/manulife_tier1_curated/manifest.json \
  --out /tmp/life_product_extractor_run
```

The command writes `routing.json`, `sections_structured.jsonl`, `candidate.json`, `validation_report.json`, `ai_review.json`, `review.html`, `status_report.json`, and `status_report.md`.

To rebuild status after applying human review decisions:

```bash
life-extract status \
  --reviewed /tmp/life_product_extractor_run/reviewed.json \
  --out-json /tmp/life_product_extractor_run/status_report.json \
  --out-md /tmp/life_product_extractor_run/status_report.md
```
