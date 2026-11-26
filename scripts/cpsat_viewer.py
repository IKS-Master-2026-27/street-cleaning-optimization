"""Build an offline HTML viewer for the cold/warm CP-SAT results.

Reads ``results/cpsat/`` (``results.csv``, ``metadata_part*.json`` and every
``jobs/<instance>_<variant>/progress.csv``) and writes one self-contained page,
``results/cpsat/viewer.html``. Open it in any browser: no server, no internet.

    python scripts/cpsat_viewer.py                 # results/cpsat/viewer.html
    python scripts/cpsat_viewer.py --out other/dir # another results folder

``scripts/run_cpsat.py`` rebuilds the page after every finished batch.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS = {"solution": 0, "round_end": 1, "event": 2}


def _num(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except ValueError:
        return value


def load(out: Path) -> dict:
    """Everything the page needs, as plain JSON-able data."""

    rows = []
    with (out / "results.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows.append({k: (_num(v) if k not in ("instance", "variant", "result", "reason",
                                                   "seed_algorithm", "cpsat_status", "message",
                                                   "hint_feasible", "valid") else v)
                         for k, v in row.items()})
    progress = {}
    for row in rows:
        path = out / "jobs" / f"{row['instance']}_{row['variant']}" / "progress.csv"
        if not path.is_file():
            continue
        points = []
        with path.open(encoding="utf-8") as handle:
            for p in csv.DictReader(handle):
                points.append([float(p["seconds"]), int(p["round"] or 0),
                               EVENTS.get(p["event"], 2), _num(p["objective_score"]),
                               _num(p["bound_score"]), 1 if p["valid"] == "True" else 0])
        progress[f"{row['instance']}_{row['variant']}"] = points
    metadata = {}
    for path in sorted(out.glob("metadata*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        metadata[path.stem] = {k: data.get(k) for k in (
            "part", "model", "ortools", "python", "platform", "cpu_count", "time_limit_s",
            "workers", "random_seed", "build_limit_s", "seed_algorithm", "started_utc")}
    return {"rows": rows, "progress": progress, "metadata": metadata}


def build(out: Path) -> Path:
    data = json.dumps(load(out), separators=(",", ":")).replace("</", "<\\/")
    page = out / "viewer.html"
    page.write_text(TEMPLATE.replace("__DATA__", data), encoding="utf-8")
    return page


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="results/cpsat", help="results folder of run_cpsat.py")
    args = parser.parse_args()
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    print(f"Viewer: {build(out)}")
    return 0


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MILP cold vs warm start · results viewer</title>
<style>
:root{--ink:#161a2e;--muted:#646b82;--acc:#4f46e5;--acc2:#eceafd;--or:#d9620f;--or2:#fdeedd;--gr:#15925a;--gr2:#e3f4ea;--x:#7a8096;--x2:#eceef4;--line:#e4e5ef;--card:#fff}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;color:var(--ink);background:#f4f5fa}
header{background:#fff;border-bottom:1px solid var(--line);padding:18px 32px 0;position:sticky;top:0;z-index:5}
header h1{margin:0;font-size:22px}
header .sub{color:var(--muted);font-size:14px;margin:4px 0 12px}
nav{display:flex;gap:4px}
nav button{border:0;background:none;padding:10px 16px;font-size:15px;font-weight:600;color:var(--muted);border-bottom:3px solid transparent;cursor:pointer}
nav button.on{color:var(--acc);border-bottom-color:var(--acc)}
main{padding:24px 32px 60px;max-width:1500px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px 22px;margin-bottom:18px}
.card h2{font-size:17px;margin:0 0 12px}
.grid{display:grid;gap:18px}
.g2{grid-template-columns:1fr 1fr}.g4{grid-template-columns:repeat(4,1fr)}
.kpi .v{font-size:30px;font-weight:700}.kpi .l{color:var(--muted);font-size:14px;margin-top:4px}
table{border-collapse:collapse;width:100%;font-size:14px}
th{text-align:left;font-weight:600;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.5px;padding:8px;border-bottom:1px solid var(--line)}
td{padding:9px 8px;border-bottom:1px solid #f0f1f6;vertical-align:top}
td.n{font-variant-numeric:tabular-nums;white-space:nowrap}
tr.click{cursor:pointer}tr.click:hover td{background:#f7f7fd}
.pill{display:inline-block;font-size:12.5px;font-weight:600;border-radius:12px;padding:3px 10px;white-space:nowrap}
.p-g{background:var(--gr2);color:var(--gr)}.p-o{background:var(--or2);color:var(--or)}.p-a{background:var(--acc2);color:var(--acc)}.p-x{background:var(--x2);color:var(--x)}
.muted{color:var(--muted)}.small{font-size:13px}
.up{color:var(--gr);font-weight:600}
select{font-size:15px;padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:#fff}
.kv{display:grid;grid-template-columns:auto 1fr;gap:6px 18px;font-size:14px}
.kv div:nth-child(odd){color:var(--muted)}
.variant{font-size:20px;font-weight:700;margin-bottom:4px}
.reason{font-size:14px;margin:6px 0 14px}
.legend{display:flex;gap:18px;flex-wrap:wrap;font-size:13px;color:var(--muted);margin-top:8px}
.legend span:before{content:"";display:inline-block;width:22px;height:0;border-top:3px solid currentColor;vertical-align:middle;margin-right:6px}
.q{font-style:italic;color:#2d3247;font-size:14.5px;line-height:1.5}
.num{display:inline-flex;width:28px;height:28px;border-radius:50%;background:var(--acc);color:#fff;font-weight:700;align-items:center;justify-content:center;margin-right:10px}
.links button{border:1px solid var(--line);background:#fff;border-radius:14px;padding:3px 10px;margin:3px 4px 0 0;font-size:12.5px;color:var(--acc);cursor:pointer}
.toggle{display:inline-flex;gap:4px;margin-left:12px}
.toggle button{border:1px solid var(--line);background:#fff;border-radius:8px;padding:5px 10px;font-size:13px;cursor:pointer}
.toggle button.on{background:var(--acc);color:#fff;border-color:var(--acc)}
svg text{font-family:inherit}
.tip{position:fixed;pointer-events:none;background:#161a2e;color:#fff;font-size:12.5px;padding:6px 9px;border-radius:6px;display:none;z-index:9}
ul.f{margin:0;padding-left:20px;line-height:1.7;font-size:15px}
</style></head><body>
<header>
  <h1>MILP cold start vs warm start</h1>
  <div class="sub" id="sub"></div>
  <nav id="nav"></nav>
</header>
<main id="main"></main>
<div class="tip" id="tip"></div>
<script>
const D=__DATA__;
const $=s=>document.querySelector(s);
const NS='http://www.w3.org/2000/svg';
function el(tag,attrs,parent,text){const e=document.createElementNS(NS,tag);for(const k in attrs)e.setAttribute(k,attrs[k]);if(text!=null)e.textContent=text;if(parent)parent.appendChild(e);return e}
const f4=v=>v==null||v===''?'–':(+v).toFixed(4);
const pct=v=>v==null||v===''?'–':((+v)*100).toFixed(2)+'%';
const secs=v=>{if(v==null||v==='')return'–';v=+v;return v<1?v.toFixed(2)+' s':v<120?v.toFixed(1)+' s':v<7200?(v/60).toFixed(1)+' min':(v/3600).toFixed(2)+' h'};
const int=v=>v==null||v===''?'–':Math.round(+v).toLocaleString('en-US');
const gb=v=>v==null||v===''?'–':((+v)/1024).toFixed(1)+' GB';

// ---------- data ----------
const ROWS=D.rows;const INST=[];const BY={};
for(const r of ROWS){if(!BY[r.instance]){BY[r.instance]={};INST.push(r.instance)}BY[r.instance][r.variant]=r}
const meta=Object.values(D.metadata)[0]||{};
$('#sub').textContent=`CLIPP competition model (OR-Tools CP-SAT ${meta.ortools||''}) · ${meta.time_limit_s/3600||1} h per run · ${meta.workers||4} workers · random seed ${meta.random_seed??0} · warm start = ${meta.seed_algorithm||'dp_simple'} as AddHint · ${ROWS.length} runs`;

function outcome(r){
  if(!r)return['not run','p-x'];
  const res=r.result;
  if(res==='optimal')return['optimal','p-g'];
  if(res==='no improvement (seed optimal)')return['DP proven optimal','p-g'];
  if(res==='feasible'){if(r.variant==='warm'&&+r.improvement_vs_seed>1e-9)return['improved DP','p-a'];return['feasible','p-a']}
  if(res==='no improvement')return['no improvement','p-o'];
  if(res==='model not built')return['model not built','p-x'];
  if(res==='no valid solution')return[r.cpsat_status==='UNKNOWN'?'no solution':'no valid solution','p-x'];
  return[res,'p-x'];
}
const pill=r=>{const [t,c]=outcome(r);return `<span class="pill ${c}">${t}</span>`};
const score=r=>r&&r.official_score!=null&&r.official_score!==''?+r.official_score:null;

// ---------- tabs ----------
const TABS=[['overview','Overview'],['instance','Instance'],['requirements','Requirements'],['findings','Findings']];
let current='overview',currentInst=INST[0];
$('#nav').innerHTML=TABS.map(([k,l])=>`<button data-k="${k}">${l}</button>`).join('');
$('#nav').onclick=e=>{if(e.target.dataset.k)show(e.target.dataset.k)};
function show(k,inst){current=k;if(inst)currentInst=inst;
  document.querySelectorAll('nav button').forEach(b=>b.className=b.dataset.k===k?'on':'');
  ({overview,instance,requirements,findings})[k]();window.scrollTo(0,0)}
window.openInst=i=>show('instance',i);

// ---------- overview ----------
function overview(){
  const warm=ROWS.filter(r=>r.variant==='warm'),cold=ROWS.filter(r=>r.variant==='cold');
  const improved=warm.filter(r=>+r.improvement_vs_seed>1e-9).length;
  const proven=warm.filter(r=>r.result==='no improvement (seed optimal)'||r.result==='optimal').length;
  const coldValid=cold.filter(r=>score(r)!=null).length;
  const notBuilt=ROWS.filter(r=>r.result==='model not built').length;
  let h=`<div class="grid g4">
   <div class="card kpi"><div class="v">${improved}</div><div class="l">instances where warm improves the DP</div></div>
   <div class="card kpi"><div class="v">${proven}</div><div class="l">instances where the model proves optimality</div></div>
   <div class="card kpi"><div class="v">${coldValid} / ${cold.length}</div><div class="l">cold runs with a valid solution in the time limit</div></div>
   <div class="card kpi"><div class="v">${notBuilt}</div><div class="l">models not built within the build limit</div></div></div>
  <div class="card"><h2>All instances <span class="muted small" style="font-weight:400">· click a row for details</span></h2><table>
  <tr><th>Instance</th><th>Variables</th><th>Cold</th><th>Cold score</th><th>Cold 1st valid</th><th>Warm</th><th>Warm score</th><th>Warm 1st valid</th><th>DP score</th><th>Warm vs DP</th><th>Warm gap</th></tr>`;
  for(const i of INST){const c=BY[i].cold,w=BY[i].warm,any=w||c;
    const imp=w&&w.improvement_vs_seed!=null&&w.improvement_vs_seed!==''?+w.improvement_vs_seed:null;
    h+=`<tr class="click" onclick="openInst('${i}')"><td><b>${i}</b></td><td class="n">${int(any.num_vars)}</td>
     <td>${pill(c)}</td><td class="n">${f4(score(c))}</td><td class="n">${c?secs(c.first_valid_s):''}</td>
     <td>${pill(w)}</td><td class="n">${f4(score(w))}</td><td class="n">${w?secs(w.first_valid_s):''}</td>
     <td class="n">${f4(w&&w.seed_score)}</td><td class="n ${imp>1e-9?'up':''}">${imp==null?'–':(imp>0?'+':'')+imp.toFixed(4)}</td><td class="n">${pct(w&&w.gap)}</td></tr>`}
  h+=`</table><div class="small muted" style="margin-top:10px">Score = official score of the best valid solution (lower bound). Gap = (UB − LB) / LB. In warm runs the DP solution is valid from the start; "1st valid" is the solver's own first valid solution.</div></div>`;
  $('#main').innerHTML=h;
}

// ---------- instance ----------
function instance(){
  const i=currentInst,c=BY[i].cold,w=BY[i].warm,any=w||c;
  let h=`<div class="card" style="display:flex;align-items:center;gap:16px;flex-wrap:wrap"><b style="font-size:20px">Instance</b>
   <select id="sel">${INST.map(x=>`<option ${x===i?'selected':''}>${x}</option>`).join('')}</select>
   <span class="muted">${int(any.num_vars)} variables${any.num_constraints?` · ${int(any.num_constraints)} constraints`:''} · ${any.result==='model not built'?`build stopped after ${secs(any.build_s)}`:`model built in ${secs(any.build_s)}`}</span></div>
   <div class="grid g2">${[c,w].map((r,k)=>runCard(r,k?'warm':'cold')).join('')}</div>
   ${any.result==='model not built'?'':`<div class="card"><h2 style="display:flex;align-items:center">Best score over time
    <span class="toggle"><button id="lg" class="on">log time</button><button id="ln">linear time</button></span></h2>
    <svg id="chart" width="100%" height="430"></svg>
    <div class="legend"><span style="color:#4f46e5">cold · best valid</span><span style="color:#d9620f">warm · best valid</span>
     <span style="color:#9aa0b4">upper bound (UB)</span><span style="color:#15925a">DP score (seed)</span><span style="color:#c5c8d6">candidate with subtours (not valid)</span></div></div>`}`;
  $('#main').innerHTML=h;
  $('#sel').onchange=e=>{currentInst=e.target.value;instance()};
  if(any.result==='model not built')return;
  let log=true;const draw=()=>chart(i,log);
  $('#lg').onclick=()=>{log=true;$('#lg').className='on';$('#ln').className='';draw()};
  $('#ln').onclick=()=>{log=false;$('#ln').className='on';$('#lg').className='';draw()};
  draw();
}
function runCard(r,v){
  const col=v==='cold'?'var(--acc)':'var(--or)';
  if(!r)return `<div class="card"><div class="variant" style="color:${col}">${v}</div><span class="pill p-x">not run</span><div class="reason muted">Cold start was run only on instance_A–E and Presheva.</div></div>`;
  const imp=r.improvement_vs_seed;
  if(r.result==='model not built')return `<div class="card"><div class="variant" style="color:${col}">${v}</div>${pill(r)}
   <div class="reason">${r.reason||''}</div><div class="kv"><div>Variables</div><div><b>${int(r.num_vars)}</b></div>
   <div>Build stopped after</div><div>${secs(r.build_s)}</div><div>Peak memory</div><div>${gb(r.peak_rss_mb)}</div></div>
   <div class="small muted" style="margin-top:12px">Reported as the professor asked: number of variables, time and reason.</div></div>`;
  return `<div class="card"><div class="variant" style="color:${col}">${v}</div>${pill(r)}
   <div class="reason">${r.reason||''}</div>
   <div class="kv">
    <div>Score (LB)</div><div><b>${f4(score(r)??r.lower_bound)}</b></div>
    <div>Upper bound</div><div>${f4(r.upper_bound)}</div>
    <div>Gap</div><div>${pct(r.gap)}</div>
    ${v==='warm'?`<div>DP score</div><div>${f4(r.seed_score)}</div><div>Improvement vs DP</div><div class="${+imp>1e-9?'up':''}">${imp==null||imp===''?'–':(+imp>0?'+':'')+(+imp).toFixed(4)}</div><div>DP valid for model</div><div>${r.hint_feasible===''||r.hint_feasible==null?'–':r.hint_feasible==='True'?'yes (fixed-hint check)':'no'}</div>`:''}
    <div>First valid solution</div><div>${secs(r.first_valid_s)}</div>
    <div>Best found at</div><div>${secs(r.best_s)}</div>
    <div>Solve time</div><div>${secs(r.solve_s)}</div>
    <div>Rounds / with cuts</div><div>${r.rounds??'–'} / ${r.cut_rounds??'–'}</div>
    <div>Peak memory</div><div>${gb(r.peak_rss_mb)}</div>
    <div>Validator</div><div>${r.valid==='True'?'valid':r.valid===''?'–':'invalid'}</div>
   </div></div>`;
}
function chart(i,log){
  const svg=$('#chart');svg.innerHTML='';const W=svg.clientWidth,H=430,L=60,R=20,T=16,B=46;
  const c=BY[i].cold,w=BY[i].warm;const tl=(c||w).time_limit_s||3600;
  const sers=[['cold',c,'#4f46e5'],['warm',w,'#d9620f']].filter(s=>s[1]);
  const pts=sers.flatMap(([v])=>D.progress[i+'_'+v]||[]);
  let lo=1,hi=0;for(const p of pts){for(const y of [p[3],p[4]])if(y!=null){lo=Math.min(lo,y);hi=Math.max(hi,y)}}
  if(w&&w.seed_score!=null)lo=Math.min(lo,+w.seed_score);
  if(!pts.length){el('text',{x:L,y:60,'font-size':15,fill:'#646b82'},svg,(w||c).result==='model not built'?'Model not built: no solver progress.':'No solver progress recorded (the DP was proven optimal immediately or no solution was found).');}
  lo=Math.max(0,Math.floor((lo-0.02)*20)/20);hi=Math.min(1.0,Math.ceil((Math.max(hi,lo+0.05)+0.005)*20)/20);
  const tmin=0.01,tmax=Math.max(tl,1);
  const X=t=>{t=Math.max(t,tmin);return log?L+(Math.log10(t)-Math.log10(tmin))/(Math.log10(tmax)-Math.log10(tmin))*(W-L-R):L+t/tmax*(W-L-R)};
  const Y=s=>T+(hi-Math.max(lo,Math.min(hi,s)))/(hi-lo)*(H-T-B);
  for(let s=lo;s<=hi+1e-9;s+=0.05){el('line',{x1:L,x2:W-R,y1:Y(s),y2:Y(s),stroke:'#eef0f5'},svg);el('text',{x:L-8,y:Y(s)+4,'text-anchor':'end','font-size':12,fill:'#646b82'},svg,s.toFixed(2))}
  const ticks=log?[[0.01,'0.01 s'],[0.1,'0.1 s'],[1,'1 s'],[10,'10 s'],[60,'1 min'],[600,'10 min'],[3600,'1 h']]:[[0,'0'],[600,'10 min'],[1200,'20 min'],[1800,'30 min'],[2400,'40 min'],[3000,'50 min'],[3600,'1 h']];
  for(const [t,l] of ticks){if(t>tmax)continue;el('line',{x1:X(t),x2:X(t),y1:T,y2:H-B,stroke:'#eef0f5'},svg);el('text',{x:X(t),y:H-B+18,'text-anchor':'middle','font-size':12,fill:'#646b82'},svg,l)}
  el('text',{x:L,y:H-6,'font-size':12,fill:'#9aa0b4'},svg,'solve time'+(log?' (log scale)':''));
  if(w&&w.seed_score!=null){const y=Y(+w.seed_score);el('line',{x1:L,x2:W-R,y1:y,y2:y,stroke:'#15925a','stroke-dasharray':'2 4','stroke-width':1.5},svg);el('text',{x:W-R-4,y:y-6,'text-anchor':'end','font-size':12,fill:'#15925a'},svg,'DP '+(+w.seed_score).toFixed(4))}
  const tip=$('#tip');
  for(const [v,r,col] of sers){const P=D.progress[i+'_'+v]||[];
    // candidates (not valid)
    for(const p of P){if(p[2]===0&&!p[5]&&p[3]!=null){const d=el('circle',{cx:X(p[0]),cy:Y(p[3]),r:2.2,fill:'#c5c8d6'},svg)}}
    // upper bound step
    let ub=null,d='';for(const p of P){if(p[4]!=null&&(ub==null||p[4]<ub-1e-12)){d+=(d?` H${X(p[0])} V${Y(p[4])}`:`M${X(p[0])} ${Y(p[4])}`);ub=p[4]}}
    if(d){d+=` H${X(tmax)}`;el('path',{d,fill:'none',stroke:col,'stroke-opacity':.35,'stroke-width':1.5,'stroke-dasharray':'6 5'},svg)}
    // best valid step (warm starts at the DP)
    let best=null;d='';const marks=[];
    if(v==='warm'&&r.seed_score!=null&&r.hint_feasible==='True'){best=+r.seed_score;d=`M${X(tmin)} ${Y(best)}`}
    for(const p of P){if(p[5]&&p[3]!=null&&(best==null||p[3]>best+1e-12)){d+=(d?` H${X(p[0])} V${Y(p[3])}`:`M${X(p[0])} ${Y(p[3])}`);best=p[3];marks.push(p)}}
    if(d){d+=` H${X(tmax)}`;el('path',{d,fill:'none',stroke:col,'stroke-width':3},svg)}
    for(const p of marks){const m=el('circle',{cx:X(p[0]),cy:Y(p[3]),r:4.5,fill:col,stroke:'#fff','stroke-width':1.5},svg);
      m.onmousemove=e=>{tip.style.display='block';tip.style.left=e.clientX+12+'px';tip.style.top=e.clientY+12+'px';tip.textContent=`${v} · ${p[3].toFixed(4)} at ${secs(p[0])} · round ${p[1]}`};m.onmouseleave=()=>tip.style.display='none'}
  }
}

// ---------- requirements ----------
function requirements(){
  const warm=ROWS.filter(r=>r.variant==='warm'),cold=ROWS.filter(r=>r.variant==='cold');
  const hintOk=warm.filter(r=>r.hint_feasible==='True').length,built=warm.filter(r=>r.result!=='model not built').length;
  const nb=ROWS.filter(r=>r.result==='model not built');
  const links=list=>`<div class="links">${list.map(r=>`<button onclick="openInst('${r.instance}')">${r.instance}</button>`).join('')}</div>`;
  const Q=[
   ['MILP model','Modeli ekzistues gjendet në repository-n e garës CLIPP … përdor OR-Tools CP-SAT … përdoreni këtë model si bazë. Për variantin me warm start, mund ta jepni zgjidhjen fillestare si hint (AddHint) në CP-SAT. Modelin tuaj në HiGHS mund ta mbani si krahasim shtesë, por jo si model kryesor.',
    `The competition model (milp-solver, commit cf6ed8a) is copied unchanged into <code>third_party/clipp_cpsat/</code>. Warm start = the DP solution as a complete <code>AddHint</code>. The earlier HiGHS model appears only as a comparison in <code>docs/cpsat-report.md</code>.`,[]],
   ['Warm start','Dynamic Programming është zgjedhje e mirë, meqë jep rezultat të përsëritshëm. Kontrolloni që zgjidhja e tij të jetë e vlefshme edhe për modelin.',
    `Seed = <code>data/output/dp_simple</code>. Checked by solving with every variable fixed to the hint plus a depot-connectivity check: <b>valid on ${hintOk} of ${built}</b> built models.`,warm.filter(r=>r.hint_feasible==='True')],
   ['Instances','Pa zgjidhje fillestare (cold start), mjafton A–E dhe Presheva. Me warm start, ekzekutimi duhet të bëhet për të gjitha instancat, me një kohë maksimale prej 1 ore për çdo instancë. Për instancat ku modeli nuk arrin as të ndërtohet ose të përmirësojë zgjidhjen fillestare, raportoni numrin e variablave, kohën dhe arsyen.',
    `Cold: ${cold.length} runs, warm: ${warm.length} runs. Not built: ${nb.map(r=>`${r.instance} (${int(r.num_vars)} variables, ${secs(r.build_s)})`).join(', ')||'none'}. No improvement: see the reason column of each run.`,nb.concat(warm.filter(r=>r.result.startsWith('no improvement')))],
   ['Time limit','Përdorni të njëjtin kufi kohor (1 orë), të njëjtin numër të workers dhe të njëjtin kompjuter për të dy variantet. Raportoni edhe kohën deri te zgjidhja e parë e vlefshme dhe sa e përmirëson modeli zgjidhjen fillestare.',
    `${(meta.time_limit_s||3600)/3600} h for all rounds together, ${meta.workers||4} workers, random seed ${meta.random_seed??0}, same computer (${meta.platform||''}). Time to first valid solution and improvement vs DP are columns in every run.`,ROWS.filter(r=>r.variant==='warm'&&+r.improvement_vs_seed>1e-9)],
  ];
  $('#main').innerHTML=`<div class="grid g2">${Q.map(([t,q,a,l],k)=>`<div class="card"><h2 style="display:flex;align-items:center"><span class="num">${k+1}</span>${t}</h2>
    <div class="q">“${q}”</div><div style="margin-top:12px;font-size:14.5px;line-height:1.55">${a}</div>${l.length?links(l):''}</div>`).join('')}</div>
    <div class="small muted">Quotes: Prof. Kadri's answer, 2026-11-25.</div>`;
}

// ---------- findings ----------
function findings(){
  const warm=ROWS.filter(r=>r.variant==='warm'),cold=ROWS.filter(r=>r.variant==='cold');
  const imp=warm.filter(r=>+r.improvement_vs_seed>1e-9).map(r=>`${r.instance} ${(+r.seed_score).toFixed(3)} → ${score(r).toFixed(3)}`);
  const prov=warm.filter(r=>r.result==='no improvement (seed optimal)').map(r=>r.instance);
  const cv=cold.filter(r=>score(r)!=null),cn=cold.filter(r=>score(r)==null);
  const nb=ROWS.filter(r=>r.result==='model not built').map(r=>r.instance);
  const fw=warm.filter(r=>r.first_valid_s!=null&&r.first_valid_s!=='').map(r=>+r.first_valid_s);
  let h=`<div class="card"><h2>Findings</h2><ul class="f">
   <li><b>Warm start always has a valid solution</b> (the DP) from the start; the solver's own first valid solution came after at most ${fw.length?secs(Math.max(...fw)):'–'}. Cold found a valid solution on ${cv.length} of ${cold.length} instances (${cv.map(r=>r.instance+' after '+secs(r.first_valid_s)).join(', ')}); none on ${cn.map(r=>r.instance).join(', ')}.</li>
   <li><b>The model improves the DP</b> on ${imp.length} instances: ${imp.join(', ')}.</li>
   <li><b>The DP is proven optimal</b> on ${prov.length} instances: ${prov.join(', ')}.</li>
   <li><b>The model does not scale:</b> ${nb.length} models not built within the build limit (${nb.join(', ')}); on larger synthetic instances a single round uses the whole hour.</li>
  </ul></div>
  <div class="card"><h2>Result by model size</h2><svg id="size" width="100%" height="250"></svg>
  <div class="legend"><span style="color:#15925a">valid result / DP optimal</span><span style="color:#4f46e5">improved / feasible</span><span style="color:#d9620f">no improvement</span><span style="color:#9aa0b4">no valid solution / not built</span></div></div>`;
  $('#main').innerHTML=h;
  const svg=$('#size'),W=svg.clientWidth,L=80,R=30;const X=v=>L+(Math.log10(v)-2)/(9-2)*(W-L-R);
  for(let e=2;e<=9;e++){el('line',{x1:X(10**e),x2:X(10**e),y1:20,y2:190,stroke:'#eef0f5'},svg);el('text',{x:X(10**e),y:212,'text-anchor':'middle','font-size':12,fill:'#646b82'},svg,['100','1 k','10 k','100 k','1 M','10 M','100 M','1 B'][e-2])}
  el('text',{x:L,y:240,'font-size':12,fill:'#9aa0b4'},svg,'model variables (log scale) · hover a point');
  const tip=$('#tip');
  [['cold',60],['warm',140]].forEach(([v,y])=>{el('text',{x:L-12,y:y+5,'text-anchor':'end','font-size':14,'font-weight':600,fill:v==='cold'?'#4f46e5':'#d9620f'},svg,v);
    ROWS.filter(r=>r.variant===v).forEach(r=>{const [t]=outcome(r);const col=t==='improved DP'||t==='feasible'?'#4f46e5':t==='DP proven optimal'||t==='optimal'?'#15925a':t==='no improvement'?'#d9620f':'#9aa0b4';
      const c=el('circle',{cx:X(+r.num_vars),cy:y,r:9,fill:col,'fill-opacity':.85,stroke:'#fff','stroke-width':2,style:'cursor:pointer'},svg);
      c.onmousemove=e=>{tip.style.display='block';tip.style.left=e.clientX+12+'px';tip.style.top=e.clientY+12+'px';tip.textContent=`${r.instance} · ${int(r.num_vars)} variables · ${t}`};c.onmouseleave=()=>tip.style.display='none';c.onclick=()=>openInst(r.instance)})});
}
show('overview');
</script></body></html>
"""

if __name__ == "__main__":
    raise SystemExit(main())
