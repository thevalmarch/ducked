/* ═══════════════════════════════════════════════════
   ROUTER — which state section is visible

   Exactly one .state carries .active at a time.
   ═══════════════════════════════════════════════════ */

/** @param {'idle'|'building'|'running'|'destroyed'} name */
export function switchState(name) {
    document.querySelectorAll('.state').forEach(el => el.classList.remove('active'));
    const target = document.getElementById(`state-${name}`);
    if (target) target.classList.add('active');
}
