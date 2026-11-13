# AGENTS.md

## Project Context
This repository contains a small internal CLI utility used to fetch JSON data
from external APIs. The utility currently has no resilience against transient
network failures. Your task is to add retry-with-backoff behavior to the
HTTP fetch path, with accompanying tests.

## Build / Test / Lint Commands
- Install deps:      pip install -r requirements.txt   (or npm install)
- Run all tests:     pytest -q                          (or npm test)
- Run a single test: pytest -q path/to/test_file.py::test_name
- Lint:              ruff check .                        (or npm run lint)
- Type-check:        mypy .                              (or tsc --noEmit)

Run lint and the full test suite before considering any change complete.

## Coding Conventions
- Match the existing style of the file you're editing (naming, docstring
  format, import ordering). Do not reformat unrelated code.
- Functions should have type hints (Python) or explicit types (TS).
- Prefer small, composable functions over large ones.
- Log retries and failures explicitly — do not fail or recover silently.
- Write a short docstring/comment for any new public function explaining
  why, not just what.

## Constraints / Guardrails
- Do not add new third-party dependencies. Use only what's already imported
  in the repo, plus standard library.
- Do not modify files outside the HTTP client module and its test file
  unless strictly necessary — if you believe a change elsewhere is required,
  explain why before making it.
- Retry logic must distinguish transient errors (timeouts, 429, 502/503/504)
  from non-transient client errors (4xx other than 429) — the latter must
  fail immediately, without retrying.
- Any exponential backoff must include jitter to avoid thundering-herd
  behavior, and must have a configurable maximum number of attempts.

## Self-Verification
Before declaring the task complete, you must:
1. Run the full test suite and confirm all tests pass, including the new
   ones you added.
2. Run the lint and type-check commands and confirm no new warnings/errors
   were introduced.
3. Re-read your diff and confirm it stays within the stated scope (HTTP
   client module + its tests only).
4. Summarize, in plain language, what retry behavior was added and how it
   was tested — as if handing off to a human reviewer who hasn't seen the
   task brief.