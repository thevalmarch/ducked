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

**Status:** Done
**Scope:** `frontend/js/config.js`, `frontend/js/main.js`

`config.js` used to hardcode 60 seconds, duplicating `CONTAINER_TTL_SECONDS` in
`backend/config.py`. `loadConfig()` now reads the value from `/api/health` — which
already reported it — at page load, so the countdown, the `TTL: 60s` constraint
label, and the timer placeholder all follow the engine.

The hardcoded 60 remains only as a fallback for when the engine is unreachable,
which leaves behaviour unchanged from before. No backend change was needed.

---

## Integrations

### Self-hosted Git instance support

**Status:** Done
**Scope:** `backend/config.py`, `backend/models.py`,
`backend/services/github_service.py`

The engine clones from GitHub, GitLab, Codeberg, and Gitea out of the box, plus
any self-hosted instance added via `GIT_ALLOWED_HOSTS`.

URL validation no longer pattern-matches GitHub. It parses the URL and checks the
authority against `settings.ALLOWED_GIT_HOSTS`, which is **the primary SSRF
defence** — `git clone` runs server-side, so an unrestricted host would let a
user point the engine at anything it can reach. The allowlist must never be
widened to arbitrary hosts.

Validation also rejects non-HTTPS schemes, credentials in the authority
(`https://github.com@evil.com/...`), query strings, fragments, and any path
segment that does not start alphanumeric — which rules out `.` and `..` traversal
outright. GitLab subgroups are supported up to five path segments.

Size checking is the only forge-specific part:

| Forge | Pre-clone size check |
|---|---|
| GitHub | `api.github.com/repos/...` |
| Gitea, Forgejo, Codeberg | `<host>/api/v1/repos/...` |
| GitLab | none — size needs `?statistics=true`, which public readers cannot use |

Where the API cannot answer, the clone falls through to the post-clone disk check
bounded by `CLONE_TIMEOUT_SECONDS`. That is the same graceful degradation the
GitHub path already had when its API was unreachable.

Possible follow-up: `GitHubService` is now a misnomer — it handles every forge.
Renaming it to `GitService` was left out to keep this change focused.

---

## Contributing

Want to pick something up? Open an issue first so we can agree on scope — see
[CONTRIBUTING.md](CONTRIBUTING.md).
