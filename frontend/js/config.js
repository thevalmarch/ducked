/* ═══════════════════════════════════════════════════
   CONFIG — endpoints and constants
   ═══════════════════════════════════════════════════ */

export const API = `${location.protocol}//${location.host}`;

export const WS_PROTO = location.protocol === 'https:' ? 'wss:' : 'ws:';

/**
 * Session lifetime in seconds.
 *
 * NOTE: duplicates SESSION_TTL in backend/config.py. If the backend value
 * changes, the countdown here drifts out of sync with the reaper. Worth
 * serving from the API instead — tracked in ROADMAP.md.
 */
export const TTL = 60;
