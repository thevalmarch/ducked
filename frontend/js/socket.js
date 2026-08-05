/* ═══════════════════════════════════════════════════
   SOCKET — live log stream

   Transport only. Parsing a frame into an application event is the
   caller's job, so this module stays unaware of the UI.
   ═══════════════════════════════════════════════════ */

import { WS_PROTO } from './config.js';
import { session } from './store.js';

/**
 * Open the log stream for a session and store the handle.
 *
 * @param {string} sid
 * @param {object} handlers
 * @param {(event: object) => void} handlers.onEvent  parsed message payload
 * @param {() => void} handlers.onError               transport failure
 */
export function connectWS(sid, { onEvent, onError }) {
    session.ws = new WebSocket(`${WS_PROTO}//${location.host}/api/sessions/${sid}/ws`);

    session.ws.onmessage = (e) => {
        onEvent(JSON.parse(e.data));
    };

    session.ws.onerror = () => {
        onError();
    };

    session.ws.onclose = () => {
        session.ws = null;
    };
}

/** Close the stream if one is open. Safe to call when already closed. */
export function closeSocket() {
    if (session.ws) session.ws.close();
}
