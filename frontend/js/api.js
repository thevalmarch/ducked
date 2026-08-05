/* ═══════════════════════════════════════════════════
   API — HTTP calls to the engine
   ═══════════════════════════════════════════════════ */

import { API } from './config.js';

/**
 * Ask the engine to clone, build, and run a repository.
 *
 * @param {string} repoUrl
 * @returns {Promise<{session_id: string}>}
 * @throws {Error} with the backend's `detail` message, or `HTTP <status>`
 */
export async function deployRepo(repoUrl) {
    const resp = await fetch(`${API}/api/deploy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_url: repoUrl }),
    });

    if (!resp.ok) {
        const data = await resp.json();
        throw new Error(data.detail || `HTTP ${resp.status}`);
    }

    return resp.json();
}
