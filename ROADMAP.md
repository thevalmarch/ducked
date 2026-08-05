# Roadmap

Planned work for Ducked Engine. Items are not ordered by date — only by intent.

Nothing here is a promise. Things that stop making sense get deleted, not shipped.

---

## Frontend

### Component-based frontend architecture

**Status:** Done
**Scope:** `frontend/`

`frontend/index.html` was a single 1,249-line file with inline `<style>` and
`<script>` blocks — roughly 690 lines of CSS, 115 of markup, and 427 of
JavaScript. It is now 137 lines of markup, with the rest split into stylesheets
and ES modules.

No build step, no `package.json`, no `node_modules`. Ducked is a Python project
whose whole premise is minimalism; an npm toolchain to serve one page would cost
more than it returns. Native ES modules and plain CSS gave the file boundaries
without the pipeline. No backend change was needed either — `main.py` already
mounts `/static` → `../frontend`, so `/static/css/…` and `/static/js/…` resolve
against the existing route.

Shipped layout:

```
frontend/
  index.html          # markup + the #watcher-face template
  css/
    tokens.css        # :root custom properties
    base.css          # reset, body, .state visibility, .btn-deploy
    watcher.css       # the duck, its states, the zzz animation
    terminal.css      # log surface, shared by three states
    phase-bar.css     # clone/detect/build/run indicator
    states.css        # per-state layout
    responsive.css    # breakpoints, loaded last
  js/
    main.js           # controller: deploy, dispatch, state entry, wiring
    config.js         # API base, WS protocol, TTL
    store.js          # session state
    api.js            # deployRepo()
    socket.js         # connectWS / closeSocket
    router.js         # switchState()
    components/
      watcher.js      # eye tracking, focus/deploy/sleep states
      phaseBar.js     # phase transitions
      terminal.js     # log buffer + rendering
      countdown.js    # the 60s timer and bar
```

Where the result differed from the plan:

- **No `preview.js`.** The live-preview iframe is a handful of lines inside
  `enterRunningState()` and did not justify a module. Worth revisiting if the
  preview grows a loading or error state.
- **The log buffer lives in `terminal.js`, not `store.js`.** It is only ever read
  to render a terminal, so nothing else needs it.
- **`handleEvent` stayed in `main.js`** rather than moving into `socket.js`,
  which keeps the socket module pure transport with no knowledge of what a
  message means.
- **`connectWS` takes `onEvent`/`onError` callbacks.** `ws.onerror` logged
  directly rather than going through the dispatcher; routing it through the
  dispatcher would have torn the session down on a transient socket hiccup.

The refactor was behavior-preserving throughout: no visual change, no functional
change, no new dependencies. The one required fix was moving the inline
`onclick="deploy()"` and `onclick="reset()"` attributes to `addEventListener` —
ES modules do not share global scope, so attribute handlers stop resolving.

### Serve the session TTL from the API

**Status:** Planned
**Scope:** `frontend/js/config.js`, `backend/main.py`

`TTL` in `config.js` hardcodes 60 seconds, duplicating `SESSION_TTL` in
`backend/config.py`. If the backend value changes, the countdown drifts out of
sync with the reaper and the UI lies about how long a container has left.
Exposing it via `/api/health` or a small config endpoint would remove the
duplication.

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
