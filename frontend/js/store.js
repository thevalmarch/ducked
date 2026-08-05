/* ═══════════════════════════════════════════════════
   STORE — state for the current session

   Exported as one mutable object rather than individual bindings. An
   exported `let` is live for readers but read-only to importers, so
   modules that need to WRITE session state (socket.js setting `ws`,
   api.js setting `sessionId`) could not use it. A const binding holding
   a mutable object gives every module a shared, writable handle without
   a wrapper function per field.
   ═══════════════════════════════════════════════════ */

export const session = {
    /** @type {WebSocket|null} live log stream, null when disconnected */
    ws: null,
    /** @type {string|null} id returned by POST /api/deploy */
    sessionId: null,
    /** @type {number|null} Date.now() when the build was kicked off */
    buildStartTime: null,
    /** @type {number|null} Date.now() when the container went live */
    runStartTime: null,
};

/** Clear all session state. Does not close the socket — callers do that. */
export function resetSession() {
    session.ws = null;
    session.sessionId = null;
    session.buildStartTime = null;
    session.runStartTime = null;
}
