/* ═══════════════════════════════════════════════════
   CONFIG — endpoints and constants
   ═══════════════════════════════════════════════════ */

export const API = `${location.protocol}//${location.host}`;

export const WS_PROTO = location.protocol === 'https:' ? 'wss:' : 'ws:';

/**
 * Session lifetime in seconds.
 *
 * Fallback only — loadConfig() replaces this with the engine's actual
 * CONTAINER_TTL_SECONDS so the countdown cannot drift from the reaper.
 *
 * Exported as `let` deliberately: importers get a live binding, and
 * config.js is the only writer. Modules that need to WRITE shared state
 * use the mutable object in store.js instead.
 */
export let TTL = 60;

/**
 * Pull runtime values from the engine.
 *
 * Fire-and-forget at startup: the TTL is not read until a container
 * reaches the running phase, which is a clone and a build away, so the
 * response has long since landed. If the request fails the fallback
 * above stands and behaviour is unchanged.
 */
export async function loadConfig() {
    try {
        const resp = await fetch(`${API}/api/health`);
        if (!resp.ok) return;

        const data = await resp.json();
        const ttl = Number(data.container_ttl_seconds);
        if (Number.isFinite(ttl) && ttl > 0) TTL = ttl;
    } catch {
        // Engine unreachable — keep the fallback.
    }
}
