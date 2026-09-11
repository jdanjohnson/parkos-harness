# Rules

- Your editor, your machine, this container. Standardized runtime; not standardized editing.
- Phase 1 (Discover + Design) and Phase 2 (Engineering core): **AI coding tools OFF**. Application models OFF.
- Phase 3 (AI-native extension): AI coding tools **ON**. Application models ON via `scaffold.model.ModelClient` (`lot-fast`, `lot-deep`).
- Phase 4 (Defense): AI OFF; working tree frozen at `./interview submit`.
- The whole interview is on Zoom with your screen shared and recorded. `./interview watch` auto-commits every 5 minutes during Phase 3; that is expected and visible to the interviewer.
- `./interview status` is the source of truth for the clock and policy. Ask the interviewer if anything disagrees.
- Do not edit `scaffold/`, `harness/`, or `problem/`. You own `candidate/`.
- Hard-coding fixture ids or expected outputs is a critical fail.
