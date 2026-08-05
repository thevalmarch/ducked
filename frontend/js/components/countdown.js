/* ═══════════════════════════════════════════════════
   COUNTDOWN — the TTL bar and remaining-seconds timer

   The interval handle is private to this module; callers start and stop
   it rather than clearing it themselves.
   ═══════════════════════════════════════════════════ */

let countdownInterval = null;

/**
 * @param {number} runStartTime  Date.now() when the container went live
 * @param {number} ttl           session lifetime in seconds
 */
export function startCountdown(runStartTime, ttl) {
    const bar = document.getElementById('countdown-bar');
    const timerEl = document.getElementById('countdown-timer');
    const statusEl = document.getElementById('countdown-status');

    stopCountdown();

    countdownInterval = setInterval(() => {
        const elapsed = (Date.now() - runStartTime) / 1000;
        const remaining = Math.max(0, ttl - elapsed);
        const pct = (remaining / ttl) * 100;

        bar.style.width = `${pct}%`;
        timerEl.textContent = `${Math.ceil(remaining)}s remaining`;

        if (remaining <= 3) {
            bar.classList.add('critical');
            statusEl.classList.add('critical');
        }

        if (remaining <= 0) {
            stopCountdown();
            timerEl.textContent = '0s';
        }
    }, 100);
}

export function stopCountdown() {
    if (countdownInterval) {
        clearInterval(countdownInterval);
        countdownInterval = null;
    }
}
