// Progressive enhancement for the public site: scroll-linked effects, reveals and the small
// interactive demos on the home page. Every page works without it. It makes no network
// requests, stores nothing and only writes text with textContent and CSS custom properties.
// With prefers-reduced-motion it leaves every illustration in its final, still state.

const doc = document;
const root = doc.documentElement;
const reduceQuery = globalThis.matchMedia("(prefers-reduced-motion: reduce)");
const finePointer = globalThis.matchMedia("(hover: hover) and (pointer: fine)");
let motion = !reduceQuery.matches;

root.classList.add("js");
root.classList.toggle("motion", motion);
reduceQuery.addEventListener("change", () => {
  motion = !reduceQuery.matches;
  root.classList.toggle("motion", motion);
  schedule();
});

const clamp = (value, min = 0, max = 1) => Math.min(max, Math.max(min, value));
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function onceVisible(element, callback, options = { threshold: 0.35 }) {
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      observer.disconnect();
      callback();
    }
  }, options);
  observer.observe(element);
}

// Header: solid once the page scrolls, tucked away while reading down, back on scroll up.
const header = doc.querySelector(".site-header");
let lastY = globalThis.scrollY;

function updateHeader(y) {
  if (!header) return;
  header.classList.toggle("is-scrolled", y > 8);
  if (Math.abs(y - lastY) < 6) return;
  const hide = y > lastY && y > 520 && !header.contains(doc.activeElement);
  header.classList.toggle("is-hidden", hide);
  lastY = y;
}
header?.addEventListener("focusin", () => header.classList.remove("is-hidden"));

// Scroll progress: [data-progress] gets --p from 0 to 1 while it crosses the viewport
// ("exit" measures from the top of the page until the element has scrolled away).
const tracked = new Set();
const progressObserver = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    if (entry.isIntersecting) tracked.add(entry.target);
    else tracked.delete(entry.target);
  }
  schedule();
}, { rootMargin: "15% 0px" });
for (const element of doc.querySelectorAll("[data-progress]")) progressObserver.observe(element);

function updateProgress() {
  const height = globalThis.innerHeight;
  const measured = [...tracked].map((element) => [element, element.getBoundingClientRect()]);
  for (const [element, rect] of measured) {
    const exit = element.getAttribute("data-progress") === "exit";
    const progress = exit ? clamp(-rect.top / Math.max(1, rect.height * 0.9)) : clamp((height - rect.top) / (height + rect.height));
    element.style.setProperty("--p", progress.toFixed(4));
  }
}

let queued = false;
function schedule() {
  if (queued) return;
  queued = true;
  requestAnimationFrame(() => {
    queued = false;
    updateHeader(globalThis.scrollY);
    updateProgress();
    updateStories();
  });
}
globalThis.addEventListener("scroll", schedule, { passive: true });
globalThis.addEventListener("resize", schedule);

// Reveals: [data-reveal] and [data-stagger] groups get .is-in the first time they show up.
for (const group of doc.querySelectorAll("[data-stagger]")) {
  [...group.children].forEach((child, index) => child.style.setProperty("--i", String(index)));
}
const revealObserver = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue;
    entry.target.classList.add("is-in");
    revealObserver.unobserve(entry.target);
  }
}, { rootMargin: "0px 0px -10% 0px", threshold: 0.08 });
for (const element of doc.querySelectorAll("[data-reveal], [data-stagger]")) revealObserver.observe(element);

// Looping illustrations only animate while on screen.
const liveObserver = new IntersectionObserver((entries) => {
  for (const entry of entries) entry.target.classList.toggle("is-live", entry.isIntersecting);
});
for (const element of doc.querySelectorAll("[data-live]")) liveObserver.observe(element);

// Story: the sticky stage follows the step closest to the middle of the viewport.
const stories = [...doc.querySelectorAll("[data-story]")].map((story) => ({
  stage: story.querySelector("[data-stage]"),
  steps: [...story.querySelectorAll("[data-step]")],
  current: null,
})).filter((story) => story.stage && story.steps.length > 0);

