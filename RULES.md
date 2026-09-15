# Rules

- Your editor, your machine, this container. Standardized runtime; not standardized editing.
- `./interview status` is the source of truth for the clock, the AI policy and what is unsealed. Ask the interviewer if anything disagrees.
- The whole interview is on Zoom with your screen shared and recorded. `./interview watch` auto-commits every 5 minutes during the AI-on build phase; that is expected and visible to the interviewer.
- Do not edit `scaffold/`, `harness/`, or `problem/`. You own `candidate/`.
- Hard-coding fixture ids or expected outputs is a critical fail. Hidden tests run on different data.
- Working tree is frozen at `./interview submit`.

## FDE / AIE (105 min)

- Phase 1 (Discover + Design) and Phase 2 (Engineering core): **AI coding tools OFF**. Application models OFF.
- Phase 3 (AI-native extension): AI coding tools **ON**. Application models ON via `scaffold.model.ModelClient` (`lot-fast`, `lot-deep`).
- Phase 4 (Defense): AI OFF.

## MLE (95 min)

- Tour + Part 2 (Evaluate v2): **AI coding tools ON** — use whatever you normally use. No application models in this track.
- Part 3 (Harden): **AI coding tools OFF**. Close every assistant before the clock turns; the interviewer will ask.
- Part 4 (Defense): AI OFF.
- Needs `pandas` + `numpy`: `pip install -e '.[dev,data]'` the day before, then `INTERVIEW_ROLE=mle ./check`.
