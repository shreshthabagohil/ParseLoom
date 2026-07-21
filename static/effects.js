/**
 * UI/UX phase (post Milestone 10): cursor-reactive visual effects,
 * hand-ported from Aceternity-UI-style interactions to plain vanilla
 * JS/CSS -- no React, no Framer Motion, no build step. Deliberately a
 * separate file from each template's own inline <script> (which owns
 * app logic: form submission, polling, rendering) so this purely
 * visual layer can't accidentally touch data/state, and stays easy to
 * disable wholesale (skip loading this one file) without touching app
 * logic at all.
 *
 * Two effects:
 *  1. A page-wide cursor spotlight (a fixed radial-gradient layer whose
 *     center tracks the pointer via CSS custom properties).
 *  2. A subtle 3D tilt on .card / .candidate-card elements, following
 *     the pointer while hovering.
 *
 * Both respect prefers-reduced-motion (skip entirely) and coarse
 * pointers / no-hover devices (skip the tilt effect -- a spotlight is
 * harmless on touch, a tilt effect driven by "hover" makes no sense
 * without a real pointer).
 */
(function () {
  const reducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reducedMotion) return;

  // ---- 1. Cursor spotlight ------------------------------------------------
  const spotlight = document.createElement('div');
  spotlight.className = 'cursor-spotlight';
  spotlight.setAttribute('aria-hidden', 'true');
  document.body.prepend(spotlight);

  let rafPending = false;
  let lastX = window.innerWidth / 2;
  let lastY = window.innerHeight / 2;

  function applyCursorVars() {
    document.documentElement.style.setProperty('--cursor-x', lastX + 'px');
    document.documentElement.style.setProperty('--cursor-y', lastY + 'px');
    rafPending = false;
  }

  window.addEventListener('pointermove', (e) => {
    lastX = e.clientX;
    lastY = e.clientY;
    if (!rafPending) {
      rafPending = true;
      requestAnimationFrame(applyCursorVars);
    }
  }, { passive: true });

  // ---- 2. Card tilt --------------------------------------------------------
  // Only on devices with a real pointer and hover support -- a touch
  // device has no "hover" state for this to react to.
  const hasFinePointer = window.matchMedia && window.matchMedia('(pointer: fine)').matches;
  if (!hasFinePointer) return;

  const MAX_TILT_DEG = 6;
  let activeCard = null;

  function tiltFor(card, clientX, clientY) {
    const rect = card.getBoundingClientRect();
    const px = (clientX - rect.left) / rect.width;  // 0..1
    const py = (clientY - rect.top) / rect.height;   // 0..1
    const rotateY = (px - 0.5) * (MAX_TILT_DEG * 2);
    const rotateX = (0.5 - py) * (MAX_TILT_DEG * 2);
    card.style.transform = `perspective(900px) rotateX(${rotateX.toFixed(2)}deg) rotateY(${rotateY.toFixed(2)}deg) scale3d(1.015, 1.015, 1.015)`;
  }

  function resetTilt(card) {
    card.style.transform = '';
  }

  // Event delegation on document, not per-card listeners -- results and
  // candidate cards are re-rendered/replaced wholesale via innerHTML as
  // jobs complete (see index.html's renderResults/renderInProgress), so
  // binding directly to individual card elements would silently stop
  // working the moment they're replaced. Delegation on a stable ancestor
  // needs no re-binding, ever.
  document.addEventListener('pointermove', (e) => {
    const card = e.target.closest('.card, .candidate-card');
    if (card !== activeCard) {
      if (activeCard) resetTilt(activeCard);
      activeCard = card;
    }
    if (card) tiltFor(card, e.clientX, e.clientY);
  }, { passive: true });

  document.addEventListener('pointerleave', () => {
    if (activeCard) {
      resetTilt(activeCard);
      activeCard = null;
    }
  }, { passive: true });
})();
