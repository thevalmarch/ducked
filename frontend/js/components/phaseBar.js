/* ═══════════════════════════════════════════════════
   PHASE BAR — clone → detect → build → run indicator
   ═══════════════════════════════════════════════════ */

const ORDER = ['clone', 'detect', 'build', 'run'];

export function resetPhaseBar() {
    ORDER.forEach(p => {
        const el = document.getElementById(`phase-${p}`);
        if (el) el.classList.remove('active', 'done');
    });
    const ind = document.getElementById('phase-indicator');
    if (ind) ind.style.opacity = '0';
}

export function setActivePhase(name) {
    const idx = ORDER.indexOf(name);
    const indicator = document.getElementById('phase-indicator');

    ORDER.forEach((p, i) => {
        const el = document.getElementById(`phase-${p}`);
        if (!el) return;
        el.classList.remove('active', 'done');
        if (i < idx) el.classList.add('done');
        if (i === idx) {
            el.classList.add('active');
            if (indicator) {
                indicator.style.opacity = '1';
                indicator.style.left = `${el.offsetLeft}px`;
                indicator.style.width = `${el.offsetWidth}px`;

                let color = 'var(--text-primary)';
                if (p === 'clone') color = 'var(--phase-clone)';
                if (p === 'build') color = 'var(--phase-build)';
                if (p === 'run') color = 'var(--phase-run)';

                indicator.style.backgroundColor = color;
                indicator.style.boxShadow = `0 0 10px ${color}`;
            }
        }
    });
}
