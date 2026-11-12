// EchoLabs landing page: player, scroll story, charts and receipt.
// Everything drawn here comes from site/data/*.json, generated from real runs
// by scripts/build_site.py.

const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;
const SVG = "http://www.w3.org/2000/svg";
const STEM = { vocals: "var(--vocals)", drums: "var(--drums)", bass: "var(--bass)", other: "var(--other)" };

document.documentElement.classList.add("js");

const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const lerp = (a, b, t) => a + (b - a) * t;
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const fmtTime = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
const signed = (n) => (n > 0 ? `+${n}` : `${n}`.replace("-", "−"));
const el = (tag, attrs = {}, parent) => {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
};

/* ---------- Kinetic headline: split into letters for the load animation ---------- */
function splitHeadline() {
  let i = 0;
  for (const line of document.querySelectorAll(".kinetic .line")) {
    const words = line.textContent.split(" ");
    line.textContent = "";
    words.forEach((word, w) => {
      const span = document.createElement("span");
      span.style.whiteSpace = "nowrap";
      for (const ch of word) {
        const c = document.createElement("span");
        c.className = "ch";
        c.textContent = ch;
        c.style.setProperty("--i", i++);
        span.appendChild(c);
      }
      line.appendChild(span);
      if (w < words.length - 1) line.appendChild(document.createTextNode(" "));
    });
  }
}

/* ---------- Player ---------- */
function player(clips) {
  const root = document.querySelector(".player");
  const pairsEl = root.querySelector(".pairs");
  const playBtn = root.querySelector(".play");
  const canvas = root.querySelector(".wave");
  const seek = root.querySelector(".seek");
  const timeEl = root.querySelector(".time");
  const facts = root.querySelector(".facts");
  const versionBtns = [...root.querySelectorAll(".versions button")];

  let pair = 0;
  let mode = "beatwarp";
  const audios = clips.map((c) =>
    Object.fromEntries(Object.entries(c.takes).map(([m, t]) => {
      const a = new Audio();
      a.preload = "none";
      a.src = t.src;
      return [m, a];
    })),
  );
  const current = () => audios[pair][mode];
  const take = () => clips[pair].takes[mode];

  clips.forEach((c, i) => {
    const b = document.createElement("button");
    b.type = "button";
    b.role = "tab";
    b.textContent = `${c.vocals_from.artist}'s vocals on ${c.beat_from.artist}'s beat`;
    b.setAttribute("aria-selected", i === 0);
    b.addEventListener("click", () => selectPair(i));
    pairsEl.appendChild(b);
  });

  function renderFacts() {
    const t = take();
    const shifted = t.plan.semitones !== 0;
    const items = [
      [`${Math.round(t.vocals.tempo_bpm)} → ${Math.round(t.beat.tempo_bpm)} BPM`, ""],
      [`${t.vocals.key} → ${t.beat.key}`, ""],
      [shifted ? `Vocals moved ${signed(t.plan.semitones)} semitones` : "No pitch shift", ""],
      [t.plan.mode === "beatwarp" ? `Stretched beat by beat (${t.plan.n_warp_segments} beats)` : "No time stretch", ""],
      [t.match.key_relation === "clash" ? "Keys clash" : "Keys match", t.match.key_relation === "clash" ? "clash" : "match"],
    ];
    facts.replaceChildren(...items.map(([text, cls]) => {
      const li = document.createElement("li");
      li.textContent = text;
      if (cls) li.className = cls;
      return li;
    }));
  }

  function draw() {
    const dpr = devicePixelRatio || 1;
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w) return;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    const t = take();
    const peaks = t.peaks;
    const a = current();
    const dur = a.duration || 30;
    const played = (a.currentTime || 0) / dur;
    const styles = getComputedStyle(document.documentElement);
    const text = styles.getPropertyValue("--text").trim();
    const line = styles.getPropertyValue("--line").trim();
    const vocals = styles.getPropertyValue("--vocals").trim();
    const step = w / peaks.length;
    const barW = Math.max(1, step * 0.62);
    peaks.forEach((p, i) => {
      const bh = Math.max(2, p * (h - 14));
      ctx.fillStyle = i / peaks.length < played ? text : line;
      ctx.fillRect(i * step, (h - bh) / 2, barW, bh);
    });
    const vx = (t.vocals_enter_s / dur) * w;
    ctx.fillStyle = vocals;
    ctx.fillRect(vx, 0, 2, h);
    ctx.font = '600 11px "Bricolage Grotesque", system-ui';
    ctx.fillText("vocals in", Math.min(vx + 6, w - 52), 11);
  }

  function sync() {
    const a = current();
    seek.value = a.currentTime || 0;
    timeEl.textContent = fmtTime(a.currentTime || 0);
    playBtn.setAttribute("aria-pressed", !a.paused);
    playBtn.setAttribute("aria-label", a.paused ? "Play" : "Pause");
    draw();
  }

  function loop() {
    sync();
    if (!current().paused) requestAnimationFrame(loop);
  }

  // Buffer the other version of this pair as soon as one plays, so switching
  // can seek straight to the same moment instead of waiting for a download.
  function warmOther() {
    for (const [m, a] of Object.entries(audios[pair])) {
      if (m !== mode && a.preload !== "auto") {
        a.preload = "auto";
        a.load();
      }
    }
  }

  function switchTo(nextPair, nextMode) {
    const prev = current();
    const wasPlaying = !prev.paused;
    const t = prev.currentTime || 0;
    prev.pause();
    pair = nextPair;
    mode = nextMode;
    const a = current();
    a.preload = "auto";
    const start = () => {
      a.currentTime = t;
      if (wasPlaying) a.play().then(loop).catch(() => {});
      sync();
    };
    // Seeking needs the clip's metadata; the server's range support does the rest.
    if (a.readyState >= 1) start();
    else {
      a.addEventListener("loadedmetadata", start, { once: true });
      a.load();
    }
    if (wasPlaying) warmOther();
    renderFacts();
    sync();
  }

  function selectPair(i) {
    [...pairsEl.children].forEach((b, j) => b.setAttribute("aria-selected", i === j));
    const prev = current();
    prev.pause();
    prev.currentTime = 0;
    switchTo(i, mode);
  }

  versionBtns.forEach((b) =>
    b.addEventListener("click", () => {
      versionBtns.forEach((o) => o.setAttribute("aria-checked", o === b));
      switchTo(pair, b.dataset.mode);
    }),
  );

  playBtn.addEventListener("click", () => {
    const a = current();
    if (a.paused) {
      a.preload = "auto";
      a.play().then(loop).catch(() => {});
      warmOther();
    } else {
      a.pause();
    }
    sync();
  });
  seek.addEventListener("input", () => {
    const a = current();
    const t = Number(seek.value);
    // A clip that hasn't loaded yet can't seek; load its metadata first.
    if (a.readyState >= 1) a.currentTime = t;
    else {
      a.preload = "auto";
      a.addEventListener("loadedmetadata", () => { a.currentTime = t; sync(); }, { once: true });
      a.load();
    }
    sync();
  });
  for (const pairAudios of audios) {
    for (const a of Object.values(pairAudios)) a.addEventListener("ended", sync);
  }
  new ResizeObserver(draw).observe(canvas);
  renderFacts();
  sync();
}

