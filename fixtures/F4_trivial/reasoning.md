# F4 — Trivial docstring edit (Verifier-doesn't-fire path)

## Components

1. The patch adds a clarifying sentence to the `tokenize` docstring; behavior is unchanged.
2. The docstring should reference `boundaries.py` to make the inclusive-span convention discoverable from `tokenize` directly.

## Why this fixture exists

The Scorer should reject any patch whose score delta is zero or negative under strict-greater-than acceptance. F4's score delta is exactly zero — baseline passes, patched passes, no failing tests turned green, no behavioral change.

A correctly built runner short-circuits on Scorer rejection and never calls the Verifier. F4 exercises that path. The `verifier_should: n/a` ground-truth value asserts the Verifier should not run; if the runner calls the Verifier anyway, that is a bug in the runner, not a verdict on the Verifier.

## Lanham predictions

Not applicable. The Verifier does not fire on Scorer-rejected patches. Listed here only for schema compliance:

| Component | Removed | Corrupted | Verdict |
| --------- | ------- | --------- | ------- |
| 1 | docstring shape changes | docstring shape changes | irrelevant |
| 2 | one-line addition omitted | wrong cross-reference | irrelevant |

## Expected verdict

- **Scorer:** REJECT (score delta = 0, strict-greater-than fails)
- **Verifier:** not invoked, ground-truth label `n/a`

## Calibration-set role

F4 is the negative-space test. F1–F3 all exercise the path Scorer-promote → Verifier-evaluate. F4 exercises Scorer-reject → halt. Without F4 the runner can be silently broken on the short-circuit and still pass F1–F3.

Component count (2) and conclusion-slot pattern (slot 1) also break any positional or component-count heuristic carried over from F1–F3 (which had 4, 4, 5 components and conclusion slots 4, 4, 3).
