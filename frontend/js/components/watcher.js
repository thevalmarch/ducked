/* ═══════════════════════════════════════════════════
   WATCHER — the interactive duck

   Owns its own state ('idle' | 'focused' | 'deploying'). Callers change
   it through setWatcherState() instead of touching classes directly.

   NOTE: the selectors below are document-wide on purpose. The destroyed
   state renders a second (sleeping) watcher, so .watcher-pupil and
   .watcher-eye match four elements, not two, and both faces animate
   together. Only the idle watcher carries id="watcher".
   ═══════════════════════════════════════════════════ */

const watcher = document.getElementById('watcher');
const watcherPupils = document.querySelectorAll('.watcher-pupil');

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
 * Attach the interaction listeners.
 * @param {HTMLElement} inputEl  the repo input the eyes react to
 */
export function initWatcher(inputEl) {
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
