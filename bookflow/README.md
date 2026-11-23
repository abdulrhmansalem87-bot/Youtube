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

The renderer creates three visual beats per scene (page highlight/motif changes and a slow camera push-in), saves a resumable cache manifest, and validates that the final MP4 has the correct duration/resolution and no audio stream. A retry reuses verified completed beats.

BookFlow is currently render-and-review only. It has no YouTube/TikTok upload, scheduling or publishing action.