function updateStories() {
  const middle = globalThis.innerHeight / 2;
  for (const story of stories) {
    let best = story.steps[0];
    let distance = Infinity;
    for (const step of story.steps) {
      const rect = step.getBoundingClientRect();
      const gap = Math.abs((rect.top + rect.bottom) / 2 - middle);
      if (gap < distance) {
        distance = gap;
        best = step;
      }
    }
    if (best === story.current) continue;
    story.current = best;
    story.stage.setAttribute("data-active", best.getAttribute("data-step") ?? "1");
    for (const step of story.steps) step.classList.toggle("is-active", step === best);
  }
}

// Privacy lens: the same files as you see them and as Telegram stores them.
const HEX = "0123456789abcdef";

function cipherName(text) {
  let hash = 2166136261;
  for (const char of text) hash = Math.imul(hash ^ (char.codePointAt(0) ?? 0), 16777619) >>> 0;
  let out = "";
  while (out.length < 24) {
    hash = Math.imul(hash ^ (hash >>> 15), 2246822507) >>> 0;
    hash ^= hash >>> 13;
    out += (hash & 0xffff).toString(16).padStart(4, "0");
  }
  return `${out.slice(0, 10)}…${out.slice(-6)}`;
}

function scramble(element, target) {
  const token = Symbol("scramble");
  element.scrambleToken = token;
  if (!motion) {
    element.textContent = target;
    return;
  }
  const start = performance.now();
  const duration = 520;
  const step = (now) => {
    if (element.scrambleToken !== token) return;
    const progress = clamp((now - start) / duration);
    const settled = Math.floor(target.length * progress);
    let text = target.slice(0, settled);
    for (let index = settled; index < target.length; index += 1) {
      text += target[index] === " " ? " " : HEX[Math.floor(Math.random() * HEX.length)];
    }
    element.textContent = text;
    if (progress < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

for (const lens of doc.querySelectorAll("[data-lens]")) {
  const buttons = [...lens.querySelectorAll("[data-lens-mode]")];
  const fields = [...lens.querySelectorAll("[data-cipher]")].map((element) => ({
    element,
    plain: element.textContent ?? "",
    cipher: element.getAttribute("data-cipher") || cipherName(element.textContent ?? ""),
  }));
  let touched = false;
  const setMode = (mode) => {
    const cipher = mode === "cipher";
    lens.classList.toggle("is-cipher", cipher);
    for (const button of buttons) button.setAttribute("aria-pressed", String(button.getAttribute("data-lens-mode") === mode));
    for (const field of fields) scramble(field.element, cipher ? field.cipher : field.plain);
  };
  for (const button of buttons) {
    button.addEventListener("click", () => {
      touched = true;
      setMode(button.getAttribute("data-lens-mode") ?? "plain");
    });
  }
  const controls = lens.querySelector("[data-lens-controls]");
  if (controls) controls.hidden = false;
  onceVisible(lens, async () => {
    if (!motion) return;
    await wait(1400);
    if (!touched) setMode("cipher");
  }, { threshold: 0.6 });
}

// Pairing demo: the code types itself in, the emojis appear, the countdown runs.
for (const demo of doc.querySelectorAll("[data-pairing]")) {
  const code = demo.querySelector("[data-type]");
  const countdown = demo.querySelector("[data-countdown]");
  if (countdown) {
    let seconds = 581;
    setInterval(() => {
      if (!demo.classList.contains("is-live")) return;
      seconds = seconds <= 0 ? 599 : seconds - 1;
      countdown.textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
    }, 1000);
  }
  if (!code || !motion) {
    demo.classList.add("is-typed");
    continue;
  }
  const full = code.textContent ?? "";
  code.textContent = "";
  onceVisible(demo, async () => {
    for (let index = 1; index <= full.length; index += 1) {
      code.textContent = full.slice(0, index);
      await wait(full[index - 1] === "-" ? 160 : 70);
    }
    demo.classList.add("is-typed");
  });
}

// Search demo: a few queries type themselves and the matching result lights up.
for (const search of doc.querySelectorAll("[data-search-demo]")) {
  const field = search.querySelector("[data-typing]");
  const results = [...search.querySelectorAll("[data-result]")];
  const words = (field?.getAttribute("data-words") ?? "").split("|").filter(Boolean);
  if (!field || words.length === 0 || !motion) continue;
  const show = (index) => {
    for (const result of results) result.classList.toggle("is-match", result.getAttribute("data-result") === String(index));
  };
  onceVisible(search, async () => {
    for (let round = 0; ; round = (round + 1) % words.length) {
      while (!search.classList.contains("is-live") || !motion) await wait(400);
      const word = words[round];
      show(-1);
      for (let index = field.textContent.length; index >= 0; index -= 1) {
        field.textContent = field.textContent.slice(0, index);
        await wait(28);
      }
      for (let index = 1; index <= word.length; index += 1) {
        field.textContent = word.slice(0, index);
        await wait(75);
      }
      show(round);
      await wait(2200);
    }
  });
}

// Figures count up the first time they are seen.
const numberFormat = new Intl.NumberFormat(root.lang || "es");
for (const element of doc.querySelectorAll("[data-count]")) {
  const target = Number(element.getAttribute("data-count"));
  if (!motion || !Number.isFinite(target) || target === 0) continue;
  onceVisible(element, () => {
    const start = performance.now();
    const duration = 1100;
    const step = (now) => {
      const progress = clamp((now - start) / duration);
      const eased = 1 - (1 - progress) ** 4;
      element.textContent = numberFormat.format(Math.round(target * eased));
      if (progress < 1) requestAnimationFrame(step);
    };
    element.textContent = "0";
    requestAnimationFrame(step);
  }, { threshold: 0.8 });
}

// Downloads: point out the visitor's own system (desktop browsers only).
const agent = (globalThis.navigator?.userAgent ?? "").toLowerCase();
const platform = (globalThis.navigator?.userAgentData?.platform ?? globalThis.navigator?.platform ?? agent).toLowerCase();
const mobile = /android|iphone|ipad|ipod|mobile/u.test(agent);
const system = mobile ? null : /win/u.test(platform) ? "windows" : /mac/u.test(platform) ? "macos" : /linux|x11/u.test(platform) ? "linux" : null;
if (system) {
  for (const card of doc.querySelectorAll(`[data-os="${system}"]`)) {
    card.classList.add("is-yours");
    for (const badge of card.querySelectorAll("[data-os-badge]")) badge.hidden = false;
  }
}

// Hero: the box unwraps itself once at least part of it is on screen.
for (const stage of doc.querySelectorAll(".hero-stage")) {
  const query = stage.querySelector(".hb-query > span");
  const word = query?.textContent ?? "";
  if (query && motion) query.textContent = "";
  onceVisible(stage, async () => {
    stage.classList.add("is-open");
    if (!query || !motion) return;
    await wait(2900);
    for (let index = 1; index <= word.length; index += 1) {
      query.textContent = word.slice(0, index);
      await wait(85);
    }
  }, { threshold: 0.3 });
}

// Pointer effects: a gentle tilt on the hero box and a soft light that follows the cursor.
for (const element of doc.querySelectorAll("[data-tilt]")) {
  element.addEventListener("pointermove", (event) => {
    if (!motion || !finePointer.matches) return;
    const rect = element.getBoundingClientRect();
    element.style.setProperty("--tx", ((event.clientX - rect.left) / rect.width - 0.5).toFixed(3));
    element.style.setProperty("--ty", ((event.clientY - rect.top) / rect.height - 0.5).toFixed(3));
  });
  element.addEventListener("pointerleave", () => {
    element.style.setProperty("--tx", "0");
    element.style.setProperty("--ty", "0");
  });
}
for (const tile of doc.querySelectorAll(".tile")) {
  tile.addEventListener("pointermove", (event) => {
    if (!finePointer.matches) return;
    const rect = tile.getBoundingClientRect();
    tile.style.setProperty("--mx", `${Math.round(event.clientX - rect.left)}px`);
    tile.style.setProperty("--my", `${Math.round(event.clientY - rect.top)}px`);
  });
}

schedule();
