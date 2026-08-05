/* ═══════════════════════════════════════════════════
   TERMINAL — log buffer and rendering

   The buffer lives here rather than in main.js: it is only ever read to
   render a terminal, and every state (building, running, destroyed)
   renders from the same history.
   ═══════════════════════════════════════════════════ */

const logLines = [];

/** Drop all buffered lines. Called when a new session starts. */
export function clearLogs() {
    logLines.length = 0;
}

export function appendLog(text, type = 'log') {
    logLines.push({ text, type });

    // Append to build terminal
    const buildTerm = document.getElementById('terminal-build');
    if (buildTerm) appendToTerminal(buildTerm, text, type);

    // Also append to running terminal if visible
    const runTerm = document.getElementById('terminal-running');
    if (runTerm) appendToTerminal(runTerm, text, type);
}

function appendToTerminal(terminal, text, type) {
    const line = document.createElement('div');
    line.className = 'log-line';
    if (type === 'phase') line.classList.add('log-phase');
    if (type === 'error') line.classList.add('log-error');
    if (type === 'muted') line.classList.add('log-muted');
    line.textContent = text;
    terminal.appendChild(line);

    // Auto-scroll
    terminal.scrollTop = terminal.scrollHeight;
}

/** Re-render the full buffered history into a terminal element. */
export function populateTerminal(terminal) {
    terminal.innerHTML = '';
    logLines.forEach(({ text, type }) => {
        appendToTerminal(terminal, text, type);
    });
}
