/**
 * Termnova motion — pointer parallax on the Ask paper stack,
 * GSAP entrance for the hero sheet, clip-path already in CSS.
 * Techniques: depth parallax, float-loop (CSS), view birth (CSS).
 */
(function initDeskMotion() {
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const coarse = window.matchMedia("(pointer: coarse)").matches;

  if (typeof gsap !== "undefined") {
    if (reduced) {
      gsap.globalTimeline.timeScale(0);
    } else {
      const hero = document.querySelector(".paper-hero");
      if (hero) {
        gsap.from(hero, {
          y: 28,
          opacity: 0,
          duration: 0.9,
          ease: "power3.out",
        });
        gsap.from(".deck-card", {
          y: 16,
          opacity: 0,
          duration: 0.55,
          stagger: 0.08,
          delay: 0.25,
          ease: "power2.out",
        });
      }
    }
  }

  if (reduced || coarse) return;

  const scene = document.querySelector("[data-scene='ask-empty']");
  if (!scene) return;

  const layers = scene.querySelectorAll("[data-depth]");
  const factors = { 0: 6, 1: 10, 2: 16, 3: 22, 4: 8 };
  let raf = 0;
  let targetX = 0;
  let targetY = 0;
  let curX = 0;
  let curY = 0;

  function tick() {
    raf = 0;
    curX += (targetX - curX) * 0.08;
    curY += (targetY - curY) * 0.08;
    layers.forEach((layer) => {
      const depth = layer.dataset.depth;
      const f = factors[depth] || 10;
      layer.style.transform = `translate3d(${curX * f}px, ${curY * f}px, 0)`;
    });
    if (Math.abs(targetX - curX) > 0.001 || Math.abs(targetY - curY) > 0.001) {
      raf = requestAnimationFrame(tick);
    }
  }

  scene.addEventListener(
    "pointermove",
    (event) => {
      const rect = scene.getBoundingClientRect();
      targetX = (event.clientX - rect.left) / rect.width - 0.5;
      targetY = (event.clientY - rect.top) / rect.height - 0.5;
      if (!raf) raf = requestAnimationFrame(tick);
    },
    { passive: true }
  );

  scene.addEventListener(
    "pointerleave",
    () => {
      targetX = 0;
      targetY = 0;
      if (!raf) raf = requestAnimationFrame(tick);
    },
    { passive: true }
  );
})();