/* ---------- Scroll story ---------- */
function story(data) {
  const svg = document.getElementById("scene");
  const X0 = 60, W = 880;
  const N = data.a.mix.length;
  const xs = (t) => X0 + W * t;

  // Mirrored waveform path from peaks; xmap remaps normalised time.
  const wavePath = (peaks, amp, xmap = (t) => t) => {
    let top = "", bottom = "";
    for (let i = 0; i < peaks.length; i++) {
      const x = xs(xmap(i / (peaks.length - 1))).toFixed(1);
      const y = (peaks[i] * amp).toFixed(1);
      top += `${i ? "L" : "M"}${x},${-y}`;
      bottom = `L${x},${y}` + bottom;
    }
    return `${top}${bottom}Z`;
  };

  const lanesA = { vocals: 120, drums: 215, bass: 310, other: 405 };
  const MIX_Y = 262;

  const gGridA = el("g", {}, svg);
  const gGridB = el("g", {}, svg);
  const mix = el("path", { d: wavePath(data.a.mix, 90), fill: "var(--text)" }, svg);
  const stemsA = {};
  for (const k of Object.keys(lanesA)) {
    stemsA[k] = el("path", { d: wavePath(data.a.stems[k], 40), fill: STEM[k] }, svg);
  }
  const bDrums = el("path", { d: wavePath(data.b.stems.drums, 32), fill: STEM.drums }, svg);
  const bBass = el("path", { d: wavePath(data.b.stems.bass, 32), fill: STEM.bass }, svg);
  const bOther = el("path", { d: wavePath(data.b.stems.other, 32), fill: STEM.other }, svg);

  // Beat grids. A window starts on a downbeat, so every 4th beat is a downbeat.
  const gridA = data.a.beats.map((t, i) =>
    el("line", { x1: xs(t), x2: xs(t), stroke: "var(--text)", "stroke-width": i % 4 === 0 ? 2.5 : 1, "stroke-opacity": i % 4 === 0 ? 0.9 : 0.45 }, gGridA),
  );
  const gridB = data.b.beats.map((t, i) =>
    el("line", { x1: xs(t), x2: xs(t), y1: 80, y2: 290, stroke: "var(--drums)", "stroke-width": i % 4 === 0 ? 2.5 : 1, "stroke-opacity": i % 4 === 0 ? 0.9 : 0.5 }, gGridB),
  );

  const labelA = el("text", { x: X0, y: 42, class: "sc-big" }, svg);
  labelA.textContent = `${data.a.song.tempo} BPM in ${data.a.song.key}`;
  const subA = el("text", { x: X0, y: 66, class: "sc-label sc-sub" }, svg);
  subA.textContent = `${data.a.song.artist}, 4 bars. Thick lines are the first beat of each bar.`;

  // Camelot wheel: 12 outer (major, B) and 12 inner (minor, A) positions, 12 at the top.
  const wheel = el("g", { transform: "translate(500 300)" }, svg);
  const C = (n, r) => {
    const ang = ((n % 12) * 30 - 90) * (Math.PI / 180);
    return [r * Math.cos(ang), r * Math.sin(ang)];
  };
  const arc = (n, r0, r1) => {
    const a0 = (((n % 12) * 30 - 105) * Math.PI) / 180, a1 = (((n % 12) * 30 - 75) * Math.PI) / 180;
    const p = (r, a) => `${(r * Math.cos(a)).toFixed(1)},${(r * Math.sin(a)).toFixed(1)}`;
    return `M${p(r1, a0)} A${r1},${r1} 0 0 1 ${p(r1, a1)} L${p(r0, a1)} A${r0},${r0} 0 0 0 ${p(r0, a0)}Z`;
  };
  const fromN = parseInt(data.a.song.camelot), toN = parseInt(data.match.camelot_after);
  const segs = {};
  for (let n = 1; n <= 12; n++) {
    for (const [ring, r0, r1] of [["B", 168, 232], ["A", 100, 164]]) {
      const id = `${n}${ring}`;
      segs[id] = el("path", { d: arc(n, r0, r1), fill: "var(--ink-3)", stroke: "var(--ink)", "stroke-width": 3 }, wheel);
      const [tx, ty] = C(n, (r0 + r1) / 2);
      const label = el("text", { x: tx, y: ty, class: "sc-wheel-text" }, wheel);
      label.textContent = id;
      segs[id].label = label;
    }
  }
  for (const [id, colour] of [[`${fromN}A`, "var(--vocals)"], [`${toN}A`, "var(--drums)"]]) {
    segs[id].setAttribute("fill", colour);
    segs[id].label.style.fill = "var(--ink)";
    segs[id].label.style.fontWeight = 800;
  }
  const shiftArc = el("path", { fill: "none", stroke: "var(--text)", "stroke-width": 5, "stroke-linecap": "round", "stroke-dasharray": "0.1 11" }, wheel);
  const wheelMid = el("text", { x: 0, y: -6, class: "sc-mid", "text-anchor": "middle" }, wheel);
  wheelMid.textContent = `${signed(data.match.semitones)} semitones`;
  const wheelSub = el("text", { x: 0, y: 20, class: "sc-label", "text-anchor": "middle" }, wheel);
  wheelSub.textContent = `${data.a.song.camelot} to ${data.match.camelot_after}`;
  const wheelTempo = el("text", { x: 0, y: 270, class: "sc-label", "text-anchor": "middle" }, wheel);
  wheelTempo.textContent = `Tempo: ${data.a.song.tempo} → ${data.b.song.tempo} BPM, stretched ×${data.match.stretch.toFixed(3)} on average`;

  // Where each vocal beat lands relative to the new beat, in ms.
  const aSec = data.warp.a.map((t) => t * data.a.seconds);
  const oSec = data.warp.out.map((t) => t * data.b.seconds);
  const offsets = {
    naive: aSec.map((a, i) => (a - oSec[i]) * 1000),
    global: aSec.map((a, i) => (a / data.match.stretch - oSec[i]) * 1000),
  };
  const CH_Y = 470, MS = 1.15;
  const chart = el("g", {}, svg);
  el("rect", { x: X0, y: CH_Y - 20 * MS, width: W, height: 40 * MS, fill: "var(--bass)", "fill-opacity": 0.12, rx: 6 }, chart);
  el("line", { x1: X0, x2: X0 + W, y1: CH_Y, y2: CH_Y, stroke: "var(--bass)", "stroke-opacity": 0.6 }, chart);
  el("text", { x: X0 + W - 10, y: CH_Y + 80 * MS + 14, class: "sc-small", "text-anchor": "end" }, chart).textContent = "within ±20 ms sounds like one hit";
  el("text", { x: X0, y: CH_Y - 80 * MS - 16, class: "sc-label" }, chart).textContent = "Where each sung beat lands, in ms from the new beat";
  const series = {};
  const seriesStyle = { naive: { stroke: "var(--muted)" }, global: { stroke: "var(--other)" }, warp: { stroke: "var(--vocals)" } };
  // The key for these lines lives in the step-4 text (HTML), so it stays readable on phones.
  for (const [k, s] of Object.entries(seriesStyle)) {
    series[k] = el("polyline", { fill: "none", stroke: s.stroke, "stroke-width": k === "warp" ? 4 : 2.5, "stroke-linejoin": "round" }, chart);
  }
  const pts = (vals) => data.warp.out.map((t, i) => `${xs(t).toFixed(1)},${(CH_Y - clamp(vals[i], -80, 80) * MS).toFixed(1)}`).join(" ");

  const labelB = el("text", { x: X0, y: 42, class: "sc-big" }, svg);
  labelB.textContent = `New beat: ${data.b.song.tempo} BPM in ${data.b.song.key}`;
  const subB = el("text", { x: X0, y: 66, class: "sc-label sc-sub" }, svg);
  subB.textContent = `${data.b.song.artist}. Vocals moved ${signed(data.match.semitones)} semitones to match.`;
  const caption = el("text", { x: 500, y: 480, class: "sc-mid", "text-anchor": "middle" }, svg);
  caption.textContent = "One mix, loudness-matched, with its receipt";

  const warpMap = (p) => (t) => {
    const a = data.warp.a, o = data.warp.out;
    let k = 0;
    while (k < a.length - 2 && t > a[k + 1]) k++;
    const m = o[k] + ((t - a[k]) / (a[k + 1] - a[k])) * (o[k + 1] - o[k]);
    return lerp(t, m, p);
  };

  const steps = [...document.querySelectorAll(".step")];
  let target = 0, shown = REDUCED ? 1 : 0;

  function render(P) {
    const s1 = ease(clamp(P)), s2 = ease(clamp(P - 1));
    const wheelIn = ease(clamp((P - 2) / 0.3)) * (1 - ease(clamp((P - 2.8) / 0.25)));
    const toWarp = ease(clamp((P - 3) / 0.35));
    const warpP = ease(clamp((P - 3.35) / 0.5));
    const s5 = ease(clamp(P - 4));
    const dim = 1 - 0.95 * wheelIn;

    mix.setAttribute("transform", `translate(0 ${MIX_Y})`);
    mix.setAttribute("opacity", (1 - s1) * 0.9);

    for (const [k, y] of Object.entries(lanesA)) {
      const yy = k === "vocals" ? lerp(lerp(MIX_Y, y, s1), 185, toWarp) : lerp(MIX_Y, y, s1);
      const fade = k === "vocals" ? 1 : 1 - toWarp;
      const merged = k === "vocals" ? lerp(yy, 330, s5) : yy;
      stemsA[k].setAttribute("transform", `translate(0 ${merged}) scale(1 ${k === "vocals" ? lerp(1, 1.7, s5) : 1})`);
      stemsA[k].setAttribute("opacity", s1 * dim * fade * (k === "vocals" ? 1 : 0.9));
    }
    stemsA.vocals.setAttribute("d", wavePath(data.a.stems.vocals, 40, warpMap(warpP)));

    const nA = gridA.length;
    gridA.forEach((ln, i) => {
      const q = clamp((s2 * (nA + 6) - i) / 6);
      const x = xs(warpMap(warpP)(data.a.beats[i]));
      const y1 = lerp(80, 150, toWarp), y2full = lerp(445, 220, toWarp);
      ln.setAttribute("x1", x);
      ln.setAttribute("x2", x);
      ln.setAttribute("y1", y1);
      ln.setAttribute("y2", lerp(y1, y2full, q));
    });
    gGridA.setAttribute("opacity", dim * (1 - s5) * (1 - 0.5 * toWarp));
    labelA.setAttribute("opacity", s2 * (1 - wheelIn) * (1 - toWarp) * (P < 2.9 ? 1 : 0));
    subA.setAttribute("opacity", s2 * (1 - wheelIn) * (1 - toWarp) * (P < 2.9 ? 1 : 0));

    wheel.setAttribute("opacity", wheelIn);
    wheel.setAttribute("transform", `translate(500 300) scale(${lerp(0.92, 1, wheelIn)})`);
    const p3 = ease(clamp((P - 2.15) / 0.45));
    if (fromN !== toN) {
      const steps12 = (toN - fromN + 12) % 12;
      const a0 = ((fromN % 12) * 30 - 90) * (Math.PI / 180);
      const a1 = a0 + steps12 * 30 * (Math.PI / 180) * p3;
      const r = 88;
      const big = steps12 * 30 * p3 > 180 ? 1 : 0;
      shiftArc.setAttribute("d", `M${r * Math.cos(a0)},${r * Math.sin(a0)} A${r},${r} 0 ${big} 1 ${r * Math.cos(a1)},${r * Math.sin(a1)}`);
    }

    for (const [path, y] of [[bDrums, 252], [bBass, 330], [bOther, 330]]) {
      const isDrums = path === bDrums;
      path.setAttribute("transform", `translate(0 ${lerp(y, 330, s5)}) scale(1 ${lerp(1, 2.1, s5)})`);
      path.setAttribute("opacity", (isDrums ? toWarp : 0) * (1 - s5) + s5 * 0.85);
    }
    gGridB.setAttribute("opacity", toWarp * (1 - s5));
    labelB.setAttribute("opacity", toWarp * (1 - s5));
    subB.setAttribute("opacity", toWarp * (1 - s5));

    chart.setAttribute("opacity", ease(clamp((P - 3.2) / 0.3)) * (1 - s5));
    series.naive.setAttribute("points", pts(offsets.naive));
    series.global.setAttribute("points", pts(offsets.global));
    series.warp.setAttribute("points", pts(offsets.global.map((v) => v * (1 - warpP))));

    caption.setAttribute("opacity", s5);
  }

  function progress() {
    const body = document.querySelector(".story-body");
    const r = body.getBoundingClientRect();
    const vh = innerHeight;
    const raw = (vh * 0.55 - r.top) / (r.height - vh * 0.6);
    return clamp(raw) * 5;
  }

  function tick() {
    target = progress();
    const active = Math.min(4, Math.floor(target));
    steps.forEach((s, i) => s.classList.toggle("is-active", i === active));
    if (REDUCED) {
      shown = active + 1; // jump straight to each step's finished picture
    } else {
      shown += (target - shown) * 0.14;
      if (Math.abs(target - shown) < 0.001) shown = target;
    }
    render(shown);
    if (!REDUCED && Math.abs(target - shown) > 0.001) requestAnimationFrame(tick);
  }
  addEventListener("scroll", () => requestAnimationFrame(tick), { passive: true });
  addEventListener("resize", () => requestAnimationFrame(tick));
  tick();
}

