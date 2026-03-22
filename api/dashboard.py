"""
Dashboard visual para debug de jobs.
Rota: GET /dashboard
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>PEDRO - Dashboard</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Segoe UI',system-ui,sans-serif; background:#0f172a; color:#e2e8f0; padding:16px; font-size:14px; }
h1 { font-size:1.3em; color:#38bdf8; }
.sub { color:#64748b; font-size:.8em; margin-bottom:16px; }
.top { display:flex; gap:10px; margin-bottom:16px; flex-wrap:wrap; }
.sc { background:#1e293b; border-radius:6px; padding:10px 16px; min-width:100px; }
.sc .n { font-size:1.6em; font-weight:700; }
.sc .l { font-size:.7em; color:#94a3b8; text-transform:uppercase; }
.sc.g .n{color:#4ade80} .sc.r .n{color:#f87171} .sc.b .n{color:#38bdf8}
.sc.y .n{color:#facc15} .sc.p .n{color:#a78bfa}

.nj { background:#1e293b; border-radius:6px; padding:12px; margin-bottom:16px; }
.nj h3 { color:#38bdf8; font-size:.9em; margin-bottom:8px; }
.nj form { display:flex; gap:6px; flex-wrap:wrap; align-items:end; }
.nj label { font-size:.7em; color:#94a3b8; display:block; margin-bottom:1px; }
.nj input { background:#0f172a; border:1px solid #334155; color:#e2e8f0; padding:5px 8px; border-radius:3px; font-size:.82em; width:160px; }
.nj button { background:#2563eb; color:#fff; border:none; padding:7px 18px; border-radius:3px; cursor:pointer; font-weight:600; font-size:.85em; }
.nj button:hover { background:#1d4ed8; }

.jl { display:flex; flex-direction:column; gap:10px; }
.jc { background:#1e293b; border-radius:6px; padding:14px; border-left:4px solid #334155; }
.jc.concluido{border-left-color:#4ade80} .jc.processando{border-left-color:#facc15} .jc.na_fila{border-left-color:#94a3b8} .jc.cancelado{border-left-color:#f87171}

.jh { display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; }
.jid { font-family:monospace; font-size:1em; color:#38bdf8; }
.js { padding:2px 8px; border-radius:10px; font-size:.7em; font-weight:600; text-transform:uppercase; }
.js.concluido{background:#166534;color:#4ade80} .js.processando{background:#854d0e;color:#facc15} .js.na_fila{background:#334155;color:#94a3b8} .js.cancelado{background:#7f1d1d;color:#fca5a5}

.jm { font-size:.75em; color:#64748b; margin-bottom:6px; }
.jp { display:flex; gap:10px; font-size:.8em; margin-bottom:6px; }
.jp span { display:flex; align-items:center; gap:3px; }
.d { width:7px; height:7px; border-radius:50%; display:inline-block; }
.d.g{background:#4ade80} .d.r{background:#f87171} .d.y{background:#facc15} .d.gr{background:#64748b} .d.p{background:#a78bfa}

.pb { background:#334155; border-radius:3px; height:5px; margin-bottom:8px; overflow:hidden; }
.pbf { height:100%; border-radius:3px; transition:width .5s; }
.pbf.g{background:#4ade80} .pbf.y{background:#facc15}

.cg { display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:4px; }
.ci { display:flex; align-items:center; gap:6px; padding:5px 8px; border-radius:3px; font-size:.78em; background:#0f172a; }
.ci .cn { flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.ci .ct { font-size:.7em; color:#64748b; min-width:40px; text-align:right; }
.ci .cs { font-weight:600; font-size:.7em; padding:1px 5px; border-radius:2px; white-space:nowrap; }
.ci .cs.sucesso{background:#166534;color:#4ade80}
.ci .cs.cache{background:#1e1b4b;color:#a78bfa}
.ci .cs.erro,.ci .cs.falha{background:#7f1d1d;color:#fca5a5}
.ci .cs.executando{background:#854d0e;color:#fde68a}
.ci .cs.na_fila,.ci .cs.pendente{background:#334155;color:#94a3b8}
.ci .cs.timeout{background:#7f1d1d;color:#fca5a5}
.ci .cs.stuck{background:#92400e;color:#fb923c;animation:pulse 1s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
.ci a { color:#38bdf8; text-decoration:none; font-size:.75em; }
.ci a:hover { text-decoration:underline; }

.par { background:#0f172a; border-radius:4px; padding:8px; margin-top:6px; font-size:.78em; }
.par .sit { font-weight:700; }
.par .sit.regular{color:#4ade80} .par .sit.regular_com_ressalvas{color:#facc15}
.par .sit.incompleto{color:#fb923c} .par .sit.erro_total{color:#f87171}
.par .al { color:#f87171; font-weight:600; }
.par ul { margin:3px 0 0 14px; color:#94a3b8; font-size:.9em; }

.lgs { background:#1e293b; border-radius:6px; padding:12px; margin-top:16px; }
.lgs h3 { color:#38bdf8; font-size:.9em; margin-bottom:6px; }
.lgs .tabs { display:flex; gap:4px; margin-bottom:6px; }
.lgs .tab { background:#334155; color:#94a3b8; border:none; padding:3px 10px; border-radius:3px; cursor:pointer; font-size:.75em; }
.lgs .tab.active { background:#2563eb; color:#fff; }
.lgs pre { background:#0f172a; padding:8px; border-radius:3px; font-size:.72em; max-height:250px; overflow-y:auto; color:#94a3b8; white-space:pre-wrap; word-break:break-all; }
.bs { background:#334155; color:#94a3b8; border:none; padding:3px 8px; border-radius:3px; cursor:pointer; font-size:.72em; }
.bs:hover{background:#475569} .bd{background:#7f1d1d;color:#fca5a5}
</style>
</head>
<body>
<h1>PEDRO PROJECT — Dashboard</h1>
<p class="sub">Auto-refresh 5s | <span id="lu"></span></p>

<div class="top" id="top"></div>

<div class="nj">
  <h3>Novo Job</h3>
  <form id="njf" onsubmit="return cj(event)">
    <div><label>CPF</label><input name="cpf" placeholder="27290000625"></div>
    <div><label>CNPJ</label><input name="cnpj" placeholder="26546054000140"></div>
    <div><label>Nome</label><input name="nome" placeholder="FULANO DA SILVA"></div>
    <div><label>Nome Mae</label><input name="nm_mae" placeholder="MARIA DA SILVA"></div>
    <div><label>Nascimento</label><input name="dt_nascimento" placeholder="dd/mm/aaaa"></div>
    <button type="submit">Criar Job</button>
  </form>
</div>

<div class="jl" id="jl"></div>

<div class="lgs">
  <h3>Logs</h3>
  <div class="tabs">
    <button class="tab active" onclick="sl('pedro',this)">Tudo</button>
    <button class="tab" onclick="sl('jobs',this)">Jobs</button>
    <button class="tab" onclick="sl('certidoes',this)">Certidoes</button>
    <button class="tab" onclick="sl('erros',this)">Erros</button>
  </div>
  <pre id="lc">Carregando...</pre>
</div>

<script>
let curLog='pedro';

async function fj(u){const r=await fetch(u);return r.json()}

function ftime(iso){
  if(!iso)return'';
  try{return new Date(iso).toLocaleTimeString('pt-BR')}catch{return iso.slice(11,19)}
}

function elapsed(ini,fim){
  if(!ini)return'';
  try{
    const t0=new Date(ini), t1=fim?new Date(fim):new Date();
    const s=Math.round((t1-t0)/1000);
    if(s<60)return s+'s';
    return Math.floor(s/60)+'m'+('0'+(s%60)).slice(-2)+'s';
  }catch{return''}
}

function isStuck(ini,status){
  if(status!=='executando'||!ini)return false;
  try{return(new Date()-new Date(ini))/1000>120}catch{return false}
}

async function ld(){
  try{
    const[q,jd]=await Promise.all([fj('/api/v1/queue'),fj('/api/v1/jobs?limit=20')]);
    const jobs=jd.jobs||[];
    const proc=jobs.filter(j=>j.status==='processando').length;
    const done=jobs.filter(j=>j.status==='concluido').length;
    const tok=jobs.reduce((s,j)=>s+(j.sucesso||0),0);
    const tf=jobs.reduce((s,j)=>s+(j.falha||0),0);

    document.getElementById('top').innerHTML=`
      <div class="sc b"><div class="n">${q.fila}</div><div class="l">Fila</div></div>
      <div class="sc y"><div class="n">${proc}</div><div class="l">Processando</div></div>
      <div class="sc g"><div class="n">${done}</div><div class="l">Concluidos</div></div>
      <div class="sc g"><div class="n">${tok}</div><div class="l">OK</div></div>
      <div class="sc r"><div class="n">${tf}</div><div class="l">Falha</div></div>
      <div class="sc p"><div class="n">${q.total_workers}</div><div class="l">Workers</div></div>
    `;

    const details=await Promise.all(jobs.slice(0,15).map(j=>fj('/api/v1/job/'+j.job_id).catch(()=>j)));
    document.getElementById('jl').innerHTML=details.map(rj).join('');
    document.getElementById('lu').textContent=new Date().toLocaleTimeString();
  }catch(e){console.error(e)}
}

function rj(j){
  const cs=j.certidoes||{};
  const n=Object.keys(cs).length;
  const pct=n>0?Math.round((j.concluidas/n)*100):0;
  const bc=j.status==='concluido'?'g':'y';
  const jobElapsed=elapsed(j.iniciado_em,j.finalizado_em);

  let ch=Object.entries(cs).map(([id,c])=>{
    const res=c.resultado||{};
    const lnk=res.link_local||res.link||'';
    const lh=lnk?`<a href="${lnk}" target="_blank">PDF</a>`:'';
    const tc=res.tipo_certidao||'';
    const el=elapsed(c.inicio,c.fim);
    const stuck=isStuck(c.inicio,c.status);
    const stClass=stuck?'stuck':c.status;
    const stLabel=stuck?'TRAVADO':c.status;
    return`<div class="ci">
      <span class="d ${sd(c.status,stuck)}"></span>
      <span class="cn">${c.nome||id}${tc?' ('+tc+')':''}</span>
      <span class="ct">${el}</span>
      <span class="cs ${stClass}">${stLabel}</span>
      ${lh}
    </div>`;
  }).join('');

  let ph='';
  if(j.parecer){
    const p=j.parecer;
    const al=(p.alertas||[]).map(a=>`<div class="al">! ${a}</div>`).join('');
    const dt=(p.detalhes||[]).map(d=>`<li>${d}</li>`).join('');
    ph=`<div class="par">
      <span class="sit ${p.situacao}">${p.situacao.replace(/_/g,' ').toUpperCase()}</span>
      — ${p.resumo}${al}<ul>${dt}</ul>
    </div>`;
  }

  const criado=ftime(j.criado_em);
  const wk=j.worker_id?` | ${j.worker_id}`:'';

  return`<div class="jc ${j.status}">
    <div class="jh">
      <span>
        <span class="jid">${j.job_id}</span>
        <span class="jm">${j.tipo?.toUpperCase()} ${j.documento} | ${criado}${wk}${jobElapsed?' | '+jobElapsed:''}</span>
      </span>
      <span>
        <span class="js ${j.status}">${j.status}</span>
        <button class="bs bd" onclick="dj('${j.job_id}')" title="Deletar">X</button>
      </span>
    </div>
    <div class="jp">
      <span><span class="d g"></span>${j.sucesso||0} ok</span>
      <span><span class="d r"></span>${j.falha||0} falha</span>
      <span><span class="d gr"></span>${(j.total||0)-(j.concluidas||0)} restante</span>
      <span>${j.concluidas||0}/${j.total||0}</span>
    </div>
    <div class="pb"><div class="pbf ${bc}" style="width:${pct}%"></div></div>
    <div class="cg">${ch}</div>
    ${ph}
  </div>`;
}

function sd(s,stuck){
  if(stuck)return'y';
  if(s==='sucesso'||s==='cache')return'g';
  if(s==='erro'||s==='falha')return'r';
  if(s==='executando')return'y';
  return'gr';
}

async function cj(e){
  e.preventDefault();
  const f=e.target, b={};
  for(const[k,v]of new FormData(f)){if(v)b[k]=v}
  if(!b.cpf&&!b.cnpj){alert('CPF ou CNPJ');return false}
  const r=await fetch('/api/v1/job',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
  const d=await r.json();
  if(d.job_id){f.reset();ld()}else{alert(JSON.stringify(d))}
  return false;
}

async function dj(id){
  if(!confirm('Deletar '+id+'?'))return;
  await fetch('/api/v1/job/'+id,{method:'DELETE'});ld();
}

async function ll(){
  try{
    const r=await fj('/api/v1/logs/recent?arquivo='+curLog+'&linhas=100');
    const el=document.getElementById('lc');
    el.textContent=r.logs||'(vazio)';
    el.scrollTop=el.scrollHeight;
  }catch{document.getElementById('lc').textContent='Erro'}
}

function sl(a,btn){
  curLog=a;
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  btn.classList.add('active');
  ll();
}

ld();ll();
setInterval(ld,5000);
setInterval(ll,10000);
</script>
</body>
</html>"""


@router.get("/dashboard", response_class=HTMLResponse, tags=["Dashboard"])
async def dashboard():
    return DASHBOARD_HTML
