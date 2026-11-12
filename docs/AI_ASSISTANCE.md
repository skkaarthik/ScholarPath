# AI assistance disclosure

> Editable template. Adjust it to your institution's policy and to what really happened.
> Keep statements factual.

## Tool used

- Assistant: Claude (Anthropic), model Claude Opus 5.5, via Claude Code.
- Date of initial generation: 2026-11-12.

## What the assistant did

Starting from a written specification provided by the student(s), the assistant:

- designed and wrote the Python code in `scholarpath/`, `app.py` and `tests/`;
- inspected the two official source websites in a browser, checked their robots.txt files and
  captured trimmed HTML snapshots (`data/snapshots/`);
- generated the fictional example dataset (`data/examples/`);
- ran the test suite, a clean-start smoke test and a headless-browser smoke test;
- wrote the documentation in `README.md` and `docs/`;
- made the Git commits on branch `feature/scholarpath-v1` (author `Claude`, with a
  `Co-Authored-By` trailer).

## What the student(s) did

> Fill in: e.g. wrote the specification, reviewed code, ran the app, changed X, verified Y,
> prepared the presentation.

-
-

## Verification by the student(s)

> Fill in what you personally checked (e.g. "ran `python -m pytest` on Windows - all passed",
> "compared the 16 real records with the official pages on <date>").

-

## Limits of the assistance

- The assistant did not verify live HTTP collection (network blocked in its environment).
- No real record has been manually verified against its official page.
- Eligibility logic is rule-based; no AI is used at runtime.