/* ---------- Results charts ---------- */
function charts(n) {
  const bar = (label, sub, value, max, text, hero) => {
    const row = document.createElement("div");
    row.className = `bar${hero ? " hero-bar" : ""}`;
    row.innerHTML = `<div class="bar-label">${label}${sub ? `<small>${sub}</small>` : ""}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${(100 * value) / max}%">${text}</div></div>`;
    return row;
  };
  const sep = document.querySelector('[data-chart="separation"]');
  sep.append(
    bar("EchoLabs", "Demucs neural separator", n.separation.htdemucs.vocals, 12, `${n.separation.htdemucs.vocals.toFixed(1)} dB`, true),
    bar("Classic signal processing", "REPET-SIM", n.separation.repet_sim.vocals, 12, `${n.separation.repet_sim.vocals.toFixed(1)} dB`),
  );

  const sync = document.querySelector('[data-chart="sync"]');
  const f = n.sync.f;
  sync.append(
    bar("Naive overlay", "no stretching", f.naive, 1, f.naive.toFixed(2)),
    bar("One global stretch", "a single tempo ratio", f.global, 1, f.global.toFixed(2)),
    bar("EchoLabs beat-warp", "every beat stretched", f.beatwarp, 1, f.beatwarp.toFixed(2), true),
  );
  for (const track of sync.querySelectorAll(".bar-track")) {
    const c = document.createElement("div");
    c.className = "bar-ceiling";
    c.style.left = `${n.sync.ceiling * 100}%`;
    track.appendChild(c);
  }
  const first = sync.querySelector(".bar-ceiling");
  first.innerHTML = `<span>best possible here: ${n.sync.ceiling.toFixed(2)}</span>`;

  const clash = document.querySelector('[data-chart="clash"]');
  clash.append(
    bar("Naive overlay", "keys left as they are", n.sync.clash.naive, 1, `${Math.round(n.sync.clash.naive * 100)}%`),
    bar("EchoLabs", "vocals moved to a matching key", n.sync.clash.beatwarp, 1, `${Math.round(n.sync.clash.beatwarp * 100)}%`, true),
  );

  const fill = (key, text) => {
    const node = document.querySelector(`[data-fill="${key}"]`);
    if (node) node.textContent = text;
  };
  fill("limit-beatthis", `A newer neural beat tracker (Beat This!) scored ${n.sync.beatthis_beatwarp.toFixed(2)} against ${f.beatwarp.toFixed(2)} for the classic one in this test, so it stays optional.`);
  const k = n.key["harmonic/krumhansl"].mirex_weighted;
  fill("limit-key", `Key detection scores ${k.toFixed(3)} on GiantSteps (${n.key.n} tracks). Learned key models reach about 0.74, so this is a solid baseline, not the state of the art.`);
}

