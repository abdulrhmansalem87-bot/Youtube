# BookFlow

A separate premium silent-video pipeline for book-inspired finance and business content.

- Production rules: [BOOKFLOW_PRODUCTION_METHOD.md](../BOOKFLOW_PRODUCTION_METHOD.md)
- [Short sample plan](examples/sample_short.json) — 48 seconds, 9:16.
- [Long sample plan](examples/sample_long.json) — 5 minutes, 16:9.
- [Visual configuration](config.json)

## Validate plans
```bash
python scripts/bookflow_validate.py bookflow/examples/sample_short.json
python scripts/bookflow_validate.py bookflow/examples/sample_long.json
python -m unittest discover -s tests -p "test_bookflow_contract.py" -v
```

## Render silent MP4s
```bash
python scripts/bookflow_render.py bookflow/examples/sample_short.json --output output/bookflow-short.mp4 --cache output/bookflow-cache/short
python scripts/bookflow_render.py bookflow/examples/sample_long.json --output output/bookflow-long.mp4 --cache output/bookflow-cache/long
```

The renderer creates a new visual beat every 2–3 seconds, saves a resumable cache manifest, and validates the final MP4's duration, resolution and silent audio contract. A retry reuses verified completed beats.

GitHub Actions stores review MP4s and QA manifests as a temporary workflow artifact. BookFlow has no YouTube/TikTok upload, scheduling, publishing, OAuth or production-secret integration.
