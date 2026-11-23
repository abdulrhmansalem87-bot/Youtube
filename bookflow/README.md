# BookFlow

Isolated plan-validation foundation for the silent book-page video format.

- Production rules: [BOOKFLOW_PRODUCTION_METHOD.md](../BOOKFLOW_PRODUCTION_METHOD.md)
- Example short plan: [examples/sample_short.json](examples/sample_short.json)
- Configuration: [config.json](config.json)

## Validate locally
```bash
python scripts/bookflow_validate.py bookflow/examples/sample_short.json
python -m unittest discover -s tests -p "test_bookflow_contract.py" -v
```

This stage validates plans only. It does not generate media, call TTS, use NewsFlow, upload, or publish.