/* ---------- Receipt ---------- */
function receipt(m) {
  const dl = document.querySelector(".receipt-body");
  const v = m.sources.vocals, b = m.sources.instrumental;
  const rows = [
    ["Vocals from", `${v.file}`],
    ["File hash", v.sha1_16],
    ["Beat from", `${b.file}`],
    ["File hash", b.sha1_16],
    null,
    ["Detected", `${v.analysis.tempo_bpm} → ${b.analysis.tempo_bpm} BPM, ${v.analysis.camelot} → ${b.analysis.camelot}`],
    ["Stretch applied", `×${m.plan.mean_stretch_applied}, beat by beat (${m.plan.n_warp_segments} beats)`],
    ["Pitch shift", `${signed(m.plan.semitones)} semitones`],
    ["Loudness", `${m.output_lufs} LUFS`],
    null,
    ["AI-generated", m.ai_generated_derivative ? "Yes" : "No"],
    ["Made by", m.generated_by],
  ];
  for (const r of rows) {
    if (!r) {
      const hr = document.createElement("div");
      hr.className = "rule";
      dl.appendChild(hr);
      continue;
    }
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = r[0];
    dd.textContent = r[1];
    dl.append(dt, dd);
  }
}

/* ---------- Fill story copy from data ---------- */
function storyCopy(s) {
  const fill = (key, text) => {
    const node = document.querySelector(`[data-fill="${key}"]`);
    if (node) node.textContent = text;
  };
  const f = s.warp.factors;
  fill("a-summary", `This song: ${Math.round(s.a.song.tempo)} BPM in ${s.a.song.key}.`);
  fill("match-summary", `The other song is ${s.b.song.tempo} BPM in ${s.b.song.key}.`);
  fill(
    "warp-summary",
    `Over these 16 beats the stretch runs from ×${Math.min(...f).toFixed(2)} to ×${Math.max(...f).toFixed(2)}. A naive overlay drifts up to ${Math.round(
      Math.max(...s.warp.a.map((t, i) => Math.abs(t * s.a.seconds - s.warp.out[i] * s.b.seconds))) * 1000,
    )} ms off the beat.`,
  );
}

/* ---------- Boot ---------- */
splitHeadline();
const get = (p) => fetch(p).then((r) => {
  if (!r.ok) throw new Error(`${p}: ${r.status}`);
  return r.json();
});
Promise.all([get("data/clips.json"), get("data/story.json"), get("data/numbers.json")])
  .then(([clips, s, n]) => {
    player(clips);
    story(s);
    storyCopy(s);
    charts(n);
    return get(clips[0].takes.beatwarp.manifest).then(receipt);
  })
  .catch((err) => console.error("EchoLabs page data failed to load:", err));
