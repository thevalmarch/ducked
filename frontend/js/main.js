/* ═══════════════════════════════════════════════════
   DUCKED.DEV — Frontend Controller
   ═══════════════════════════════════════════════════ */

import { resetPhaseBar, setActivePhase } from './components/phaseBar.js';
import { appendLog, populateTerminal, clearLogs } from './components/terminal.js';
import { startCountdown, stopCountdown } from './components/countdown.js';

const API = `${location.protocol}//${location.host}`;
const WS_PROTO = location.protocol === 'https:' ? 'wss:' : 'ws:';

let ws = null;
let sessionId = null;
let buildStartTime = null;
let runStartTime = null;
let ttl = 60; // seconds — matches config

// ── Global DOM Elements ──────────────────────────────
const repoInput = document.getElementById('repo-input');
const errorEl = document.getElementById('deploy-error');

// ── State Machine ───────────────────────────────────

function switchState(name) {
    document.querySelectorAll('.state').forEach(el => el.classList.remove('active'));
    const target = document.getElementById(`state-${name}`);
    if (target) target.classList.add('active');
}

// ── Deploy ──────────────────────────────────────────

async function deploy() {
    const repoUrl = repoInput.value.trim();
    if (!repoUrl) return;

    // Watcher reacts
    watcherState = 'deploying';
    watcher.classList.remove('focus');
    watcher.classList.add('deploying');
    watcherPupils.forEach(p => {
        p.style.transform = `translate(-50%, -50%)`;
    });

    // UI updates
    const btn = document.getElementById('btn-deploy');
    errorEl.style.display = 'none';

    btn.disabled = true;
    btn.textContent = 'Deploying...';

    try {
        const resp = await fetch(`${API}/api/deploy`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ repo_url: repoUrl }),
        });

        if (!resp.ok) {
            const data = await resp.json();
            throw new Error(data.detail || `HTTP ${resp.status}`);
        }

        const data = await resp.json();
        sessionId = data.session_id;
        buildStartTime = Date.now();

        // Reset state
        clearLogs();
        document.getElementById('terminal-build').innerHTML = '';
        document.getElementById('terminal-session-id').textContent = sessionId;
        resetPhaseBar();

        // Switch to building view
        switchState('building');

        // Connect WebSocket
        connectWS(sessionId);

    } catch (e) {
        errorEl.textContent = e.message;
        errorEl.style.display = 'block';
        btn.disabled = false;
        btn.textContent = 'Launch';
        watcherState = 'idle';
        watcher.classList.remove('deploying');
    }
}

// ── Watcher Interactions ────────────────────────────
const watcher = document.getElementById('watcher');
const watcherPupils = document.querySelectorAll('.watcher-pupil');
let watcherState = 'idle'; // idle, focused, deploying

document.addEventListener('mousemove', (e) => {
    if (watcherState !== 'idle') return;

    const eyes = document.querySelectorAll('.watcher-eye');
    eyes.forEach((eye, index) => {
        const rect = eye.getBoundingClientRect();
        const ex = rect.left + rect.width / 2;
        const ey = rect.top + rect.height / 2;

        const rad = Math.atan2(e.clientY - ey, e.clientX - ex);

        // Constrain distance to keep pupil inside eye (max ~3.5px)
        const distance = Math.min(3.5, Math.hypot(e.clientX - ex, e.clientY - ey) / 25);

        const tx = Math.cos(rad) * distance;
        const ty = Math.sin(rad) * distance;

        watcherPupils[index].style.transform = `translate(calc(-50% + ${tx}px), calc(-50% + ${ty}px))`;
    });
});

repoInput.addEventListener('focus', () => {
    if (watcherState === 'deploying') return;
    watcherState = 'focused';
    watcher.classList.add('focus');
    // Lock eyes down towards the input
    watcherPupils.forEach(p => {
        p.style.transform = `translate(-50%, calc(-50% + 3.5px))`;
    });
});

repoInput.addEventListener('blur', () => {
    if (watcherState === 'deploying') return;
    watcherState = 'idle';
    watcher.classList.remove('focus');
    watcherPupils.forEach(p => {
        p.style.transform = `translate(-50%, -50%)`;
    });
});

// ── API Interactions ──────────────────────────────────

function connectWS(sid) {
    ws = new WebSocket(`${WS_PROTO}//${location.host}/api/sessions/${sid}/ws`);

    ws.onmessage = (e) => {
        const event = JSON.parse(e.data);
        handleEvent(event);
    };

    ws.onerror = () => {
        appendLog('Connection error.', 'error');
    };

    ws.onclose = () => {
        ws = null;
    };
}

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
    const previewUrl = event.preview_url || `/preview/${sessionId}`;
    const frame = document.getElementById('preview-frame');
    const loading = document.getElementById('preview-loading');

    // Preview is served by Traefik on port 80, not by FastAPI on 9000
    frame.src = `${location.protocol}//${location.hostname}${previewUrl}/`;
    frame.onload = () => {
        loading.style.display = 'none';
        frame.style.display = 'block';
    };

    // Start countdown
    runStartTime = Date.now();
    startCountdown(runStartTime, ttl);

    // Switch view
    switchState('running');
}

// ── Destroyed State ─────────────────────────────────

function enterDestroyedState() {
    stopCountdown();

    // Calculate stats
    const totalTime = buildStartTime ? ((Date.now() - buildStartTime) / 1000).toFixed(1) : '—';
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
    if (ws) { ws.close(); ws = null; }
    stopCountdown();

    sessionId = null;
    buildStartTime = null;
    runStartTime = null;
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
    watcherState = 'idle';
    if (watcher) {
        watcher.classList.remove('focus', 'deploying');
        watcherPupils.forEach(p => p.style.transform = `translate(-50%, -50%)`);
    }

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

document.getElementById('btn-deploy').addEventListener('click', deploy);
document.getElementById('btn-reset').addEventListener('click', reset);

document.getElementById('repo-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') deploy();
});

