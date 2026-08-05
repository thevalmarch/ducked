# Roadmap

Planned work for Ducked Engine. Items are not ordered by date — only by intent.

Nothing here is a promise. Things that stop making sense get deleted, not shipped.

---

## Frontend

### Component-based frontend architecture

**Status:** Planned
**Scope:** `frontend/`

The frontend is currently a single 1,249-line `frontend/index.html` with inline
`<style>` and `<script>` blocks — roughly 690 lines of CSS, 115 lines of markup,
and 427 lines of JavaScript in one file. It works, but it has hit the point where
the four UI states (idle → building → running → destroyed) are difficult to edit
in isolation, and the CSS has no enforced boundaries between them.

The plan is to split it into ES modules and separate stylesheets — **no build
step, no `package.json`, no `node_modules`**. Ducked is a Python project whose
whole premise is minimalism; adding an npm toolchain to serve one page would cost
more than it returns. Native ES modules and plain CSS give the file boundaries
without the pipeline.

Target layout:

```
frontend/
  index.html          # markup only — no inline style or script
  css/
    tokens.css        # colors, spacing, fonts (single source of truth)
    base.css          # reset, layout primitives, shared .state rules
    watcher.css       # the duck, its states, the zzz animation
    terminal.css      # terminal + log line styling (shared by 3 states)
    phase-bar.css     # clone/detect/build/run indicator
    states.css        # per-state layout (idle, building, running, destroyed)
    responsive.css    # breakpoints
  js/
    main.js           # entry point, wires DOM events
    config.js         # API base, WS protocol, TTL
    store.js          # session state + log buffer
    api.js            # fetch wrappers for /api/deploy etc.
    socket.js         # WebSocket lifecycle + event dispatch
    router.js         # switchState() — the state machine
    components/
      watcher.js      # eye tracking, focus/deploy/sleep states
      phaseBar.js     # phase transitions
      terminal.js     # append/populate log lines
      countdown.js    # the 60s timer and bar
      preview.js      # live preview iframe
```

Notes and constraints:

- **No backend change is required.** `main.py` already mounts `/static` →
  `../frontend`, so assets referenced as `/static/css/…` and `/static/js/…`
  resolve without touching the FastAPI routes.
- The inline `onclick="deploy()"` and `onclick="reset()"` handlers **must** move
  to `addEventListener`. ES modules do not share global scope, so inline
  attribute handlers silently stop resolving.
- The hardcoded `ttl = 60` in the frontend duplicates `config.py`. Worth exposing
  via `/api/health` or a config endpoint so the two cannot drift.
- The watcher markup is duplicated between the idle and destroyed states — a
  candidate for a single render function.

This refactor is explicitly **behavior-preserving**: no visual or functional
change, no new dependencies.

---

## Integrations

### Self-hosted Git instance support

**Status:** Planned
**Scope:** `backend/services/github_service.py`

Support cloning from Forgejo, GitLab, and Gitea in addition to GitHub. Requires
generalizing URL validation and the pre-clone size check, which currently assumes
the GitHub REST API.

---

## Contributing

Want to pick something up? Open an issue first so we can agree on scope — see
[CONTRIBUTING.md](CONTRIBUTING.md).
