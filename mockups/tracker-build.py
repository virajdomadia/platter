"""Build mockups/tracker.html — the Platter tracker artifact — from PRD.md, docs/*.md and docs/07-plan.md.

Run from the project root:  python mockups/tracker-build.py
Then publish mockups/tracker.html with the Artifact tool (capabilities: {db: {}, user: {}}), keeping the same URL.
Row status lives in the artifact db at rows/<id> = {status: "todo"|"doing"|"done", updated}.
"""
import json, re, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ["PRD.md", "docs/03-requirements.md", "docs/03-user-flows.md", "docs/04-technical-design.md",
        "docs/04-ui-mockups.md", "docs/05-architecture.md", "docs/06-data-and-api.md", "docs/07-plan.md"]
LINKS = {
    "variants": "https://claude.ai/artifact/JAekpL7HjR4oU5c39ak7dg",
    "screens": "https://claude.ai/artifact/GGchE2CjZ7DN5t83pzs9Cu",
    "landing": "https://platter-viraj.vercel.app",
    "repo": "https://github.com/virajdomadia/platter",
}

def read(p): return (ROOT / p).read_text(encoding="utf-8")

# ── plan rows ──
rows, version, milestone = [], "", ""
for line in read("docs/07-plan.md").splitlines():
    m = re.match(r"^## (v\d) — (.+?) \(", line)
    if m: version = f"{m.group(1)} {m.group(2)}"; continue
    m = re.match(r"^### (Milestone [\d.]+) — (.+?) \(≈ ([\d.]+) h\)", line)
    if m: milestone = f"{m.group(1)} · {m.group(2)}"; continue
    if line.startswith("## Whole-product"): break
    m = re.match(r"^\| ([SFLAU]\d+) \| \*\*(.+?)\*\* \|(.*)\|$", line)
    if m:
        cells = [c.strip() for c in m.group(3).split("|")]
        est = next((c for c in cells if re.fullmatch(r"[\d.]+ h", c)), "")
        rows.append({"id": m.group(1), "part": m.group(2), "version": version, "milestone": milestone, "est": est, "done": cells[-1]})

docs = [{"name": p.split("/")[-1].replace(".md", ""), "path": p, "md": read(p)} for p in DOCS]

