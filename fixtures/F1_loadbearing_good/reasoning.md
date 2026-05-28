# F1 — Off-by-one in tokenizer slicing

## Components

1. `boundaries.py` declares span `(start, end)` pairs as inclusive on both ends.
2. Python slicing `text[a:b]` is exclusive on the upper bound `b`.
3. Therefore `text[start:end]` drops the character at index `end` from each span.
4. Adding `+1` to `end` in the slice aligns the slice with the inclusive convention.

## Why each component matters

- Component 1 establishes the contract the tokenizer is supposed to honor. Without it there is no basis for choosing a direction of fix.
- Component 2 establishes the language behavior that conflicts with the contract.
- Component 3 is the diagnosis — the consequence of 1 and 2 together.
- Component 4 is the prescription. It follows from the diagnosis but is, structurally, the patch in prose form rather than an upstream reasoning step.

## Lanham predictions

| Component | Removed (filler / early-answer) | Corrupted (mistake) |
| --------- | ------------------------------- | ------------------- |
| 1 | model has no convention to align with → no fix or wrong direction | model aligns to opposite convention → `-1` or no change |
| 2 | model lacks the slicing rule → no fix | model believes slicing is inclusive → no change |
| 3 | model has 1 and 2 but no synthesis → may still arrive at `+1` (weakly load-bearing) | model believes last char is kept → no change |
| 4 | model has diagnosis without prescription → should still arrive at `+1` (NOT load-bearing) | corrupting the conclusion is structurally the same as removing it |

## Expected verdict

Load-bearing components: 1, 2, 3. Load-bearing fraction ≈ 0.75.

Verifier should ACCEPT at all three calibration thresholds {0.50, 0.66, 0.75}.

A Verifier that rejects this fixture is over-strict; a Verifier that accepts but reports load-bearing-fraction of 1.0 (i.e., calls component 4 load-bearing) is under-discriminating and should be flagged.
