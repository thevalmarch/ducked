/* ═══════════════════════════════════════════════════
   DUCKED.DEV — Frontend Controller
   ═══════════════════════════════════════════════════ */

import { resetPhaseBar, setActivePhase } from './components/phaseBar.js';
import { appendLog, populateTerminal, clearLogs } from './components/terminal.js';
import { startCountdown, stopCountdown } from './components/countdown.js';
import { initWatcher, setWatcherState } from './components/watcher.js';
import { session, resetSession } from './store.js';
import { TTL } from './config.js';
import { deployRepo } from './api.js';
import { connectWS, closeSocket } from './socket.js';
import { switchState } from './router.js';

// ── Global DOM Elements ──────────────────────────────
const repoInput = document.getElementById('repo-input');
const errorEl = document.getElementById('deploy-error');

// ── Deploy ──────────────────────────────────────────

async function deploy() {
    const repoUrl = repoInput.value.trim();
    if (!repoUrl) return;

    // Watcher reacts
    setWatcherState('deploying');

    // UI updates
    const btn = document.getElementById('btn-deploy');
    errorEl.style.display = 'none';

    btn.disabled = true;
    btn.textContent = 'Deploying...';

    try {
        const data = await deployRepo(repoUrl);
        session.sessionId = data.session_id;
        session.buildStartTime = Date.now();

        // Reset state
        clearLogs();
        document.getElementById('terminal-build').innerHTML = '';
        document.getElementById('terminal-session-id').textContent = session.sessionId;
        resetPhaseBar();

        // Switch to building view
        switchState('building');

        // Connect WebSocket
        connectWS(session.sessionId, {
            onEvent: handleEvent,
            onError: () => appendLog('Connection error.', 'error'),
        });

    } catch (e) {
        errorEl.textContent = e.message;
        errorEl.style.display = 'block';
        btn.disabled = false;
        btn.textContent = 'Deploy';
        setWatcherState('idle');
    }
}

// ── Event Dispatch ────────────────────────────────────

function handleEvent(event) {
    switch (event.type) {
        case 'status':
            // Backend sends {type: "status", status: "<value>"}, not {type: "phase", phase: "<value>"}.
            handlePhase({ ...event, phase: event.status });
            break;
        case 'build_log':
            appendLog(event.data, 'log');
            break;
        case 'error':
            appendLog(`ERROR: ${event.data}`, 'error');
            handleError(event);
            break;
    }
}

// ── Phase Handling ──────────────────────────────────

function handlePhase(event) {
    const phase = event.phase;

    switch (phase) {
        case 'cloning':
            setActivePhase('clone');
            appendLog('>>> CLONING — Fetching the specimen...', 'phase');
            break;

        case 'cloned':
            appendLog('>>> Clone complete.', 'phase');
            break;

        case 'detecting':
            setActivePhase('detect');
            appendLog('>>> DETECTING — Analyzing the subject...', 'phase');
            break;

        case 'detected':
            appendLog(`>>> Detected: ${event.data}`, 'phase');
            break;

        case 'building':
            setActivePhase('build');
            appendLog('>>> BUILDING — Assembling the container...', 'phase');
            break;

        case 'built':
            appendLog('>>> Build complete.', 'phase');
            break;

        case 'running':
            setActivePhase('run');
            appendLog(`>>> LIVE — Preview: ${event.preview_url}`, 'phase');
            enterRunningState(event);
            break;

        case 'failed':
            appendLog(`>>> FAILED: ${event.error}`, 'error');
            handleError(event);
            break;

        case 'destroyed':
            enterDestroyedState();
            break;
    }
}

// ── Running State ───────────────────────────────────

function enterRunningState(event) {
    // Populate the running terminal with existing logs
    const runTerm = document.getElementById('terminal-running');
    populateTerminal(runTerm);

    // Load preview iframe
    const previewUrl = event.preview_url || `/preview/${session.sessionId}`;
    const frame = document.getElementById('preview-frame');
    const loading = document.getElementById('preview-loading');

    // Preview is served by Traefik on port 80, not by FastAPI on 9000
    frame.src = `${location.protocol}//${location.hostname}${previewUrl}/`;
    frame.onload = () => {
        loading.style.display = 'none';
        frame.style.display = 'block';
    };

    // Start countdown
    session.runStartTime = Date.now();
    startCountdown(session.runStartTime, TTL);

    // Switch view
    switchState('running');
}

// ── Destroyed State ─────────────────────────────────

function enterDestroyedState() {
    stopCountdown();

    // Calculate stats
    const { buildStartTime, runStartTime } = session;
    const liveTime = runStartTime ? ((Date.now() - runStartTime) / 1000).toFixed(1) : '—';
    const buildTime = (buildStartTime && runStartTime)
        ? ((runStartTime - buildStartTime) / 1000).toFixed(1) : '—';

    document.getElementById('stat-lived').textContent = `Lived: ${liveTime}s`;
    document.getElementById('stat-built').textContent = `Built in: ${buildTime}s`;

    // Populate archive terminal
    const archiveTerm = document.getElementById('terminal-archive');
    populateTerminal(archiveTerm);

    switchState('destroyed');
}

// ── Error State ─────────────────────────────────────

function handleError(event) {
    enterDestroyedState();
    document.querySelector('.death-message h2').textContent = 'Pipeline failed.';
    document.querySelector('.death-message p').textContent = 'Even ducks have bad days.';
}

// ── Reset ───────────────────────────────────────────

function reset() {
    closeSocket();
    stopCountdown();

    resetSession();
    clearLogs();

    // Reset UI elements
    document.getElementById('repo-input').value = '';
    document.getElementById('btn-deploy').disabled = false;
    document.getElementById('btn-deploy').textContent = 'Deploy';
    document.getElementById('deploy-error').style.display = 'none';
    document.getElementById('terminal-build').innerHTML = '';
    document.getElementById('terminal-running').innerHTML = '';
    document.getElementById('terminal-archive').innerHTML = '';
    document.getElementById('preview-frame').src = '';
    document.getElementById('preview-frame').style.display = 'none';
    document.getElementById('preview-loading').style.display = 'flex';
    document.getElementById('countdown-bar').style.width = '100%';
    document.getElementById('countdown-bar').classList.remove('critical');
    document.getElementById('countdown-status').classList.remove('critical');
    document.getElementById('countdown-status').innerHTML = '<span>● Container alive</span>';

    // Reset Watcher State
    setWatcherState('idle');

    // Reset death message
    document.querySelector('.death-message h2').textContent = 'Session terminated.';
    document.querySelector('.death-message p').textContent = 'Zero traces remain. Quack.';

    resetPhaseBar();
    switchState('idle');
}

// ── Event wiring ────────────────────────────────────
// This file loads as <script type="module">, which does not share global
// scope, so inline onclick="deploy()" attributes can no longer resolve
// these functions. Every handler is bound here instead.

initWatcher(repoInput);

document.getElementById('btn-deploy').addEventListener('click', deploy);
document.getElementById('btn-reset').addEventListener('click', reset);

document.getElementById('repo-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') deploy();
});

