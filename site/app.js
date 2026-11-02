/* Texas Legislature 2026 Forecast - client renderer. Data is embedded in data/*.js (no fetches). */
(function(){
const F = window.FORECAST, GEO = window.GEO || {}, BT = window.BACKTEST || null;
const $ = (s, el) => (el||document).querySelector(s);
const fmtP = p => p >= .995 ? ">99%" : p <= .005 ? "<1%" : Math.round(p*100) + "%";
const fmtM = m => m == null ? "—" : (m > 0 ? "D+" : m < 0 ? "R+" : "Even ") + Math.abs(m).toFixed(1);
const esc = s => String(s==null?"":s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const seats = F.seats, byKey = Object.fromEntries(seats.map(s => [s.key, s]));
const label = s => (s.chamber === "H" ? "HD " : "SD ") + s.district;
const href = s => (window.ROOT||"") + "districts/" + s.key + ".html";
const prob = s => s.p_dem == null ? null : s.p_dem;
function colorFor(s){ // diverging: blue (D) - neutral - red (R), by win probability; others gray
  if (s.contest === "not_up") return "url(#hatch)";
  if (s.p_other != null && s.p_other > 0.5) return "var(--oth)";
  const p = prob(s); if (p == null) return "var(--neutral)";
  const t = Math.abs(p - .5) * 2; // 0 = tossup, 1 = certain
  const base = p >= .5 ? [43,95,179] : [192,57,43];
  const neu = getComputedStyle(document.documentElement).getPropertyValue("--neutral").trim();
  const n = hexToRgb(neu) || [214,212,204];
  const mix = base.map((c,i) => Math.round(n[i] + (c - n[i]) * Math.pow(t, .6)));
  return `rgb(${mix.join(",")})`;
}
function hexToRgb(h){ const m = /^#?([0-9a-f]{6})$/i.exec(h); if(!m) return null; const v = parseInt(m[1],16); return [v>>16&255, v>>8&255, v&255]; }
function rating(s){
  if (s.contest === "uncontested") return "Uncontested";
  if (s.contest === "not_up") return "Not up in 2026";
  const p = prob(s); if (p == null) return "—";
  const d = p >= .5, q = d ? p : 1 - p, side = d ? "D" : "R";
  if (s.p_other > .5) return "Likely Other";
  return q > .97 ? "Safe " + side : q > .85 ? "Likely " + side : q > .65 ? "Lean " + side : "Toss-up";
}
const tt = document.createElement("div"); tt.className = "tt"; document.body.appendChild(tt);
function showTT(e, html){ tt.innerHTML = html; tt.style.display = "block"; const x = Math.min(e.clientX + 14, window.innerWidth - 280), y = e.clientY + 14; tt.style.left = x + "px"; tt.style.top = y + "px"; }
function hideTT(){ tt.style.display = "none"; }

/* ---------- charts ---------- */
function seatHistogram(el, dist, majority, current){
  const W = 640, H = 220, pad = {l:10,r:10,t:16,b:34};
  const n = dist.length, total = dist.reduce((a,b)=>a+b,0);
  const nz = dist.map((v,i)=>v>0?i:-1).filter(i=>i>=0); const lo = Math.max(0, nz[0]-1), hi = Math.min(n-1, nz[nz.length-1]+1);
  const bw = (W-pad.l-pad.r)/(hi-lo+1), mx = Math.max(...dist)/total;
  let s = `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Distribution of Democratic seats">`;
  s += `<defs></defs>`;
  for (let i=lo;i<=hi;i++){ const p = dist[i]/total, h = (H-pad.t-pad.b)*p/mx, x = pad.l+(i-lo)*bw, y = H-pad.b-h;
    s += `<rect x="${x+1}" y="${y}" width="${Math.max(bw-2,1)}" height="${h}" rx="2" fill="${i>=majority?'var(--dem)':'var(--rep)'}" data-i="${i}" data-p="${(p*100).toFixed(1)}"/>`; }
  const xm = pad.l+(majority-lo)*bw;
  s += `<line x1="${xm}" x2="${xm}" y1="${pad.t-6}" y2="${H-pad.b}" stroke="var(--ink)" stroke-dasharray="3 3"/><text x="${xm+4}" y="${pad.t}" font-size="12" fill="var(--ink2)">${majority} = majority</text>`;
  if (current != null){ const xc = pad.l+(current-lo+.5)*bw; s += `<circle cx="${xc}" cy="${H-pad.b+8}" r="4" fill="var(--ink)"/><text x="${xc}" y="${H-pad.b+30}" font-size="11" text-anchor="middle" fill="var(--ink2)">now: ${current} D</text>`; }
  const step = (hi-lo) > 24 ? 5 : (hi-lo) > 10 ? 2 : 1;
  for (let i=lo;i<=hi;i++) if (i%step===0 && i!==current) s += `<text x="${pad.l+(i-lo+.5)*bw}" y="${H-pad.b+16}" font-size="11" text-anchor="middle" fill="var(--muted)">${i}</text>`;
  s += `</svg>`; el.innerHTML = s;
  el.querySelectorAll("rect").forEach(r => { r.addEventListener("mousemove", e => showTT(e, `<b>${r.dataset.i} Democratic seats</b><br>${r.dataset.p}% of simulations`)); r.addEventListener("mouseleave", hideTT); });
}
function waterfall(el, steps){
  const W = 640, rowH = 26, pad = {l:190, r:70, t:10, b:30}, H = pad.t + pad.b + rowH*steps.length;
  const vals = steps.map(x=>x.value); let run = 0; const cum = steps.map((x,i)=>{ if (x.total){ run = x.value; return [0, x.value]; } const a = run; run += x.value; return [a, run]; });
  const lo = Math.min(0, ...cum.flat()), hi = Math.max(0, ...cum.flat()); const sc = v => pad.l + (v-lo)/(hi-lo||1)*(W-pad.l-pad.r);
  let s = `<svg class="chart wf" viewBox="0 0 ${W} ${H}" role="img" aria-label="How each input moves the expected margin">`;
  s += `<line x1="${sc(0)}" x2="${sc(0)}" y1="${pad.t}" y2="${H-pad.b}" stroke="var(--ink2)"/>`;
  steps.forEach((x,i) => { const y = pad.t + i*rowH, [a,b] = cum[i], x0 = sc(Math.min(a,b)), w = Math.max(Math.abs(sc(b)-sc(a)), 1.5);
    const col = x.total ? (b>=0?"var(--dem)":"var(--rep)") : (x.value>=0?"var(--dem2)":"var(--rep2)");
    s += `<text x="${pad.l-8}" y="${y+rowH/2+4}" text-anchor="end">${esc(x.label)}</text>`;
    s += `<rect x="${x0}" y="${y+5}" width="${w}" height="${rowH-10}" rx="3" fill="${col}"/>`;
    s += `<text x="${sc(Math.max(a,b))+6}" y="${y+rowH/2+4}">${x.total? fmtM(b) : (x.value>=0?"+":"−")+Math.abs(x.value).toFixed(1)}</text>`; });
  s += `<text x="${sc(0)}" y="${H-8}" text-anchor="middle" fill="var(--muted)">← Republican · margin, points · Democratic →</text></svg>`;
  el.innerHTML = s;
}
function drawMap(el, chamber){
  const g = GEO[chamber === "H" ? "house" : "senate"]; if (!g){ el.innerHTML = "<p class='small'>Map data unavailable.</p>"; return; }
  const vb = g.viewBox; let s = `<svg class="chart map" viewBox="${vb.join(" ")}" role="img" aria-label="District map"><defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="var(--neutral)"/><line x1="0" y1="0" x2="0" y2="6" stroke="var(--card)" stroke-width="2"/></pattern></defs>`;
  g.features.forEach(f => { const key = (chamber==="H"?"HD":"SD") + String(f.id).padStart(3,"0"), st = byKey[key]; if (!st) return;
    const d = f.rings.map(r => "M" + r.map(p => p.join(",")).join("L") + "Z").join(" ");
    s += `<path d="${d}" fill="${colorFor(st)}" data-key="${key}"/>`; });
  s += `</svg>`; el.innerHTML = s;
  el.querySelectorAll("path").forEach(p => { const st = byKey[p.dataset.key];
    p.addEventListener("mousemove", e => showTT(e, seatTip(st))); p.addEventListener("mouseleave", hideTT); p.addEventListener("click", () => location.href = href(st)); });
}
function seatTip(s){
  let h = `<b>${label(s)}</b> · ${rating(s)}<br>`;
  if (s.contest === "not_up") return h + `Held by ${s.incumbent_party || "—"}; not on the 2026 ballot`;
  if (s.dem_name) h += `<span class="dem">${esc(s.dem_name)}</span>${s.dem_incumbent?" (i)":""}: ${fmtP(s.p_dem)}<br>`;
  if (s.rep_name) h += `<span class="rep">${esc(s.rep_name)}</span>${s.rep_incumbent?" (i)":""}: ${fmtP(s.p_rep)}<br>`;
  if (s.other_names) h += `<span class="oth">${esc(s.other_names)}</span>: ${fmtP(s.p_other)}<br>`;
  if (s.margin_mean != null && s.contest === "D_vs_R") h += `Expected margin ${fmtM(s.margin_mean)} (80% range ${fmtM(s.margin_p10)} to ${fmtM(s.margin_p90)})`;
  return h;
}

/* ---------- table ---------- */
function seatTable(el, rows, opts){
  opts = opts || {}; const state = {sort: opts.sort || "p_dem", dir: 1, q: "", region: "", comp: "", type: ""};
  const regions = [...new Set(rows.map(r=>r.region))].sort();
  el.innerHTML = `<div class="filters"><input placeholder="Search district or candidate" aria-label="Search">
    <select data-f="region"><option value="">All regions</option>${regions.map(r=>`<option>${esc(r)}</option>`).join("")}</select>
    <select data-f="comp"><option value="">All ratings</option><option>Toss-up</option><option>Lean</option><option>Likely</option><option>Safe</option><option>Uncontested</option></select>
    <select data-f="type"><option value="">All seats</option><option value="open">Open seats</option><option value="inc">Incumbent running</option><option value="flip">Likely flips</option><option value="third">Third-party / independent on ballot</option><option value="up">On the 2026 ballot</option></select></div>
    <div class="tablewrap"><table><thead><tr>
    <th data-k="district">District</th><th data-k="dem_name">Democrat</th><th data-k="rep_name">Republican</th><th data-k="other_names">Other</th><th data-k="incumbent_party">Held by</th><th data-k="p_dem" class="num">Dem win</th><th data-k="margin_mean" class="num">Exp. margin</th><th data-k="lean" class="num">Lean</th><th data-k="rating">Rating</th><th data-k="tipping_prob" class="num">Tipping pt.</th></tr></thead><tbody></tbody></table></div><p class="small" data-count></p>`;
  const tb = $("tbody", el);
  function render(){
    let r = rows.filter(s => { const q = state.q.toLowerCase();
      if (q && !(label(s).toLowerCase().includes(q) || (s.dem_name||"").toLowerCase().includes(q) || (s.rep_name||"").toLowerCase().includes(q) || (s.other_names||"").toLowerCase().includes(q))) return false;
      if (state.region && s.region !== state.region) return false;
      if (state.comp && !rating(s).startsWith(state.comp)) return false;
      if (state.type === "open" && !s.open_seat) return false;
      if (state.type === "inc" && s.open_seat) return false;
      if (state.type === "flip" && !(s.incumbent_party && ((s.incumbent_party==="D" && s.p_dem < .5) || (s.incumbent_party==="R" && s.p_dem > .5)))) return false;
      if (state.type === "third" && !s.other_names) return false;
      if (state.type === "up" && s.contest === "not_up") return false;
      return true; });
    const k = state.sort; r.sort((a,b) => { let x = k==="rating"? (a.p_dem??-1) : a[k], y = k==="rating"? (b.p_dem??-1) : b[k]; if (x==null) x = typeof y==="number"? -999:""; if (y==null) y = typeof x==="number"? -999:""; return (x>y?1:x<y?-1:0)*state.dir; });
    tb.innerHTML = r.map(s => `<tr><td><a href="${href(s)}">${label(s)}</a><div class="small">${esc(s.region||"")}</div></td>
      <td>${esc(s.dem_name)||"—"}${s.dem_incumbent?" <span class='small'>(i)</span>":""}</td><td>${esc(s.rep_name)||"—"}${s.rep_incumbent?" <span class='small'>(i)</span>":""}</td><td class="small">${esc(s.other_names)||""}</td>
      <td>${s.incumbent_party?`<span class="pill ${s.incumbent_party}">${s.incumbent_party}</span>`:"<span class='small'>vacant</span>"}</td>
      <td class="num">${s.contest==="not_up"?"—":fmtP(s.p_dem)}<div class="bar" title="Democratic win probability"><span style="width:${(s.p_dem||0)*100}%"></span></div></td>
      <td class="num">${s.contest==="D_vs_R"?fmtM(s.margin_mean):(s.contest==="uncontested"?"unopposed":"—")}</td><td class="num">${fmtM(s.lean)}</td><td>${rating(s)}</td><td class="num">${s.tipping_prob>0.0005?(s.tipping_prob*100).toFixed(1)+"%":""}</td></tr>`).join("");
    $("[data-count]", el).textContent = r.length + " seats shown";
    el.querySelectorAll("th").forEach(th => th.classList.toggle("sorted", th.dataset.k === state.sort));
  }
  el.querySelectorAll("th").forEach(th => th.addEventListener("click", () => { if (state.sort === th.dataset.k) state.dir *= -1; else { state.sort = th.dataset.k; state.dir = th.classList.contains("num") ? -1 : 1; } render(); }));
  $("input", el).addEventListener("input", e => { state.q = e.target.value; render(); });
  el.querySelectorAll("select").forEach(sel => sel.addEventListener("change", e => { state[sel.dataset.f] = e.target.value; render(); }));
  render();
}

/* ---------- pages ---------- */
function chamberCard(el, ch){
  const c = F.chambers[ch]; if (!c){ el.innerHTML = "<p class='small'>Not forecast (missing inputs).</p>"; return; }
  const name = ch==="H"?"Texas House":"Texas Senate", pr = c.p_rep_control, pdm = c.p_dem_control;
  const fav = pr >= pdm ? ["Republicans", pr, "rep"] : ["Democrats", pdm, "dem"];
  const up = seats.filter(s=>s.chamber===ch && s.contest!=="not_up").length;
  el.innerHTML = `<h2><a href="${window.ROOT||""}${ch==="H"?"house":"senate"}.html">${name}</a></h2>
    <div class="hero"><div class="big ${fav[2]}">${fmtP(fav[1])}</div><div>chance <b>${fav[0]}</b> keep control<br><span class="small">Democrats ${fmtP(pdm)} · Republicans ${fmtP(pr)}${c.p_no_majority>0.005?" · no majority "+fmtP(c.p_no_majority):""}</span></div></div>
    <p>Expected: <b class="dem">${c.dem_seats_mean.toFixed(1)} D</b> / <b class="rep">${c.rep_seats_mean.toFixed(1)} R</b> of ${ch==="H"?150:31}; 80% range ${c.dem_seats_p10}–${c.dem_seats_p90} Democratic seats. ${c.current?`Now ${c.current.dem} D, ${c.current.rep} R${c.current.vacancies?`, ${c.current.vacancies} vacant`:""}.`:""} ${ch==="S"?`${up} of 31 seats on the ballot.`:""}</p>
    <div data-hist></div><p class="small">Share of 40,000 simulations by number of Democratic seats${ch==="S"?" (including seats not up)":""}.</p>`;
  seatHistogram($("[data-hist]", el), c.seat_distribution, c.majority, c.current ? c.current.dem : null);
}
function closest(el, n){
  const r = seats.filter(s=>s.contest==="D_vs_R").sort((a,b)=>Math.abs(a.p_dem-.5)-Math.abs(b.p_dem-.5)).slice(0,n);
  el.innerHTML = `<div class="tablewrap"><table><thead><tr><th>District</th><th>Held by</th><th>Democrat</th><th>Republican</th><th class="num">Dem win</th><th class="num">Exp. margin</th></tr></thead><tbody>` +
    r.map(s=>`<tr><td><a href="${href(s)}">${label(s)}</a></td><td>${s.incumbent_party?`<span class="pill ${s.incumbent_party}">${s.incumbent_party}</span>`:"vacant"}</td><td>${esc(s.dem_name)}${s.dem_incumbent?" (i)":""}</td><td>${esc(s.rep_name)}${s.rep_incumbent?" (i)":""}</td><td class="num">${fmtP(s.p_dem)}</td><td class="num">${fmtM(s.margin_mean)}</td></tr>`).join("") + `</tbody></table></div>`;
}
function flips(el){
  const r = seats.filter(s=>s.contest!=="not_up" && s.incumbent_party && ((s.incumbent_party==="D"&&s.p_dem<.5)||(s.incumbent_party==="R"&&s.p_dem>=.5) || Math.min(s.incumbent_party==="D"?1-s.p_dem:s.p_dem, 1) >= .25))
    .map(s=>({s, pf: s.incumbent_party==="D"?1-s.p_dem:s.p_dem})).sort((a,b)=>b.pf-a.pf);
  el.innerHTML = r.length ? `<div class="tablewrap"><table><thead><tr><th>District</th><th>Held by</th><th class="num">Chance of flipping</th><th>Favored</th></tr></thead><tbody>` +
    r.map(({s,pf})=>`<tr><td><a href="${href(s)}">${label(s)}</a> <span class="small">${esc(s.region)}</span></td><td><span class="pill ${s.incumbent_party}">${s.incumbent_party}</span>${s.open_seat?" <span class='small'>open</span>":""}</td><td class="num">${fmtP(pf)}</td><td>${s.p_dem>=.5?'<span class="dem">D</span>':'<span class="rep">R</span>'} ${fmtP(Math.max(s.p_dem,s.p_rep))}</td></tr>`).join("") + `</tbody></table></div>` : "<p>No seat has at least a 25% chance of changing hands.</p>";
}
function tippingPage(el, ch){
  const c = F.chambers[ch]; if (!c) { el.innerHTML = "<p class='small'>Not forecast.</p>"; return; }
  const r = seats.filter(s=>s.chamber===ch).sort((a,b)=>(b.tipping_prob||0)-(a.tipping_prob||0)).filter(s=>s.tipping_prob>0.002).slice(0,25);
  const ordered = seats.filter(s=>s.chamber===ch).slice().sort((a,b)=>(b.p_dem??(b.incumbent_party==="D"?1:0))-(a.p_dem??(a.incumbent_party==="D"?1:0)));
  const rank = Object.fromEntries(ordered.map((s,i)=>[s.key,i+1]));
  el.innerHTML = `<p>The tipping-point seat is the one that delivers the ${c.majority}th seat when every seat is ordered from most to least Democratic in a simulation. Seats are listed by how often they play that role across 40,000 runs; the rank column shows the seat's place in that ordering by win probability.</p>
  <div class="tablewrap"><table><thead><tr><th>District</th><th class="num">Tipping-point chance</th><th class="num">Rank (most D → least D)</th><th class="num">Dem win</th><th class="num">Exp. margin</th></tr></thead><tbody>` +
  r.map(s=>`<tr><td><a href="${href(s)}">${label(s)}</a> <span class="small">${esc(s.dem_name||"")}${s.dem_name&&s.rep_name?" vs ":""}${esc(s.rep_name||"")}</span></td><td class="num">${(s.tipping_prob*100).toFixed(1)}%</td><td class="num">${rank[s.key]}</td><td class="num">${fmtP(s.p_dem)}</td><td class="num">${fmtM(s.margin_mean)}</td></tr>`).join("") + `</tbody></table></div>`;
}
function districtPage(el, key){
  const s = byKey[key]; if (!s) { el.innerHTML = "Unknown district"; return; }
  const env = F.environment, cfg = F.config;
  let h = `<h1>${label(s)} <span class="small">${esc(s.region)}</span></h1>`;
  if (s.contest === "not_up") { h += `<p class="sub">This seat is not on the 2026 ballot. Held by ${s.incumbent_party==="D"?"a Democrat":s.incumbent_party==="R"?"a Republican":"—"}${s.notes?` · ${esc(s.notes)}`:""}.</p>`; el.innerHTML = h; return; }
  h += `<p class="sub">${rating(s)} · held by ${s.incumbent_party?`<span class="pill ${s.incumbent_party}">${s.incumbent_party}</span>`:"vacant"}${s.open_seat?" · open seat":""}${s.notes?` · ${esc(s.notes)}`:""}</p>`;
  h += `<div class="grid"><div class="card"><h2>Candidates</h2><div class="kv">`;
  if (s.dem_name) h += `<b>Democrat</b><span>${esc(s.dem_name)}${s.dem_incumbent?" (incumbent)":""} — <b class="dem">${fmtP(s.p_dem)}</b></span>`;
  if (s.rep_name) h += `<b>Republican</b><span>${esc(s.rep_name)}${s.rep_incumbent?" (incumbent)":""} — <b class="rep">${fmtP(s.p_rep)}</b></span>`;
  if (s.other_names) h += `<b>Other</b><span>${esc(s.other_names)} — <b class="oth">${fmtP(s.p_other)}</b></span>`;
  if (s.contest === "D_vs_R") h += `<b>Expected margin</b><span>${fmtM(s.margin_mean)} <span class="small">(80% range ${fmtM(s.margin_p10)} to ${fmtM(s.margin_p90)})</span></span>`;
  if (s.contest === "D_vs_other" || s.contest === "R_vs_other") h += `<b>Expected margin</b><span>${s.contest==="D_vs_other"?"D":"R"}+${(s.margin_mean||0).toFixed(1)} over the strongest other candidate <span class="small">(80% range ${(s.margin_p10||0).toFixed(1)} to ${(s.margin_p90||0).toFixed(1)})</span></span>`;
  if (s.contest === "uncontested") h += `<b>Status</b><span>Only one candidate is on the ballot.</span>`;
  h += `<b>Tipping-point chance</b><span>${((s.tipping_prob||0)*100).toFixed(1)}%</span></div></div>`;
  h += `<div class="card"><h2>Partisan baseline</h2><div class="kv">`;
  const races = [["pres_2024","President 2024"],["sen_2024","U.S. Senate 2024"],["gov_2022","Governor 2022"],["ag_2022","Attorney General 2022"],["pres_2020","President 2020"]];
  races.forEach(([k,n]) => { if (s["margin_"+k] != null) h += `<b>${n}</b><span>${fmtM(s["margin_"+k])} <span class="small">(lean ${fmtM(s["lean_"+k])} vs statewide ${fmtM(F.statewide_margins[k])})</span></span>`; });
  h += `<b>Blended statewide lean</b><span>${fmtM(s.lean_statewide)}</span>`;
  if (s.lean_legislative != null) h += `<b>Legislative-race lean</b><span>${fmtM(s.lean_legislative)} <span class="small">(${esc(s.leg_contested_years||"")} contested)</span></span>`;
  h += `<b>Final lean</b><span>${fmtM(s.lean)}</span><b>Hispanic (SSVR) share</b><span>${s.ssvr!=null?(s.ssvr*100).toFixed(0)+"%":"—"}</span></div></div></div>`;
  if (s.contest === "D_vs_R" || s.contest === "D_vs_other" || s.contest === "R_vs_other") {
    const a = s.adj_used || {}; const steps = [{label:"District lean", value: s.lean, total:true}, {label:"2026 statewide environment", value: env.expected_statewide_margin}];
    if (a.incumbency) steps.push({label:"Incumbency", value:a.incumbency}); if (a.prior_performance) steps.push({label:"Past over/under-performance", value:a.prior_performance});
    if (a.prior_nominee) steps.push({label:"Prior nominee here", value:a.prior_nominee}); if (a.finance) steps.push({label:"Campaign finance", value:a.finance});
    if (s.ratings_shift) steps.push({label:"External ratings", value:s.ratings_shift}); if (s.poll_shift) steps.push({label:"District polls", value:s.poll_shift});
    steps.push({label:"Expected D−R margin", value: s.mu, total:true});
    h += `<h2>How each input moves the forecast</h2><div class="card"><div data-wf></div><p class="small">Statewide environment is the model's expected 2026 statewide margin for a generic legislative race (${fmtM(env.expected_statewide_margin)}, a swing of ${env.swing_vs_reference>0?"D":"R"}+${Math.abs(env.swing_vs_reference).toFixed(1)} from the 2024 presidential result). Simulation adds statewide, regional, Hispanic-share and district error (district s.d. ${s.sd_district?s.sd_district.toFixed(1):"—"} points).</p></div>`;
  }
  h += `<h2>Inputs on record</h2><div class="grid">`;
  h += `<div class="card"><h3>Campaign finance (TEC, 2025–26 receipts)</h3><div class="kv"><b>Democrat</b><span>${s.dem_receipts!=null?"$"+Math.round(s.dem_receipts).toLocaleString():"no match / not applicable"}</span><b>Republican</b><span>${s.rep_receipts!=null?"$"+Math.round(s.rep_receipts).toLocaleString():"no match / not applicable"}</span></div><p class="small">Totals from cover sheets of reports filed since Jan 2025, with a $${cfg.candidate.finance.floor_dollars.toLocaleString()} floor on each side.</p></div>`;
  if (s.special_election) h += `<div class="card"><h3>2025–26 special election</h3><p>${esc(s.special_election.winner)} won the special election${s.special_election.runoff?" runoff ("+esc(s.special_election.runoff)+")":" ("+esc(s.special_election.date)+")"} with D ${s.special_election.dem_pct}% to R ${s.special_election.rep_pct}%. ${F.config.candidate.special_election_carryover*100}% of the over-performance versus the district baseline is carried into this forecast.</p></div>`;
  h += `<div class="card"><h3>External ratings</h3>` + ((s.rating_rows&&s.rating_rows.length) ? `<table><tbody>${s.rating_rows.map(r=>`<tr><td>${r.url?`<a href="${esc(r.url)}" rel="noopener">${esc(r.source)}</a>`:esc(r.source)}</td><td>${esc(r.rating)}</td><td class="num">${r.implied!=null?fmtM(r.implied):"competitive flag"}</td></tr>`).join("")}</tbody></table>` : "<p class='small'>No external rating or target-list entry found for this district.</p>") + `</div>`;
  h += `<div class="card"><h3>District polls</h3>` + ((s.poll_rows&&s.poll_rows.length) ? `<table><tbody>${s.poll_rows.map(p=>`<tr><td>${esc(p.pollster)}${p.internal?" <span class='small'>(internal)</span>":""}</td><td>${esc(p.end_date)}</td><td class="num">D ${p.dem} · R ${p.rep}</td></tr>`).join("")}</tbody></table>` : "<p class='small'>No public district-level poll found.</p>") + `</div></div>`;
  el.innerHTML = h; const wf = $("[data-wf]", el); if (wf) waterfall(wf, [{label:"District lean", value:s.lean, total:true}, {label:"Statewide environment", value:env.expected_statewide_margin}, ...Object.entries(s.adj_used||{}).filter(([k,v])=>v).map(([k,v])=>({label:{incumbency:"Incumbency",prior_performance:"Past performance",prior_nominee:"Prior nominee",finance:"Campaign finance",special_election:"2025-26 special election"}[k]||k, value:v})), ...(s.ratings_shift?[{label:"External ratings", value:s.ratings_shift}]:[]), ...(s.poll_shift?[{label:"District polls", value:s.poll_shift}]:[]), {label:"Expected margin", value:s.mu, total:true}]);
}
function envTable(el){
  const env = F.environment; let h = `<table><thead><tr><th>Indicator</th><th class="num">Polls</th><th class="num">Raw average</th><th class="num">Implied generic margin</th><th class="num">Weight</th></tr></thead><tbody>`;
  env.components.forEach(c => h += `<tr><td>${{tx_generic:"Texas generic/legislative preference",tx_sen:"Texas U.S. Senate race",tx_gov:"Texas governor race (minus incumbent edge)",us_generic:"National generic ballot + Texas lean",tx_abbott_approval:"Abbott net approval"}[c.indicator]||c.indicator}</td><td class="num">${c.polls}</td><td class="num">${c.raw_average!=null?fmtM(c.raw_average):"—"}</td><td class="num">${c.implied_margin!=null?fmtM(c.implied_margin):"—"}</td><td class="num">${c.weight}</td></tr>`);
  h += `<tr><td><b>Poll-based margin</b></td><td></td><td></td><td class="num"><b>${env.poll_based_margin!=null?fmtM(env.poll_based_margin):"—"}</b></td><td class="num">${(1-env.prior_weight).toFixed(2)}</td></tr>`;
  h += `<tr><td><b>Structural midterm prior</b> (2024 presidential ${fmtM(env.reference_margin)} shifted ${F.config.environment.midterm_prior.swing_toward_out_party} toward the out-party)</td><td></td><td></td><td class="num"><b>${fmtM(env.midterm_prior_margin)}</b></td><td class="num">${env.prior_weight.toFixed(2)}</td></tr>`;
  h += `<tr><td><b>Expected 2026 statewide margin</b></td><td></td><td></td><td class="num"><b>${fmtM(env.expected_statewide_margin)}</b></td><td></td></tr></tbody></table>`;
  el.innerHTML = h;
}
function pollList(el){
  const rows = []; F.environment.components.forEach(c => (c.rows||[]).forEach(r => rows.push({...r, ind:c.indicator})));
  rows.sort((a,b)=>a.end_date<b.end_date?1:-1);
  el.innerHTML = rows.length ? `<div class="tablewrap"><table><thead><tr><th>Race</th><th>Pollster</th><th>End date</th><th class="num">n</th><th class="num">Dem</th><th class="num">Rep</th><th class="num">Adj. margin</th><th class="num">Weight</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${r.ind}</td><td>${r.url?`<a href="${esc(r.url)}" rel="noopener">${esc(r.pollster)}</a>`:esc(r.pollster)}${r.internal?" <span class='small'>(partisan)</span>":""}</td><td>${r.end_date}</td><td class="num">${r.sample_size||""}</td><td class="num">${r.dem}</td><td class="num">${r.rep}</td><td class="num">${fmtM(r.margin)}</td><td class="num">${r.weight}</td></tr>`).join("")}</tbody></table></div>` : "<p class='small'>No statewide polls loaded.</p>";
}
function sensTable(el){
  const S = F.sensitivity || []; const names = {district_polls:"District-level polls", "ratings_State Navigate":"State Navigate ratings", ratings_CNalysis:"CNalysis ratings", ratings_Ballotpedia:"Ballotpedia battleground list", ratings_other:"Other ratings & target lists", finance:"Campaign finance", midterm_prior:"Structural midterm prior", statewide_polls:"Statewide polling"};
  el.innerHTML = `<div class="tablewrap"><table><thead><tr><th>Source removed</th><th class="num">House: Δ expected D seats</th><th class="num">House: Δ P(D control)</th><th class="num">Senate: Δ expected D seats</th><th class="num">Senate: Δ P(D control)</th></tr></thead><tbody>${S.map(r=>`<tr><td>${names[r.source]||r.source}</td><td class="num">${r.H_dem_seats_delta!=null?(r.H_dem_seats_delta>0?"+":"")+r.H_dem_seats_delta.toFixed(2):"—"}</td><td class="num">${r.H_p_dem_control_delta!=null?(r.H_p_dem_control_delta>0?"+":"")+(r.H_p_dem_control_delta*100).toFixed(1)+" pts":"—"}</td><td class="num">${r.S_dem_seats_delta!=null?(r.S_dem_seats_delta>0?"+":"")+r.S_dem_seats_delta.toFixed(2):"—"}</td><td class="num">${r.S_p_dem_control_delta!=null?(r.S_p_dem_control_delta>0?"+":"")+(r.S_p_dem_control_delta*100).toFixed(1)+" pts":"—"}</td></tr>`).join("")}</tbody></table></div><p class="small">Each row shows how much the forecast moves because that source is included (forecast with the source minus forecast without it, same random seed, 10,000 simulations per variant). No public district-level poll with toplines was found for 2026, so that row is zero by construction.</p>`;
}
function backtestTable(el){
  if (!BT || !BT.results) { el.innerHTML = "<p class='small'>Backtest not available.</p>"; return; }
  let h = `<div class="tablewrap"><table><thead><tr><th>Year</th><th>Chamber</th><th class="num">Seats called</th><th class="num">Contested races called</th><th class="num">Brier (contested)</th><th class="num">Margin MAE</th><th class="num">Margin bias (D−R)</th><th class="num">80% interval coverage</th><th class="num">Forecast D seats</th><th class="num">Actual D seats</th></tr></thead><tbody>`;
  Object.values(BT.results).forEach(y => Object.entries(y.chambers).forEach(([ch,c]) => { const m = c.metrics; h += `<tr><td>${y.year}</td><td>${ch==="H"?"House":"Senate"}</td><td class="num">${m.seats_called}/${m.seats_scored} (${m.seats_called_pct}%)</td><td class="num">${m.contested_called}/${m.contested_races} (${m.contested_called_pct}%)</td><td class="num">${m.brier_contested}</td><td class="num">${m.margin_mae}</td><td class="num">${m.margin_bias_d_minus_r}</td><td class="num">${m.interval80_coverage}%</td><td class="num">${m.dem_seats_forecast_mean}</td><td class="num">${m.dem_seats_actual}</td></tr>`; }));
  h += `</tbody></table></div>`;
  Object.values(BT.results).forEach(y => Object.entries(y.chambers).forEach(([ch,c]) => { if (c.misses.length) h += `<p class="small"><b>${y.year} ${ch==="H"?"House":"Senate"} misses:</b> ${c.misses.map(m=>`${m.key} (forecast ${fmtP(m.p_dem)} D, actual ${m.actual_winner}+${Math.abs(m.actual_margin).toFixed(1)})`).join("; ")}</p>`; }));
  el.innerHTML = h;
}
window.TXF = {chamberCard, closest, flips, drawMap, seatTable, tippingPage, districtPage, envTable, pollList, sensTable, backtestTable, seats, F, rating, fmtP, fmtM, label, href};
document.querySelectorAll("[data-render]").forEach(el => { const [fn, arg] = el.dataset.render.split(":"); if (window.TXF[fn]) { if (fn === "seatTable") seatTable(el, seats.filter(s=>s.chamber===arg)); else window.TXF[fn](el, arg); } });
})();
