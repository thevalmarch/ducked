/* ═══════════════════════════════════════════════════
   WATCHER — the interactive duck

   Owns its own state ('idle' | 'focused' | 'deploying'). Callers change
   it through setWatcherState() instead of touching classes directly.

   NOTE: the selectors below are document-wide on purpose. The destroyed
   state renders a second (sleeping) watcher, so .watcher-pupil and
   .watcher-eye match four elements, not two, and both faces animate
   together. Only the idle watcher carries id="watcher".
   ═══════════════════════════════════════════════════ */

// Populated by initWatcher(). The face is cloned in at that point, so the
// pupils do not exist until then and cannot be captured at module load.
let watcher = null;
let watcherPupils = [];

let watcherState = 'idle'; // idle, focused, deploying

const CENTER = `translate(-50%, -50%)`;
const LOOK_DOWN = `translate(-50%, calc(-50% + 3.5px))`;

function setPupils(transform) {
    watcherPupils.forEach(p => {
        p.style.transform = transform;
    });
}

/**
 * Move the watcher to a new state.
 * @param {'idle'|'focused'|'deploying'} next
 */
export function setWatcherState(next) {
    watcherState = next;
    if (!watcher) return;

    switch (next) {
        case 'deploying':
            watcher.classList.remove('focus');
            watcher.classList.add('deploying');
            setPupils(CENTER);
            break;

        case 'focused':
            watcher.classList.add('focus');
            // Lock eyes down towards the input
            setPupils(LOOK_DOWN);
            break;

        case 'idle':
            watcher.classList.remove('focus', 'deploying');
            setPupils(CENTER);
            break;
    }
}

/**
 * Clone the shared face into every [data-watcher-face] host.
 *
 * The idle and destroyed states render the same eyes and beak; only the
 * host's classes differ ('sleeping' shuts the eyes via CSS). The markup
 * lives in the #watcher-face <template> in index.html so it stays
 * declarative rather than being built from strings here.
 */
function renderFaces() {
    const tpl = document.getElementById('watcher-face');
    if (!tpl) return;

    document.querySelectorAll('[data-watcher-face]').forEach(host => {
        host.appendChild(tpl.content.cloneNode(true));
    });
}

/**
 * Render the faces and attach the interaction listeners.
 * @param {HTMLElement} inputEl  the repo input the eyes react to
 */
export function initWatcher(inputEl) {
    renderFaces();

    watcher = document.getElementById('watcher');
    watcherPupils = document.querySelectorAll('.watcher-pupil');

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

    inputEl.addEventListener('focus', () => {
        if (watcherState === 'deploying') return;
        setWatcherState('focused');
    });

    inputEl.addEventListener('blur', () => {
        if (watcherState === 'deploying') return;
        setWatcherState('idle');
    });
}
