(() => {
  "use strict";
  const main = document.querySelector("main.trends");
  const dataEl = document.getElementById("trends-data");
  if (!main || !dataEl) return;
  const data = JSON.parse(dataEl.textContent);
  const items = new Map(data.items.map((it) => [it.id, it]));
  const LIB = "https://cdn.jsdelivr.net/npm/lightweight-charts@5.2.1/dist/lightweight-charts.standalone.production.js";
  const SLOTS = 6;
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

  // --- セクター / テーマ の切り替え --------------------------------------------------------
  let kind = main.dataset.kind || "s";
  const selected = { s: new Map(), t: new Map() }; // id -> color slot (1..6); colour follows the entity
  const kindTabs = document.querySelectorAll(".kindtabs [data-kind]");
  function setKind(k) {
    kind = k;
    main.dataset.kind = k;
    kindTabs.forEach((b) => b.setAttribute("aria-selected", String(b.dataset.kind === k)));
    if (!selected[k].size) defaultPick(k);
    syncPicks();
    draw();
  }
  kindTabs.forEach((b) => b.addEventListener("click", () => setKind(b.dataset.kind)));

  // --- 並べ替え ---------------------------------------------------------------------------
  document.querySelectorAll("table[data-sortable]").forEach((table) => {
    const heads = [...table.querySelectorAll(".sortbtn")];
    heads.forEach((btn, colIdx) => btn.addEventListener("click", () => {
      const desc = btn.getAttribute("aria-sort") !== "descending";
      heads.forEach((h) => h.removeAttribute("aria-sort"));
      btn.setAttribute("aria-sort", desc ? "descending" : "ascending");
      const body = table.tBodies[0];
      const rows = [...body.rows];
      const val = (r) => {
        const v = r.cells[colIdx + 1].dataset.v;
        return v === "" ? null : +v;
      };
      rows.sort((a, b) => {
        const va = val(a), vb = val(b);
        if (va === null) return 1;
        if (vb === null) return -1;
        return desc ? vb - va : va - vb;
      });
      body.append(...rows);
    }));
  });

  // --- 累積推移チャート ---------------------------------------------------------------------
  let range = "60";
  let chart = null;
  let libP = null;
  const box = document.getElementById("lc-chart");
  const msg = document.getElementById("lc-msg");
  const setMsg = (t) => { msg.textContent = t || ""; msg.hidden = !t; };
  const loadLib = () => libP || (libP = new Promise((ok, ng) => {
    if (window.LightweightCharts) return ok(window.LightweightCharts);
    const s = document.createElement("script");
    s.src = LIB; s.async = true;
    s.onload = () => ok(window.LightweightCharts);
    s.onerror = () => { libP = null; ng(new Error("チャート部品を読み込めませんでした")); };
    document.head.appendChild(s);
  }));

  function baseIndex() {
    const n = data.dates.length;
    if (range === "ytd") {
      const year = data.dates[n - 1].slice(0, 4);
      const first = data.dates.findIndex((d) => d.startsWith(year));
      return Math.max(0, first - 1); // previous year's last session = 100
    }
    return Math.max(0, n - 1 - +range);
  }

  function cumulative(daily, base) {
    const out = [];
    let level = 100;
    for (let i = base; i < daily.length; i++) {
      if (i > base && daily[i] != null) level *= 1 + daily[i] / 100;
      out.push({ time: data.dates[i], value: +level.toFixed(3) });
    }
    return out;
  }

  function freeSlot(map) {
    const used = new Set(map.values());
    for (let i = 1; i <= SLOTS; i++) if (!used.has(i)) return i;
    return null;
  }

  function defaultPick(k) {
    const picks = main.querySelectorAll(`.k-${k} .pick`);
    [...picks].slice(0, 5).forEach((p) => selected[k].set(p.dataset.id, freeSlot(selected[k])));
  }

  function syncPicks() {
    main.querySelectorAll(".pick").forEach((p) => {
      const slot = selected[p.dataset.id[0]].get(p.dataset.id);
      p.setAttribute("aria-pressed", String(!!slot));
      p.style.setProperty("--sw", slot ? `var(--c${slot})` : "transparent");
      if (!slot) p.querySelector(".pv").textContent = "";
    });
  }

  main.querySelectorAll(".pick").forEach((p) => p.addEventListener("click", () => {
    const map = selected[p.dataset.id[0]];
    if (map.has(p.dataset.id)) map.delete(p.dataset.id);
    else {
      const slot = freeSlot(map);
      if (!slot) { setMsg(`同時に表示できるのは${SLOTS}本までです。どれかを外してから選んでください。`); return; }
      map.set(p.dataset.id, slot);
    }
    setMsg("");
    syncPicks();
    draw();
  }));

  document.querySelectorAll("[data-lrange]").forEach((b) => b.addEventListener("click", () => {
    range = b.dataset.lrange;
    document.querySelectorAll("[data-lrange]").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
    draw();
  }));

  async function draw() {
    let LC;
    try { LC = await loadLib(); } catch (e) { setMsg(e.message + "。表の数値をご覧ください。"); return; }
    if (chart) { chart.remove(); chart = null; }
    chart = LC.createChart(box, {
      autoSize: true,
      layout: { background: { type: "solid", color: css("--surface") }, textColor: css("--ink-2"),
                fontFamily: css("--f-mono") || "monospace", fontSize: 11 },
      grid: { vertLines: { color: css("--line") }, horzLines: { color: css("--line") } },
      rightPriceScale: { borderColor: css("--line") },
      timeScale: { borderColor: css("--line"), rightOffset: 3 },
      localization: { locale: "ja-JP", dateFormat: "yyyy/MM/dd" },
    });
    const base = baseIndex();
    const baseLine = chart.addSeries(LC.LineSeries, { color: css("--muted"), lineWidth: 1, lineStyle: 2,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    baseLine.setData([{ time: data.dates[base], value: 100 }, { time: data.dates[data.dates.length - 1], value: 100 }]);
    for (const [id, slot] of selected[kind]) {
      const it = items.get(id);
      if (!it) continue;
      const pts = cumulative(it.daily, base);
      const s = chart.addSeries(LC.LineSeries, { color: css(`--c${slot}`), lineWidth: 2, priceLineVisible: false,
        title: it.name.length > 8 ? it.name.slice(0, 8) + "…" : it.name });
      s.setData(pts);
      const last = pts[pts.length - 1].value - 100;
      const pv = main.querySelector(`.pick[data-id="${CSS.escape(id)}"] .pv`);
      if (pv) pv.textContent = `${last >= 0 ? "+" : ""}${last.toFixed(1)}%`;
    }
    chart.timeScale().fitContent();
  }

  defaultPick(kind);
  syncPicks();
  draw();
})();
