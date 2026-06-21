# Contributing

Thanks for considering a contribution! This is a small, focused project and PRs are welcome.

## Good first contributions

- **Parser robustness** — the Gesellschafterliste has no standard layout; every notary uses a
  slightly different template. More real-world templates handled = more value. Add a synthetic
  fixture that reproduces the layout and a test, then make the parser handle it.
- **More register document types** — e.g. richer parsing of `VÖ` announcements or `UT` holder data.
- **Bug fixes** — especially around the portal's JSF/PrimeFaces flow when the markup drifts.

## Ground rules

- **Be polite to the portal.** Respect the 60-requests-per-hour limit. Do **not** write tests
  that hit `handelsregister.de` — the test suite must run fully offline against synthetic
  fixtures (see `tests/`).
- **Never commit real register data.** Register documents contain personal data (managing
  directors, shareholders, birthdates). Fixtures must be *synthetic*, not real downloads.
- **Keep the server deterministic.** This is a data-access tool consumed by LLM agents — it
  must not call an LLM itself. Parsing stays rule-based; when it can't parse, it returns the raw
  text for the calling agent to handle.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

ruff check src/ tests/   # lint
pytest -q                # tests (offline)
```

CI runs `ruff` + `pytest` on every PR across Python 3.10–3.13; please make sure both pass locally first.

## Pull requests

1. Fork the repo and create a branch.
2. Make your change with a test and a clear commit message.
3. Open a PR describing **what** changed and **why**, and how you verified it.

By contributing, you agree your contributions are licensed under the project's
[Apache-2.0](LICENSE) license.