html = r'''<title>Platter Tracker</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Nunito:wght@600;700;800;900&family=JetBrains+Mono:wght@400;500&display=swap">
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.9.1/mermaid.min.js"></script>
<style>
:root{--bg:#F3F0FF;--bg-2:#FFFFFF;--ink:#1F1B2E;--ink-2:#3B3552;--muted:#8D87A3;--line:#E6DEFF;--lav:#E6DEFF;--mint:#D9F5E3;--peach:#FFE1D1;--lemon:#FFF1B8;--sky:#D8EDFF;--violet:#7B5CFF;--coral:#FF7A59;--green:#2ECC71;--amber:#B8860B;--mintink:#1B7F3B;
  --font:"Nunito",system-ui,sans-serif;--mono:"JetBrains Mono",ui-monospace,Menlo,Consolas,monospace;--sh:0 2px 0 rgba(31,27,46,.05),0 10px 24px rgba(31,27,46,.06)}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#17141F;--bg-2:#221E2E;--ink:#F3F0FF;--ink-2:#CFC9E0;--muted:#8D87A3;--line:#332D45;--lav:#2E2748;--mint:#1E3A2A;--peach:#42291F;--lemon:#3F371A;--sky:#1E2F40;--mintink:#6CCB91;--amber:#E2B84C;--sh:none}}
:root[data-theme="dark"]{--bg:#17141F;--bg-2:#221E2E;--ink:#F3F0FF;--ink-2:#CFC9E0;--muted:#8D87A3;--line:#332D45;--lav:#2E2748;--mint:#1E3A2A;--peach:#42291F;--lemon:#3F371A;--sky:#1E2F40;--mintink:#6CCB91;--amber:#E2B84C;--sh:none}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font);font-size:14.5px;font-weight:600;line-height:1.5;padding-inline:clamp(16px,3vw,40px);padding-block:0 80px}
a{color:var(--violet)}
.top{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:16px;padding-block:26px 14px}
.top h1{margin:0;font-size:clamp(28px,3vw,38px);font-weight:900;letter-spacing:-.03em}
.eyebrow{font-weight:800;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
.stats{display:flex;gap:10px;flex-wrap:wrap}
.stats div{background:var(--bg-2);border-radius:18px;padding:10px 16px;box-shadow:var(--sh);font-size:12px;font-weight:800;color:var(--muted)}
.stats b{color:var(--ink);font-weight:900;font-size:24px;display:block;line-height:1;letter-spacing:-.03em}
.stats div:nth-child(1){background:var(--mint)}.stats div:nth-child(2){background:var(--lav)}.stats div:nth-child(3){background:var(--lemon)}.stats div:nth-child(4){background:var(--sky)}
.tabs{display:flex;gap:6px;flex-wrap:wrap;position:sticky;top:0;z-index:20;background:var(--bg);padding-block:10px}
.tab{appearance:none;border:0;background:var(--bg-2);color:var(--ink);font:900 14px/1 var(--font);padding:10px 16px;border-radius:14px;cursor:pointer;box-shadow:var(--sh)}
.tab[aria-selected="true"]{background:var(--ink);color:var(--bg)}
.tab:focus-visible{outline:3px solid var(--violet);outline-offset:2px}
.panel{display:none;padding-top:20px}.panel.on{display:block}
/* plan */
.ver{margin-top:22px;background:var(--bg-2);border-radius:24px;padding:16px 18px;box-shadow:var(--sh)}
.ver h2{font-size:22px;font-weight:900;margin:0 0 4px;display:flex;align-items:baseline;gap:12px;letter-spacing:-.02em}
.ver h2 small{font-weight:800;font-size:12px;color:var(--muted)}
.ms{font-weight:900;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--violet);margin:16px 0 4px}
.rows{display:flex;flex-direction:column}
.rw{display:grid;grid-template-columns:52px 1fr auto auto;gap:12px;align-items:center;border-top:1px solid var(--line);padding:9px 4px}
.rw .id{font-family:var(--mono);font-size:12px;color:var(--muted)}
.rw .part{font-weight:900}
.rw .done{font-size:12.5px;color:var(--ink-2);margin-top:2px;font-weight:600}
.rw .est{font-weight:900;font-size:13px;color:var(--muted);white-space:nowrap}
.st{appearance:none;border:0;background:var(--lav);color:var(--ink);font:900 11px var(--font);letter-spacing:.08em;text-transform:uppercase;padding:7px 12px;border-radius:999px;cursor:pointer;display:inline-flex;gap:7px;align-items:center;min-width:92px;justify-content:center}
.st[data-s="doing"]{background:var(--lemon)}
.st[data-s="done"]{background:var(--mint);color:var(--mintink)}
.st:disabled{cursor:default;opacity:.8}
.rw.done-row .part{color:var(--muted);text-decoration:line-through;text-decoration-color:var(--green)}
.bar{height:10px;border-radius:999px;background:linear-gradient(90deg,var(--green) var(--p,0%),var(--line) 0);margin:6px 0 4px;max-width:420px}
.note{font-weight:700;font-size:13px;color:var(--muted);margin-top:14px}
/* docs */
.docnav{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:16px}
.docnav button{appearance:none;border:0;background:var(--bg-2);color:var(--ink-2);font:800 12px var(--font);padding:8px 12px;border-radius:12px;cursor:pointer;box-shadow:var(--sh)}
.docnav button[aria-selected="true"]{background:var(--violet);color:#fff}
.md{max-width:920px;font-size:14.5px;background:var(--bg-2);padding:22px 28px;border-radius:24px;box-shadow:var(--sh);font-weight:600}
.md h1{font-weight:900;font-size:26px;letter-spacing:-.03em}.md h2{font-weight:900;font-size:20px;margin-top:32px;padding-top:12px;border-top:2px dashed var(--line)}.md h3{font-size:15.5px;margin-top:22px;font-weight:900}
.md p,.md li{color:var(--ink-2)}.md strong{color:var(--ink);font-weight:900}
.md code{font-family:var(--mono);font-size:12.5px;background:var(--bg);border-radius:6px;padding:1px 5px;font-weight:500}
.md pre{background:var(--bg);border-radius:14px;padding:14px;overflow-x:auto;font-size:12.5px}
.md pre code{background:none;border:0;padding:0}
.md .tbl{overflow-x:auto}.md table{border-collapse:collapse;font-size:13px;min-width:600px}.md th,.md td{border:1px solid var(--line);padding:7px 9px;text-align:left;vertical-align:top}.md th{background:var(--bg);font-weight:900;font-size:11.5px;letter-spacing:.04em}
.md pre.mermaid{background:var(--bg-2);text-align:center}
/* mockups + project */
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}
.card{border-radius:24px;padding:18px;background:var(--bg-2);box-shadow:var(--sh)}
.card:nth-child(1){background:var(--lav)}.card:nth-child(2){background:var(--mint)}.card:nth-child(3){background:var(--lemon)}.card:nth-child(4){background:var(--sky)}
.card h3{margin:0 0 8px;font-weight:900;font-size:18px;letter-spacing:-.02em}.card p{margin:0 0 12px;color:var(--ink-2);font-size:13.5px}
.card .k{font-weight:900;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:6px}
.btnl{display:inline-block;font:900 13px var(--font);color:#fff;background:var(--ink);padding:9px 14px;border-radius:999px;text-decoration:none}
.kv{display:grid;grid-template-columns:160px 1fr;gap:8px 16px;font-size:13.5px;max-width:860px;background:var(--bg-2);border-radius:24px;padding:18px 22px;box-shadow:var(--sh)}
.kv dt{font-weight:900;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);padding-top:2px}.kv dd{margin:0;color:var(--ink-2)}.kv dd b{color:var(--ink);font-weight:900}
@media (max-width:700px){.rw{grid-template-columns:44px 1fr;grid-auto-rows:auto}.rw .est,.rw .st{grid-column:2}.kv{grid-template-columns:1fr}}
</style>
<header class="top">
  <div><div class="eyebrow">Platter · project 6 of 6 · tracker</div><h1>Platter tracker 🛵</h1></div>
  <div class="stats"><div><b id="st-done">0</b>rows done</div><div><b id="st-total">0</b>rows</div><div><b id="st-hours">0 h</b>planned</div><div><b id="st-step">7</b>lifecycle steps done</div></div>
</header>
<nav class="tabs" role="tablist"><button class="tab" role="tab" aria-selected="true" data-p="plan">Plan</button><button class="tab" role="tab" aria-selected="false" data-p="docs">Docs</button><button class="tab" role="tab" aria-selected="false" data-p="mockups">Mockups</button><button class="tab" role="tab" aria-selected="false" data-p="project">Project</button></nav>

<section class="panel on" id="p-plan"><div id="plan"></div><div class="note" id="plan-note">Click a status pill to cycle todo → doing → done. Status is shared with everyone who can open this page.</div></section>
<section class="panel" id="p-docs"><div class="docnav" id="docnav"></div><article class="md" id="doc"></article></section>
<section class="panel" id="p-mockups"><div class="cards" id="mock"></div></section>
<section class="panel" id="p-project"><dl class="kv" id="proj"></dl></section>

<script id="data" type="application/json">__DATA__</script>
<script>
(function(){
  const D = JSON.parse(document.getElementById('data').textContent);
  const rows = D.rows, docs = D.docs, L = D.links;
  const status = {};
  let db = null, canWrite = true;

  const planEl = document.getElementById('plan');
  function renderPlan(){
    const byVer = {}; rows.forEach(r=>{ (byVer[r.version] ||= []).push(r); });
    planEl.innerHTML = '';
    for(const [ver, rs] of Object.entries(byVer)){
      const done = rs.filter(r=>status[r.id]?.status==='done').length;
      const hours = rs.reduce((a,r)=>a+parseFloat(r.est||0),0);
      const sec = document.createElement('div'); sec.className='ver';
      sec.innerHTML = `<h2>${ver} <small>${rs.length} rows · ≈ ${hours} h · ${done} done</small></h2><div class="bar" style="--p:${rs.length?done/rs.length*100:0}%"></div>`;
      let ms = '';
      rs.forEach(r=>{
        if(r.milestone!==ms){ ms=r.milestone; const h=document.createElement('div'); h.className='ms'; h.textContent=ms; sec.appendChild(h); }
        const s = status[r.id]?.status || 'todo';
        const el = document.createElement('div'); el.className='rw'+(s==='done'?' done-row':'');
        el.innerHTML = `<span class="id">${r.id}</span><div><div class="part">${r.part}</div><div class="done">${r.done}</div></div><span class="est">${r.est||''}</span><button class="st" data-s="${s}" data-id="${r.id}" ${canWrite?'':'disabled'}>${s}</button>`;
        sec.appendChild(el);
      });
      planEl.appendChild(sec);
    }
    const total = rows.length, done = rows.filter(r=>status[r.id]?.status==='done').length;
    document.getElementById('st-done').textContent = done; document.getElementById('st-total').textContent = total;
    document.getElementById('st-hours').textContent = Math.round(rows.reduce((a,r)=>a+parseFloat(r.est||0),0)) + ' h';
  }
  planEl.addEventListener('click', async e=>{
    const b = e.target.closest('.st'); if(!b || !db || !canWrite) return;
    const id = b.dataset.id, next = {todo:'doing', doing:'done', done:'todo'}[b.dataset.s];
    b.disabled = true;
    try{ await db.doc('rows/'+id).set({status: next, updated: new Date().toISOString()}); }
    catch(err){ if(err && (err.code==='not_granted' || err.code==='permission_denied')){ canWrite=false; document.getElementById('plan-note').textContent='Read-only for you — status can only be changed by editors.'; } }
    b.disabled = false;
  });
  renderPlan();
  (async()=>{
    db = await claude.use('db');
    if(!db){ document.getElementById('plan-note').textContent = 'Status is not available in this view.'; canWrite=false; renderPlan(); return; }
    const user = await claude.use('user'); const cw = user ? await user.can('data.write') : null; if(cw===false){ canWrite=false; document.getElementById('plan-note').textContent='Read-only for you — status can only be changed by editors.'; }
    db.collection('rows').onSnapshot(snap=>{ snap.docs.forEach(d=>{ if(d.exists) status[d.id]=d.data(); }); snap.docChanges().forEach(c=>{ if(c.type==='removed') delete status[c.doc.id]; }); renderPlan(); }, ()=>{});
  })();

  const nav = document.getElementById('docnav'), art = document.getElementById('doc');
  const renderer = new marked.Renderer();
  renderer.code = function(code, lang){ const c = typeof code==='object' ? code.text : code; const l = typeof code==='object' ? code.lang : lang; if(l==='mermaid') return '<pre class="mermaid">'+c.replace(/</g,'&lt;')+'</pre>'; return '<pre><code>'+c.replace(/&/g,'&amp;').replace(/</g,'&lt;')+'</code></pre>'; };
  renderer.table = function(header, body){ if(typeof header==='object'){ const t=header; const h='<tr>'+t.header.map(c=>'<th>'+marked.parseInline(c.text)+'</th>').join('')+'</tr>'; const b=t.rows.map(r=>'<tr>'+r.map(c=>'<td>'+marked.parseInline(c.text)+'</td>').join('')+'</tr>').join(''); return '<div class="tbl"><table><thead>'+h+'</thead><tbody>'+b+'</tbody></table></div>'; } return '<div class="tbl"><table><thead>'+header+'</thead><tbody>'+body+'</tbody></table></div>'; };
  function showDoc(i){ nav.querySelectorAll('button').forEach((b,j)=>b.setAttribute('aria-selected', i===j)); art.innerHTML = marked.parse(docs[i].md, {renderer, gfm:true}); art.querySelectorAll('a[href^="docs/"],a[href^="../"],a[href$=".md"]').forEach(a=>{ const n=a.getAttribute('href').split('/').pop().replace('.md',''); const k=docs.findIndex(d=>d.name===n); if(k>=0){ a.href='#'; a.onclick=e=>{e.preventDefault(); showDoc(k); window.scrollTo({top:0});}; } }); if(window.mermaid){ try{ mermaid.initialize({startOnLoad:false, theme:'neutral'}); mermaid.run({nodes: art.querySelectorAll('pre.mermaid')}); }catch(e){} } }
  docs.forEach((d,i)=>{ const b=document.createElement('button'); b.textContent=d.name; b.setAttribute('aria-selected', i===0); b.onclick=()=>showDoc(i); nav.appendChild(b); });
  showDoc(0);

  document.getElementById('mock').innerHTML = [
    ['Direction variants', 'Twelve directions over two rounds (A–F: Menu card, Night kitchen, Dabba, Dispatch, Newsprint, Poster · G–L: Glass, Zine, Receipt, Neon, Atlas, Bento), six screens each, twelve live motion candidates over a real Koramangala map. Chosen: L · Bento (2026-09-17).', L.variants, 'Open variants'],
    ['Screens · v1', 'Every v1 screen in Bento: home (phone + desktop), restaurant, cart, checkout (+ Razorpay dismissed), tracking (phone + desktop, live), orders, restaurant board, rider app (before / after sharing), admin map, sign in + demo, addresses, menu availability, states.', L.screens, 'Open screens'],
    ['Landing · live', 'The existing landing page, deployed on Vercel from web/ (will move to platter.virajdomadia.com).', L.landing, 'Open landing'],
    ['Photos + maps', 'CC dish photos from Wikimedia Commons and OpenStreetMap tiles of Koramangala / HSR in mockups/img/ with credits in CREDITS.md — Platter and its restaurants are fictional.', L.repo + '/blob/main/mockups/img/CREDITS.md', 'Credits'],
  ].map(([t,p,u,b])=>`<div class="card"><div class="k">mockup</div><h3>${t}</h3><p>${p}</p><a class="btnl" href="${u}" target="_blank" rel="noopener">${b} ↗</a></div>`).join('');

  document.getElementById('proj').innerHTML = [
    ['Name', '<b>Platter</b> · hot food, tracked to your door · project 6 of 6, build last'],
    ['One-liner', 'A four-sided food-delivery platform for one Bengaluru neighbourhood: customers watch the rider move on a real map, restaurants run a live board, riders share GPS from a phone, an admin sees everything — PostGIS, a role-guarded order state machine, live location over SSE with Postgres as the bus. ₹0 per order.'],
    ['URLs', 'platter.virajdomadia.com · api.platter.virajdomadia.com · landing at platter-viraj.vercel.app until DNS'],
    ['Repo', `<a href="${L.repo}" target="_blank" rel="noopener">github.com/virajdomadia/platter</a> · web/ Next.js 15 + MapLibre · api/ FastAPI + PostGIS + the stream loop`],
    ['Versions', '<b>v1 Kitchen</b> 16 h → <b>v2 Rush</b> 11 h → <b>v3 Fleet</b> 8 h → <b>v4 Order together</b> 3 h ≈ 38 h · add-ons after v4 only from time saved'],
    ['Unique feature', 'v4 Order together: one link, many phones — a group cart friends add to from their own phones, one pays, and the same link becomes everyone\'s live tracking page. ₹0 per use.'],
    ['Engine', 'Rider POSTs GPS every 3 s → rider_positions + rider_track; every transition appends to order_events (the bus); one stream loop serves customer / board / rider / admin over SSE with Last-Event-ID replay and a 280-s cut; sim riders advance lazily inside the tick; v3 swaps the 1-s poll for LISTEN/NOTIFY'],
    ['Geo at ₹0', 'PostGIS (ST_DWithin, KNN nearest rider) · MapLibre + OpenFreeMap tiles · OSRM public routes once per leg with a straight-line fallback · Photon geocoding'],
    ['Money', 'COD default + Razorpay (idempotent mark_paid) in v1; refunds + ledgers (restaurant 80/20, rider ₹30 + ₹8/km) + admin payouts in v2'],
    ['Seed', 'Koramangala + HSR · 12 fictional restaurants · ~100 dishes with CC photos · 8 sim riders + 1 demo rider · ~60 past orders · demo logins: customer, restaurant, rider, admin'],
    ['Direction', 'L · Bento — pastel tiles (lavender, mint, peach, lemon, sky), Nunito 900, the map as the biggest tile, tile spring on every screen; signature = Rider glide + Route draw on tracking, ticket print on the board'],
    ['Lifecycle', 'Steps 1–7 complete (2026-09-17). Next: step 8 = milestone 1.0, last in the build order (1 → 2 → 4 → 5 → 3 → 6)'],
    ['Rules', 'Lean setup, rich features · accounts just-in-time (Neon + PostGIS and Blob in S2; Razorpay in F3; VAPID in L2) · one PR per row, every PR visible in the browser · tests only from 04 §12 · tracker updated per milestone'],
  ].map(([k,v])=>`<dt>${k}</dt><dd>${v}</dd>`).join('');

  const tabs=[...document.querySelectorAll('.tab')];
  function show(p){ tabs.forEach(t=>t.setAttribute('aria-selected', t.dataset.p===p)); document.querySelectorAll('.panel').forEach(x=>x.classList.toggle('on', x.id==='p-'+p)); try{localStorage.setItem('pl-tab',p)}catch(e){} }
  tabs.forEach(t=>t.onclick=()=>show(t.dataset.p));
  let start='plan'; try{ start=localStorage.getItem('pl-tab')||'plan'; }catch(e){} show(start);
})();
</script>
'''
data = json.dumps({"rows": rows, "docs": docs, "links": LINKS}, ensure_ascii=False).replace("</", "<\\/")
out = ROOT / "mockups" / "tracker.html"
out.write_text(html.replace("__DATA__", data), encoding="utf-8", newline="\n")
print(f"wrote {out} · {len(rows)} rows · {len(docs)} docs")
for r in rows: print(" ", r["id"], r["est"], r["part"][:40])
