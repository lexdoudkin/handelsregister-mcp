## What & why

<!-- What does this change do, and why? Link any related issue. -->

## How I tested it

<!-- e.g. added a synthetic fixture + test; `pytest -q` and `ruff check` pass locally. -->

## Checklist

- [ ] `ruff check src/ tests/` passes
- [ ] `pytest -q` passes
- [ ] No real register data / personal data committed (fixtures are synthetic)
- [ ] No new live-portal calls in tests; respects the 60 req/hour etiquette
- [ ] The server stays deterministic (no LLM calls added inside it)
