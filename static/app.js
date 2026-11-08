/* STAND — interfaccia. JavaScript semplice: stato, chiamate all'API, disegno delle sezioni. */
(function () {
  "use strict";

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v, d = 0) => Number(v).toLocaleString("it-IT", { maximumFractionDigits: d });
  const TABS = ["modello", "pezzi", "montaggio", "verifica"];

  const S = {
    presets: [], angles: [], key: null, res: null, tab: "modello", view: "3d", angle: null,
    guide: 0, meshes: new Map(), viewer: null, busy: false,
  };

  // ---------------------------------------------------------------- API
  async function api(path, opts = {}) {
    const r = await fetch(path, {
      ...opts,
      headers: opts.body ? { "Content-Type": "application/json" } : undefined,
    });
    let data = null;
    try { data = await r.json(); } catch (_) { /* risposta vuota */ }
    if (!r.ok) throw new Error((data && data.detail) || `Errore ${r.status}`);
    return data;
  }

  async function waitJob(job, onProgress) {
    while (job.state !== "done" && job.state !== "error") {
      onProgress(job);
      await new Promise((ok) => setTimeout(ok, 450));
      job = await api(`/api/jobs/${job.id}`);
    }
    onProgress(job);
    if (job.state === "error") throw new Error(job.error);
    return job.key;
  }

  // ---------------------------------------------------------------- modulo
  const F = {
    preset: $("#f-preset"), title: $("#f-title"), w: $("#f-w"), d: $("#f-d"), h: $("#f-h"), kg: $("#f-kg"),
    max: $("#f-max"), lip: $("#f-lip"), spmin: $("#f-spmin"), spmax: $("#f-spmax"), keep: $("#f-keep"),
    angleNew: $("#f-angle-new"),
  };
  const fmtIn = (v) => (v === null || v === undefined || v === "" ? "" : String(v).replace(".", ","));

  function fillForm(p) {
    F.w.value = fmtIn(p.w); F.d.value = fmtIn(p.d); F.h.value = fmtIn(p.h); F.kg.value = fmtIn(p.kg);
    F.lip.value = fmtIn(p.lip ?? 10);
    F.max.value = fmtIn(p.max_depth ?? "");
    F.spmin.value = fmtIn(p.sp_min ?? ""); F.spmax.value = fmtIn(p.sp_max ?? "");
    S.angles = (p.angles || []).map(Number);
    renderAngles();
  }

  function presetChanged() {
    const p = S.presets.find((x) => x.id === F.preset.value);
    $("#f-title-wrap").hidden = !!p;
    $("#f-keep-wrap").hidden = !p;
    if (p) fillForm(p);
  }

  function renderAngles() {
    S.angles = [...new Set(S.angles)].sort((a, b) => a - b);
    $("#angle-chips").innerHTML = S.angles.map((a) =>
      `<span class="angle-chip">${esc(num(a, 1))}°<button type="button" data-del="${a}" aria-label="Togli ${esc(num(a, 1))} gradi">×</button></span>`
    ).join("") || `<span class="hint">Nessun angolo: aggiungine almeno uno.</span>`;
  }

  function addAngle() {
    const v = parseFloat(F.angleNew.value.replace(",", "."));
    if (!isFinite(v) || v < 1 || v > 60) return showError("Angolo: un numero tra 1 e 60.");
    if (S.angles.length >= 6 && !S.angles.includes(v)) return showError("Al massimo 6 angoli.");
    S.angles.push(Math.round(v * 10) / 10);
    F.angleNew.value = "";
    showError(null);
    renderAngles();
  }

  function showError(msg) {
    const el = $("#form-error");
    el.hidden = !msg;
    el.textContent = msg || "";
  }

  function body() {
    return {
      preset: F.preset.value || null,
      title: F.title.value,
      w: F.w.value, d: F.d.value, h: F.h.value, kg: F.kg.value,
      angles: S.angles,
      lip: F.lip.value || 0,
      max_depth: F.max.value || null,
      sp_min: F.spmin.value || null, sp_max: F.spmax.value || null,
      keep_notches: F.keep.checked,
    };
  }

  // ---------------------------------------------------------------- generazione
  function setBusy(on, stage = "", frac = 0, note = "") {
    S.busy = on;
    $("#generate").disabled = on;
    $("#gen-box").hidden = !on && !note;
    $("#gen-stage").textContent = stage;
    $("#gen-pct").textContent = on ? `${Math.round(frac * 100)} %` : "";
    $("#gen-bar").style.width = `${Math.round((on ? frac : 1) * 100)}%`;
    $("#gen-note").textContent = note;
    $("#vp-busy").hidden = !on;
    $("#vp-busy-text").textContent = stage;
  }

  async function generate() {
    if (S.busy) return;
    showError(null);
    if (!S.angles.length) return showError("Aggiungi almeno un angolo.");
    closeDrawer();
    const t0 = performance.now();
    setBusy(true, "Invio", 0.02);
    try {
      const r = await api("/api/generate", { method: "POST", body: JSON.stringify(body()) });
      const key = r.key || await waitJob(r, (j) => setBusy(true, j.stage, j.progress));
      setBusy(true, "Carico il risultato", 0.95);
      await loadResult(key, "modello");
      const s = ((performance.now() - t0) / 1000).toFixed(1).replace(".", ",");
      const tune = S.res.summary && S.res.tune ? ` Tacche ${S.res.tune}` : "";
      setBusy(false, r.cached ? "Dalla cache" : "Generato", 1, r.cached ? `Ripreso dalla cache in ${s} s.` : `Fatto in ${s} s.${tune}`);
      $("#gen-stage").textContent = r.cached ? "Dalla cache" : "Generato";
    } catch (e) {
      setBusy(false);
      $("#gen-box").hidden = true;
      showError(e.message);
    }
  }

  // ---------------------------------------------------------------- risultato
  async function loadResult(key, tab) {
    const res = await api(`/api/result/${key}`);
    S.key = key; S.res = res; S.guide = 0;
    S.meshes.clear();
    const valid = !!res.summary;
    S.angle = valid ? res.angles[res.angles.length - 1] : null;
    renderHeader();
    renderModel();
    renderPezzi();
    renderGuide();
    renderVerifica();
    syncFormFromResult();
    go(tab || S.tab, true);
    if (valid) {
      res.angles.forEach((a) => { new Image().src = `/api/draw/${key}/side_${a}.png`; });
    }
  }

  function syncFormFromResult() {
    // riporta nel modulo i dati con cui è stato generato il risultato aperto
    const inp = S.res && S.res.input;
    if (!inp) return;
    const preset = S.presets.find((x) => x.label === S.res.title);
    F.preset.value = preset ? preset.id : "";
    $("#f-title-wrap").hidden = !!preset;
    $("#f-keep-wrap").hidden = !preset;
    if (!preset) F.title.value = S.res.title || "";
    fillForm(inp);
  }

  function statusOf(res) {
    if (!res.summary) return { cls: "err", text: "nessun supporto possibile" };
    const errs = res.checks.filter((c) => !c.ok && c.level === "error").length;
    const warns = res.checks.filter((c) => !c.ok && c.level === "warning").length;
    if (errs) return { cls: "err", text: `${errs} ${errs === 1 ? "problema" : "problemi"}` };
    if (warns) return { cls: "warn", text: `${warns} ${warns === 1 ? "avviso" : "avvisi"}` };
    return { cls: "ok", text: "nessuna collisione" };
  }

  function renderHeader() {
    const res = S.res;
    $("#crumb-title").textContent = res ? res.title : "Nuovo";
    $("#crumb-key").hidden = !res;
    $("#crumb-key").textContent = res ? res.key.slice(0, 6) : "";
    const chip = $("#status-chip");
    chip.hidden = !res;
    if (res) {
      const st = statusOf(res);
      chip.className = `chip ${st.cls}`;
      chip.textContent = st.text;
    }
    const valid = res && res.summary;
    $("#top-guide").hidden = !valid;
    $("#top-guide").href = valid ? `#/${res.key}/montaggio` : "#";
    $("#top-zip").hidden = !valid;
    if (valid) $("#top-zip").href = `/files/${res.key}/${res.files.zip}`;
    $$("[data-tab]").forEach((a) => {
      const t = a.dataset.tab;
      a.classList.toggle("disabled", !res || (!valid && t !== "modello" && t !== "verifica"));
    });
    document.title = res ? `${res.title} · STAND` : "STAND · supporti inclinabili low-profile";
  }

  // ---------------------------------------------------------------- modello
  function renderModel() {
    const res = S.res, valid = res && res.summary;
    $("#vp-empty").hidden = !!res;
    $("#vp-fail").hidden = !res || valid;
    $("#vp-label").hidden = !valid;
    $("#vp-dims").hidden = !valid;
    $("#vp-angles").hidden = !valid;
    $("#summary").hidden = !valid;
    $("#view-seg").hidden = !valid;
    if (res && !valid) {
      $("#vp-fail").innerHTML = `<span class="eyebrow">Esito</span><h2>Nessun supporto possibile</h2>
        <p>${esc(res.message)}</p>${res.tune_errors && res.tune_errors.length ? `<p class="hint">Ultimo controllo fallito: ${esc(res.tune_errors[0])}</p>` : ""}
        <p class="hint">Prova con meno angoli, angoli più distanti tra loro o senza limite di profondità.</p>`;
      $("#gl").hidden = true; $("#side-img").hidden = true; $("#vp-reset").hidden = true;
      return;
    }
    if (!valid) { $("#gl").hidden = true; $("#side-img").hidden = true; $("#vp-reset").hidden = true; return; }

    const sm = res.summary;
    $("#vp-dims").innerHTML = `<span>piano d'appoggio <b>${num(sm.piano_davanti_mm)} mm</b></span>
      <span>profondità base <b>${num(sm.profondita_mm)} mm</b></span>
      <span>fianchi a <b>${num(res.spacing[0])}–${num(res.spacing[1])} mm</b></span>`;
    $("#angle-seg").innerHTML = res.angles.map((a) =>
      `<button type="button" data-angle="${esc(a)}" aria-pressed="${a === S.angle}">${esc(a.replace(".", ","))}°</button>`).join("");
    renderSummary();
    applyView();
  }

  function hwCounts(bom) {
    const c = { viti: 0, dadi: 0, auto: 0, rondelle: 0 };
    for (const b of bom) {
      if (/^Vite/i.test(b.item)) c.viti += b.qty;
      else if (/^Dado/i.test(b.item)) { c.dadi += b.qty; if (/autobloccante/i.test(b.item)) c.auto += b.qty; }
      else if (/^Rondella/i.test(b.item)) c.rondelle += b.qty;
    }
    return c;
  }

  function renderSummary() {
    const res = S.res, sm = res.summary, d = res.device, k = res.key;
    const hw = hwCounts(res.bom);
    const nParts = res.parts.reduce((s, p) => s + p.qty, 0);
    const stl = Object.entries(res.files).filter(([n]) => n.startsWith("stl/"));
    $("#summary").innerHTML = `
      <div class="s-head">
        <span class="eyebrow">Riepilogo</span>
        <span class="s-title">${esc(res.title)}</span>
        <span class="s-sub">${num(d.DEV_W)} × ${num(d.DEV_D)} × ${num(d.DEV_H)} mm · ${num(d.DEV_KG, 1)} kg</span>
      </div>
      <dl class="stats">
        <div><dt>Piano davanti</dt><dd>${num(sm.piano_davanti_mm)}<small> mm</small></dd></div>
        <div><dt>Bordino</dt><dd>+${num(sm.bordino_mm)}<small> mm</small></dd></div>
        <div><dt>Profondità</dt><dd>${num(sm.profondita_mm)}<small> mm</small></dd></div>
        <div><dt>Filamento</dt><dd>~${num(sm.filamento_g)}<small> g</small></dd></div>
      </dl>
      <div class="s-sec">
        <span class="eyebrow">Da stampare · ${nParts} pezzi</span>
        ${res.parts.map((p) => `<div class="s-row"><span>${esc(p.name)}</span><span>${p.qty}×</span></div>`).join("")}
      </div>
      <div class="s-sec">
        <span class="eyebrow">Ferramenta · M5 inox</span>
        <div class="s-row"><span>Viti</span><span>${hw.viti}</span></div>
        <div class="s-row"><span>Dadi${hw.auto ? ` (${hw.auto} autobloccanti)` : ""}</span><span>${hw.dadi}</span></div>
        <div class="s-row"><span>Rondelle</span><span>${hw.rondelle}</span></div>
        <a href="#/${k}/pezzi" class="hint">Dettaglio e lunghezze →</a>
      </div>
      <div class="s-sec">
        <a class="dl btn-primary" href="/files/${k}/${esc(res.files.zip)}">Scarica pacchetto <span>.zip</span></a>
        <div class="stl-list">
          ${stl.map(([n, f]) => `<a href="/files/${k}/${esc(f)}" download><span>${esc(n.slice(4))}</span><span>STL ↓</span></a>`).join("")}
        </div>
      </div>`;
  }

  function ensureViewer() {
    if (S.viewer || S.noGL) return S.viewer;
    try {
      S.viewer = new window.StandViewer($("#gl"));
    } catch (e) {
      S.noGL = true;
      S.view = "side";
      $("#view-seg").hidden = true;
    }
    return S.viewer;
  }

  async function applyView() {
    if (!S.res || !S.res.summary) return;
    const a = S.angle;
    $$("#angle-seg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.angle === a)));
    $("#vp-angle").textContent = `${a.replace(".", ",")}°`;
    const viewer = S.view === "3d" ? ensureViewer() : null;
    const side = S.view === "side" || !viewer;
    $$("#view-seg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === (side ? "side" : "3d"))));
    $("#vp-view").textContent = side ? "Profilo sinistro" : "3D · trascina per ruotare";
    $("#gl").hidden = side;
    $("#vp-reset").hidden = side;
    const img = $("#side-img");
    img.hidden = !side;
    if (side) {
      img.src = `/api/draw/${S.key}/side_${a}.png`;
      img.alt = `Profilo del supporto a ${a}°, con lo strumento a contorno`;
      return;
    }
    const key = S.key;
    let mesh = S.meshes.get(a);
    if (!mesh) {
      $("#vp-busy").hidden = false;
      $("#vp-busy-text").textContent = "Carico il modello 3D";
      try {
        mesh = await api(`/api/mesh/${key}/${a}.json`);
      } finally {
        if (!S.busy) $("#vp-busy").hidden = true;
      }
      if (key !== S.key) return;
      S.meshes.set(a, mesh);
    }
    if (S.angle === a && S.view === "3d") {
      viewer.setMesh(mesh, viewer._key === key);
      viewer._key = key;
    }
  }

  // ---------------------------------------------------------------- pezzi
  function screwSvg(L, hex) {
    const k = 2.2, hx = Math.round(5 * k), end = hx + Math.round(L * k), w = end + 4;
    let thr = "";
    for (let x = hx + 6; x < end - 3; x += 5) thr += `M${x} 6.5 L${x + 3} 13.5 `;
    const head = hex ? `<rect x="0.5" y="2.5" width="${hx}" height="15"/><path d="M0.5 7 H${hx + 0.5} M0.5 13 H${hx + 0.5}"/>`
                     : `<rect x="0.5" y="2.5" width="${hx}" height="15"/>`;
    return `<svg width="${w}" height="20" viewBox="0 0 ${w} 20" aria-hidden="true">${head}<path d="M${hx} 6.5 H${end} V13.5 H${hx}"/><path class="thr" d="${thr}"/></svg>`;
  }
  function hwSvg(item) {
    const m = item.match(/M5×(\d+)/);
    if (/^Vite/i.test(item) && m) return screwSvg(+m[1], /esagonale/i.test(item));
    if (/^Dado/i.test(item)) {
      return `<svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true"><path d="M6 1.5 H16 L21 11 L16 20.5 H6 L1 11 Z"/><circle cx="11" cy="11" r="4"/>${/autobloccante/i.test(item) ? '<circle class="acc" cx="11" cy="11" r="6.5"/>' : ""}</svg>`;
    }
    return `<svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true"><circle cx="11" cy="11" r="10"/><circle cx="11" cy="11" r="3"/></svg>`;
  }

  function checkIcon(c) {
    if (c.ok) return `<svg viewBox="0 0 16 16"><rect x="0.5" y="0.5" width="15" height="15"/><path d="M4 8.5 L7 11 L12 5" stroke-width="1.6"/></svg>`;
    if (c.level === "warning") return `<svg viewBox="0 0 16 16"><path d="M8 1 L15.5 15 H0.5 Z"/><path d="M8 6 V10 M8 12 V13"/></svg>`;
    return `<svg viewBox="0 0 16 16"><rect x="0.5" y="0.5" width="15" height="15"/><path d="M4.5 4.5 L11.5 11.5 M11.5 4.5 L4.5 11.5" stroke-width="1.6"/></svg>`;
  }
  const checkCls = (c) => (c.ok ? "c-ok" : c.level === "warning" ? "c-warn" : "c-err");
  const checkLi = (c, group = false) => `<li class="${checkCls(c)}">${checkIcon(c)}<span>${group ? `<span class="g">${esc(c.group)}</span>` : ""}<span class="t">${esc(c.label)}</span>${c.detail ? `<span class="d">${esc(c.detail)}</span>` : ""}</span></li>`;

  function renderPezzi() {
    const res = S.res, el = $("#page-pezzi");
    if (!res || !res.summary) { el.innerHTML = ""; return; }
    const k = res.key, st = statusOf(res);
    const files = res.files;
    const bad = res.checks.filter((c) => !c.ok);
    const longest = Math.max(...res.parts.map((p) => Math.max(...p.size)));
    el.innerHTML = `
      <div class="page-head">
        <div><span class="eyebrow">Tavola 02 · ${esc(res.title)}</span><h1>Pezzi da stampare</h1></div>
        <p>Già orientati per la stampa, senza supporti. PETG, 4 pareti, gyroid 30–40 %.${longest > 240 ? ` Il pezzo più lungo misura ${num(longest)} mm: nel piatto da 256 entra di poco, se lo slicer si lamenta ruotalo in diagonale.` : ""}</p>
      </div>
      <section class="parts" aria-label="Pezzi">
        ${res.parts.map((p) => `
          <article class="part">
            <div class="part-img bp-grid-fine"><img loading="lazy" src="/api/draw/${k}/part_${esc(p.file)}.png" alt="${esc(p.name)}"><span class="part-qty">${p.qty}×</span></div>
            <div class="part-body">
              <span class="part-name">${esc(p.name)}</span>
              <span class="part-size">${p.size.map((v) => num(v)).join(" × ")} mm</span>
              <div class="part-foot"><span>${esc(p.file)}.stl</span><a href="/files/${k}/${esc(files[`stl/${p.file}.stl`] || "")}" download>STL ↓</a></div>
            </div>
          </article>`).join("")}
      </section>
      <div class="cols">
        <section class="box" style="flex: 999 1 560px" aria-label="Ferramenta">
          <div class="box-head"><h2>Ferramenta</h2><span class="eyebrow">M5 inox · scorta standard · disegni in proporzione</span></div>
          <div class="scroll-x">
            <table class="hw">
              <thead><tr><th style="width: 200px">Pezzo</th><th>Voce</th><th>Dove</th><th>Q.tà</th></tr></thead>
              <tbody>${res.bom.map((b) => `
                <tr><td>${hwSvg(b.item)}</td><td class="item">${esc(b.item)}</td><td class="use">${esc(b.use)}</td>
                <td class="qty">${b.qty}${b.qty > b.stock ? `<span class="over">oltre la scorta (${b.stock})</span>` : ""}</td></tr>`).join("")}
              </tbody>
            </table>
          </div>
          <div class="box-foot"><span>Attrezzi: brugola 4 mm, chiave da 8 mm.</span><a href="/files/${k}/${esc(files["ferramenta.csv"])}" download>ferramenta.csv ↓</a></div>
        </section>
        <section class="box" style="flex: 1 1 320px" aria-label="Verifica">
          <div class="box-head"><h2>Verifica</h2><span class="chip ${st.cls}">${esc(st.cls === "ok" ? "tutto a posto" : st.text)}</span></div>
          <ul class="checks">${(bad.length ? bad : res.checks.slice(0, 7)).map((c) => checkLi(c)).join("")}</ul>
          <div class="box-foot"><span>${res.checks.length} controlli</span><a href="#/${k}/verifica">tutti i controlli →</a></div>
        </section>
      </div>`;
  }

  // ---------------------------------------------------------------- montaggio
  function renderGuide() {
    const res = S.res;
    if (!res || !res.summary) { $("#g-index").innerHTML = ""; $("#g-desk").innerHTML = ""; $("#g-detail").innerHTML = ""; return; }
    const G = res.guide, i = Math.min(S.guide, G.length - 1), p = G[i], k = res.key;
    const pad = (n) => String(n + 1).padStart(2, "0");
    $("#g-index").innerHTML = G.map((g, j) => `
      <li><button type="button" data-page="${j}" ${j === i ? 'aria-current="page"' : ""}>
        <span class="g-num">${pad(j)}</span>
        <span class="g-txt"><span class="eyebrow">${esc(g.kind)}</span><span>${esc(g.title)}</span></span>
      </button></li>`).join("");

    const hasPdf = res.pdf && res.pages.length;
    const sheet = hasPdf && res.pages[i]
      ? `<img class="sheet" src="/files/${k}/istruzioni/${esc(res.pages[i])}" alt="Pagina ${i + 1}: ${esc(p.title)}">`
      : `<div class="sheet-empty" id="sheet-empty">
           <svg viewBox="0 0 48 48" width="64" height="64" aria-hidden="true" class="empty-mark"><path d="M3 40 H45" class="m-ink"/><path d="M8 38 L41 13.25" class="m-acc"/><path d="M36 40 L33 19.5" class="m-ink"/></svg>
           <h2>Istruzioni illustrate</h2>
           <p>Disegno le ${G.length} pagine A4 dal modello: pezzi, ferramenta in scala 1:1, passi esplosi. Servono circa 20 secondi.</p>
           <button class="btn btn-primary" type="button" id="make-pdf">Crea le istruzioni</button>
           <div class="bar" id="pdf-bar" hidden><div></div></div>
           <span class="hint" id="pdf-stage"></span>
         </div>`;
    $("#g-desk").innerHTML = `
      <div class="g-meta"><span>Foglio ${pad(i)} / ${pad(G.length - 1)}</span><span>${hasPdf ? `<a href="/files/${k}/istruzioni.pdf" target="_blank" rel="noopener">istruzioni.pdf ↗</a>` : "A4 · stampa al 100 %"}</span></div>
      ${sheet}
      <div class="g-nav">
        <button class="icon-btn" type="button" data-step="-1" aria-label="Pagina precedente" ${i === 0 ? "disabled" : ""}>←</button>
        <button class="btn btn-primary" type="button" data-step="1" ${i === G.length - 1 ? "disabled" : ""}>Pagina successiva →</button>
      </div>`;
    $("#g-detail").innerHTML = `
      <div class="g-top">
        <span class="eyebrow">${esc(p.kind)}</span>
        <div class="g-title">${p.step ? `<span class="step-no">${p.step}</span>` : ""}<h2>${esc(p.title)}</h2></div>
        <p>${esc(p.text)}</p>
        ${p.twice ? `<span class="twice"><b>2×</b>ripeti sull'altro fianco</span>` : ""}
      </div>
      <div class="need">
        <span class="eyebrow">Ti serve</span>
        ${p.need.length ? p.need.map(([w, q]) => `<div class="need-row"><span>${esc(w)}</span><span>${q}×</span></div>`).join("")
                        : `<span class="hint">${p.step ? "Solo le mani." : "Niente: è una pagina da leggere."}</span>`}
      </div>
      <div class="g-progress">
        <div class="gen-row mono"><span>Avanzamento</span><span>${pad(i)} / ${pad(G.length - 1)}</span></div>
        <div class="bar"><div style="width: ${Math.round(((i + 1) / G.length) * 100)}%"></div></div>
        ${hasPdf ? `<a class="dl btn-outline" href="/files/${k}/istruzioni.pdf" download>Scarica il PDF <span>${G.length} pag.</span></a>` : ""}
      </div>`;
  }

  async function makePdf() {
    const key = S.key, btn = $("#make-pdf"), bar = $("#pdf-bar");
    btn.disabled = true;
    bar.hidden = false;
    const t0 = performance.now();
    const tick = setInterval(() => {               // il PDF non dà avanzamento fine: stima sui ~20 s
      const f = Math.min(0.95, (performance.now() - t0) / 22000);
      if ($("#pdf-bar div")) $("#pdf-bar div").style.width = `${Math.round(f * 100)}%`;
    }, 300);
    try {
      const r = await api(`/api/pdf/${key}`, { method: "POST" });
      if (!r.key) await waitJob(r, (j) => { if ($("#pdf-stage")) $("#pdf-stage").textContent = j.stage; });
      if (key === S.key) {
        const res = await api(`/api/result/${key}`);
        Object.assign(S.res, { pdf: res.pdf, pages: res.pages });
        renderGuide();
      }
    } catch (e) {
      if ($("#pdf-stage")) $("#pdf-stage").textContent = e.message;
      btn.disabled = false;
    } finally {
      clearInterval(tick);
    }
  }

  // ---------------------------------------------------------------- verifica
  function renderVerifica() {
    const res = S.res, el = $("#page-verifica");
    if (!res) { el.innerHTML = ""; return; }
    if (!res.summary) {
      el.innerHTML = `<div class="page-head"><div><span class="eyebrow">Verifica</span><h1>Nessun supporto possibile</h1></div></div>
        <section class="box"><div class="kv"><span class="eyebrow">Motivo</span><span>${esc(res.message)}</span></div>
        ${(res.tune_errors || []).map((e) => `<div class="kv"><span class="eyebrow">Controllo fallito</span><span>${esc(e)}</span></div>`).join("")}</section>`;
      return;
    }
    const st = statusOf(res);
    const groups = {};
    res.checks.forEach((c) => (groups[c.group] = groups[c.group] || []).push(c));
    const order = (c) => (c.ok ? 2 : c.level === "warning" ? 1 : 0);
    el.innerHTML = `
      <div class="page-head">
        <div><span class="eyebrow">Tavola 04 · ${esc(res.title)}</span><h1>Verifica</h1></div>
        <span class="chip ${st.cls}">${esc(st.text)}</span>
      </div>
      <section class="box">
        <div class="kv"><span class="eyebrow">Esito</span><span>${res.ok ? "Supporto valido: nessuna collisione a nessun angolo, pezzi interi, viti dalla scorta." : esc(res.message)}</span></div>
        ${res.tune ? `<div class="kv"><span class="eyebrow">Tacche</span><span>Calcolate in automatico, ${esc(res.tune)}</span></div>` : ""}
        <div class="kv"><span class="eyebrow">Generazione</span><span class="mono">${num(res.seconds, 1)} s · chiave ${esc(res.key)}</span></div>
      </section>
      <div class="ver-grid">
        ${Object.entries(groups).map(([g, cs]) => `
          <section class="box"><div class="box-head"><h2>${esc(g)}</h2><span class="eyebrow">${cs.filter((c) => c.ok).length} / ${cs.length}</span></div>
          <ul class="checks">${cs.sort((a, b) => order(a) - order(b)).map((c) => checkLi(c)).join("")}</ul></section>`).join("")}
      </div>`;
  }

  // ---------------------------------------------------------------- navigazione
  function go(tab, replace) {
    if (!TABS.includes(tab)) tab = "modello";
    if (S.res && !S.res.summary && (tab === "pezzi" || tab === "montaggio")) tab = "modello";
    S.tab = tab;
    $$("[data-panel]").forEach((p) => (p.hidden = p.dataset.panel !== tab));
    $$("[data-tab]").forEach((a) => {
      if (a.dataset.tab === tab) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
      a.href = S.key ? `#/${S.key}/${a.dataset.tab}` : "#/";
    });
    $("#view-seg").style.visibility = tab === "modello" ? "visible" : "hidden";
    const h = S.key ? `#/${S.key}/${tab}` : "#/";
    if (location.hash !== h) {
      if (replace) history.replaceState(null, "", h); else history.pushState(null, "", h);
    }
    if (tab === "modello" && S.viewer) S.viewer.draw();
  }

  async function route() {
    const m = location.hash.match(/^#\/([0-9a-f]{16})(?:\/(\w+))?/);
    if (!m) {
      if (S.key) { S.key = null; S.res = null; renderHeader(); renderModel(); go("modello", true); }
      return;
    }
    if (m[1] !== S.key) {
      try { await loadResult(m[1], m[2]); }
      catch (e) { showError(e.message); history.replaceState(null, "", "#/"); }
    } else go(m[2], true);
  }

  // ---------------------------------------------------------------- cassetto (mobile)
  function openDrawer() { $("#params").classList.add("open"); $("#scrim").hidden = false; $("#open-params").setAttribute("aria-expanded", "true"); }
  function closeDrawer() { $("#params").classList.remove("open"); $("#scrim").hidden = true; $("#open-params").setAttribute("aria-expanded", "false"); }

  // ---------------------------------------------------------------- eventi
  function bind() {
    F.preset.addEventListener("change", presetChanged);
    $("#form").addEventListener("submit", (e) => { e.preventDefault(); generate(); });
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); generate(); }
      if (e.key === "Escape") closeDrawer();
    });
    $("#angle-add").addEventListener("click", addAngle);
    F.angleNew.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.ctrlKey && !e.metaKey) { e.preventDefault(); addAngle(); } });
    $("#angle-chips").addEventListener("click", (e) => {
      const b = e.target.closest("[data-del]");
      if (b) { S.angles = S.angles.filter((a) => a !== Number(b.dataset.del)); renderAngles(); }
    });
    $("#angle-seg").addEventListener("click", (e) => {
      const b = e.target.closest("[data-angle]");
      if (b) { S.angle = b.dataset.angle; applyView(); }
    });
    $("#view-seg").addEventListener("click", (e) => {
      const b = e.target.closest("[data-view]");
      if (b) { S.view = b.dataset.view; applyView(); }
    });
    $("#vp-reset").addEventListener("click", () => S.viewer && S.viewer.reset());
    $("#g-index").addEventListener("click", (e) => {
      const b = e.target.closest("[data-page]");
      if (b) { S.guide = Number(b.dataset.page); renderGuide(); }
    });
    $("#g-desk").addEventListener("click", (e) => {
      const b = e.target.closest("[data-step]");
      if (b) { S.guide = Math.max(0, Math.min(S.res.guide.length - 1, S.guide + Number(b.dataset.step))); renderGuide(); }
      if (e.target.closest("#make-pdf")) makePdf();
    });
    $("#open-params").addEventListener("click", () => ($("#params").classList.contains("open") ? closeDrawer() : openDrawer()));
    $("#scrim").addEventListener("click", closeDrawer);
    window.addEventListener("hashchange", route);
    window.addEventListener("popstate", route);
  }

  async function init() {
    bind();
    try {
      S.presets = await api("/api/presets");
    } catch (e) {
      showError(`Non riesco a parlare col server: ${e.message}`);
      return;
    }
    const groups = [];
    for (const p of S.presets) {
      let g = groups.find((x) => x.name === p.group);
      if (!g) groups.push((g = { name: p.group, items: [] }));
      g.items.push(p);
    }
    F.preset.innerHTML = groups.map((g) => `<optgroup label="${esc(g.name)}">${g.items.map((p) =>
      `<option value="${esc(p.id)}">${esc(p.label)}</option>`).join("")}</optgroup>`).join("")
      + `<option value="">Strumento personalizzato</option>`;
    presetChanged();
    renderHeader();
    renderModel();
    if (/^#\/[0-9a-f]{16}/.test(location.hash)) {
      await route();
    } else {
      go("modello", true);
      if (window.matchMedia("(max-width: 900px)").matches) openDrawer();
    }
  }

  init();
})();
