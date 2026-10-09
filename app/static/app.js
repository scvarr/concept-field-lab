'use strict';
const $ = (s, parent = document) => parent.querySelector(s);
const $$ = (s, parent = document) => [...parent.querySelectorAll(s)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const statusNames = {pending:'Не решено',confirmed:'Подтверждено',rejected:'Отклонено'};
let state, revision, token, selectedStudy, selectedNode, view = 'editor', showArchive = false, dirty = false, busy = false;
let nodePage = 0, matchPage = 0, proposalPage = 0, historyPage = 0;
let leftStudy, rightStudy, leftNode, rightNode, pairQueries = {left:'',right:''};
let proposalRows = [], proposalSelection = new Set();
let toastTimer;
function toast(message, error=false) { $('#toast').textContent=message; $('#toast').classList.toggle('error',error); $('#toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('#toast').hidden=true,error?11000:4500); }
function run(fn) { return async (...args) => { try { await fn(...args); } catch(error) { toast(error.message,true); } }; }
async function api(path, body) {
  let response;
  try { response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Workspace-Token':token},body:JSON.stringify(body)}); }
  catch { throw new Error('Нет связи с локальным сервером. Запустите start.cmd и обновите страницу; текст в форме пока сохранён в этой вкладке.'); }
  const result=await response.json();
  if(!response.ok) throw new Error(result.error || `Ошибка ${response.status}`);
  return result;
}
async function mutate(action,data) {
  if(busy) throw new Error('Предыдущее сохранение ещё выполняется.');
  busy=true; document.body.classList.add('busy'); $('#save-status').textContent='Сохранение…';
  try {
    const result=await api('/api/action',{action,data,revision}); state=result.state; revision=result.revision; dirty=false;
    if(result.result?.studyId && ['create_study','merge'].includes(action)) { selectedStudy=result.result.studyId; selectedNode=result.result.nodeId; view='editor'; }
    if(action==='add_node') selectedNode=result.result.nodeId;
    if(action==='delete_node') selectedNode=study()?.rootId;
    if(action==='restore') { selectedStudy=state.studies.find(s=>!s.archived)?.id; selectedNode=study()?.rootId; }
    render();
    return result.result;
  } finally { busy=false; document.body.classList.remove('busy'); $('#save-status').textContent=`Сохранено · версия ${revision}`; }
}
function study(id=selectedStudy) { return state?.studies.find(s=>s.id===id); }
function node(s=study(),id=selectedNode) { return s?.nodes.find(n=>n.id===id); }
function canLeave() { if(!dirty) return true; if(confirm('В форме есть несохранённый текст. Перейти без сохранения?')) { dirty=false; return true; } return false; }
function pagination(host,page,total,size,setPage) {
  const pages=Math.max(1,Math.ceil(total/size)); page=Math.min(page,pages-1);
  host.innerHTML=`<div class="pagination"><button data-prev ${page===0?'disabled':''}>←</button><span>${total?`${page*size+1}–${Math.min(total,(page+1)*size)} из ${total}`:'Нет записей'}</span><button data-next ${page>=pages-1?'disabled':''}>→</button></div>`;
  $('[data-prev]',host).onclick=()=>setPage(page-1); $('[data-next]',host).onclick=()=>setPage(page+1);
  return page;
}
function dialog(title,content,submit,button='Сохранить') {
  $('#dialog-body').innerHTML=`<h2>${esc(title)}</h2><form id="modal-form">${content}<div class="dialog-actions"><button type="button" id="modal-cancel">Отмена</button>${submit?`<button class="primary" type="submit">${esc(button)}</button>`:'<button type="button" id="modal-close">Закрыть</button>'}</div></form>`;
  const dlg=$('#dialog'); if(!dlg.open) dlg.showModal();
  $('#modal-cancel').onclick=()=>dlg.close(); if($('#modal-close')) $('#modal-close').onclick=()=>dlg.close();
  $('#modal-form').onsubmit=run(async e=>{e.preventDefault();await submit(new FormData(e.target));dlg.close();});
}
function nodeFields(n={}) {
  return `<label>Название<input name="label" value="${esc(n.label)}" required maxlength="1000"></label><label>Тип / роль (свободное поле)<input name="kind" value="${esc(n.kind)}" list="kinds" maxlength="1000"></label><datalist id="kinds"><option>слово</option><option>значение</option><option>свойство</option><option>определение</option><option>написание</option><option>произношение</option><option>интерпретация</option></datalist><label>Содержание и пояснения<textarea name="notes" rows="4" maxlength="50000">${esc(n.notes)}</textarea></label><label>Альтернативные интерпретации<textarea name="alternatives" rows="2" maxlength="50000">${esc(n.alternatives)}</textarea></label><label>Источник / обоснование<textarea name="source" rows="2" maxlength="50000">${esc(n.source)}</textarea></label>`;
}
function render() {
  if(!study()) { selectedStudy=state.studies.find(s=>!s.archived)?.id; selectedNode=study()?.rootId; }
  if(study()&&!node()) selectedNode=study().rootId;
  $('#workspace-title').textContent=study()?.title || 'Ваши исследования';
  $('#revision').textContent=`v${revision}`;
  $('#candidate-count').textContent=state.proposals.filter(p=>p.status==='pending').length || '';
  renderStudies();
  $$('.view').forEach(e=>e.hidden=e.id!==view); $$('.tabs button').forEach(e=>e.classList.toggle('active',e.dataset.view===view));
  if(view==='editor') renderEditor();
  if(view==='compare') renderCompare();
  if(view==='exchange') run(renderProposals)();
  if(view==='history') run(renderHistory)();
}
function renderStudies() {
  const query=$('#study-search').value.toLowerCase();
  const rows=state.studies.filter(s=>s.archived===showArchive && `${s.title} ${s.description}`.toLowerCase().includes(query));
  $('#studies').innerHTML=rows.map(s=>`<button class="study-item ${s.id===selectedStudy?'active':''}" data-study="${esc(s.id)}"><strong>${esc(s.title)}</strong><small>${s.nodes.length} элементов · ${s.edges.length} отношений</small></button>`).join('')||'<p class="hint">Здесь пока нет исследований.</p>';
  $$('[data-study]').forEach(e=>e.onclick=()=>{if(!canLeave())return;selectedStudy=e.dataset.study;selectedNode=study().rootId;nodePage=0;$('#node-search').value='';view='editor';render();});
  $('#toggle-archive').textContent=showArchive?'Активные':'Архив';
}
function renderEditor() {
  const s=study();$('#empty').hidden=!!s;$('#editor-content').hidden=!s;if(!s)return;
  $('#study-meta').innerHTML=`<span class="tag">${s.archived?'Архив':'Независимое пространство'}</span> <span class="muted">${s.nodes.length} элементов · ${s.edges.length} отношений</span>${s.description?`<p class="hint">${esc(s.description)}</p>`:''}`;
  $('#archive-study').textContent=s.archived?'Вернуть из архива':'В архив';
  renderNodes();renderInspector();drawGraph($('#graph'),s,selectedNode,id=>selectNode(id),Number($('#graph-depth').value),true);
}
function renderNodes() {
  const s=study();if(!s)return;const query=$('#node-search').value.toLowerCase();
  const rows=s.nodes.filter(n=>`${n.label} ${n.kind} ${n.notes} ${n.alternatives} ${n.source} ${n.id}`.toLowerCase().includes(query));
  nodePage=pagination($('#node-pagination'),nodePage,rows.length,80,p=>{nodePage=p;renderNodes();});
  $('#node-count').textContent=s.nodes.length;
  $('#node-list').innerHTML=rows.slice(nodePage*80,(nodePage+1)*80).map(n=>`<button class="node-item ${n.id===selectedNode?'active':''}" data-node="${esc(n.id)}" title="${esc(n.label)}">${n.id===s.rootId?'◈ ':''}${esc(n.label)}<small>${esc(n.kind||'Без типа')}</small></button>`).join('');
  $$('[data-node]',$('#node-list')).forEach(e=>e.onclick=()=>selectNode(e.dataset.node));
}
function selectNode(id) { if(!canLeave())return;selectedNode=id;renderEditor(); }
function renderInspector() {
  const s=study(),n=node();if(!n)return;
  const labels=new Map(s.nodes.map(n=>[n.id,n.label]));
  const edges=s.edges.filter(e=>e.from===n.id||e.to===n.id);
  $('#inspector').innerHTML=`<h2>${esc(n.label)}</h2><div class="id-label">ID ${esc(n.id)}</div><form id="node-form">${nodeFields(n)}<button class="primary" type="submit">Сохранить элемент</button></form><div class="actions"><button id="expand-node">＋ Раскрыть узел</button><button id="link-node">↗ Связать с существующим</button><button id="inspector-copy">Копировать фрагмент</button></div><h3>Отношения · ${edges.length}</h3>${edges.map(e=>`<div class="relation-item"><span class="relation-title">${esc(labels.get(e.from))} → ${esc(labels.get(e.to))}</span><span>${esc(e.type)}</span>${e.notes?`<p class="hint">${esc(e.notes)}</p>`:''}<div><button data-go="${esc(e.from===n.id?e.to:e.from)}">Перейти</button><button data-edit-edge="${esc(e.id)}">Изменить</button><button data-delete-edge="${esc(e.id)}" class="danger">Удалить связь</button></div></div>`).join('')||'<p class="hint">Раскройте элемент или свяжите его с уже существующим.</p>'}<h3>Происхождение · ${n.origins.length}</h3>${n.origins.map(o=>`<details><summary>${esc(o.studyTitle||o.studyId)} · ${esc(o.snapshot.label||o.nodeId)}</summary><pre>${esc(JSON.stringify(o,null,2))}</pre></details>`).join('')||'<p class="hint">История создания и принятых импортов сохраняется в истории рабочего пространства и JSON экспорте.</p>'}${n.id!==s.rootId?'<button id="delete-node" class="danger wide">Удалить элемент и его связи</button>':''}`;
  $('#node-form').oninput=()=>{dirty=true;$('#save-status').textContent='Есть несохранённый текст';};
  $('#node-form').onsubmit=run(async e=>{e.preventDefault();await mutate('edit_node',{studyId:s.id,nodeId:n.id,...Object.fromEntries(new FormData(e.target))});toast('Элемент сохранён. Изменённые соответствия требуют повторной проверки.');});
  $('#expand-node').onclick=()=>addNode(n.id);$('#link-node').onclick=()=>edgeDialog();$('#inspector-copy').onclick=run(copyFragment);
  $$('[data-go]',$('#inspector')).forEach(e=>e.onclick=()=>selectNode(e.dataset.go));
  $$('[data-edit-edge]').forEach(e=>e.onclick=()=>edgeDialog(s.edges.find(x=>x.id===e.dataset.editEdge)));
  $$('[data-delete-edge]').forEach(e=>e.onclick=run(async()=>{if(!canLeave())return;if(confirm('Удалить только эту связь? Её прежняя версия останется в истории.'))await mutate('delete_edge',{studyId:s.id,edgeId:e.dataset.deleteEdge});}));
  if($('#delete-node')) $('#delete-node').onclick=run(async()=>{if(!canLeave())return;if(confirm(`Удалить «${n.label}», связанные отношения и соответствия? Прежняя версия останется в истории.`))await mutate('delete_node',{studyId:s.id,nodeId:n.id});});
}
function newStudy() {
  if(!canLeave())return;
  dialog('Новое независимое исследование','<p>Элементы другого исследования не будут использоваться автоматически, даже при совпадении названий.</p><label>Название / исходное слово<input name="title" required maxlength="1000" placeholder="Например, камень"></label><label>Описание<textarea name="description" rows="3"></textarea></label>',async f=>{await mutate('create_study',Object.fromEntries(f));toast('Создано независимое исследование.');},'Создать');
}
function addNode(parentId) {
  if(!study()||!canLeave())return;
  const s=study();dialog(parentId?`Раскрытие «${node(s,parentId).label}»`:'Отдельный элемент',`${nodeFields()}${parentId?'<label>Тип отношения<input name="relation" value="раскрывается через" required maxlength="1000"></label>':''}`,async f=>{await mutate('add_node',{studyId:s.id,parentId,...Object.fromEntries(f)});},'Добавить');
}
function edgeDialog(edge) {
  if(!canLeave())return;const s=study();
  // Searchable text inputs keep even thousands of endpoints usable.
  const options=s.nodes.map(n=>`<option value="${esc(n.id)}">${esc(n.label)} · ${esc(n.kind)}</option>`).join('');
  dialog(edge?'Изменить отношение':'Связать существующие элементы',`<p>Допустимы повторное использование, циклы и связь элемента с самим собой. Выбор по ID сохраняет различие одноимённых элементов.</p><datalist id="endpoints">${options}</datalist><label>Откуда (ID; поиск по названию)<input name="from" list="endpoints" value="${esc(edge?.from||selectedNode)}" required></label><label>Куда (ID; поиск по названию)<input name="to" list="endpoints" value="${esc(edge?.to||'')}" required></label><label>Тип отношения<input name="type" value="${esc(edge?.type||'связан с')}" required maxlength="1000"></label><label>Пояснение / интерпретация<textarea name="notes" rows="3">${esc(edge?.notes)}</textarea></label>`,async f=>{await mutate(edge?'edit_edge':'add_edge',{studyId:s.id,edgeId:edge?.id,...Object.fromEntries(f)});});
}
function graphSlice(s,focus,depth,limit=180) {
  const adj=new Map(s.nodes.map(n=>[n.id,[]]));
  for(const e of s.edges){adj.get(e.from)?.push(e.to);adj.get(e.to)?.push(e.from);}
  const distance=new Map([[focus,0]]),queue=[focus];let truncated=false;
  for(let i=0;i<queue.length;i++) {const id=queue[i],d=distance.get(id);if(d>=depth)continue;for(const next of adj.get(id)||[])if(!distance.has(next)){if(queue.length>=limit){truncated=true;continue;}distance.set(next,d+1);queue.push(next);}}
  return {nodes:s.nodes.filter(n=>distance.has(n.id)),edges:s.edges.filter(e=>distance.has(e.from)&&distance.has(e.to)),distance,truncated};
}
function drawGraph(host,s,focus,onSelect,depth=2,persist=false,markings=new Map()) {
  if(!s||!focus){host.innerHTML='<p class="hint">Выберите исследование и элемент.</p>';return;}
  const graph=graphSlice(s,focus,Math.max(0,Math.min(depth||0,100))),levels=new Map(),positions=new Map();
  for(const n of graph.nodes){const d=graph.distance.get(n.id);if(!levels.has(d))levels.set(d,[]);levels.get(d).push(n);}
  for(const [d,rows]of levels)rows.forEach((n,i)=>positions.set(n.id,{x:Number.isFinite(n.x)?n.x:d*240,y:Number.isFinite(n.y)?n.y:(i-(rows.length-1)/2)*90}));
  const marker=`arrow-${host.id}`;
  let box;
  function fit(){const pts=[...positions.values()];const minX=Math.min(...pts.map(p=>p.x))-110,minY=Math.min(...pts.map(p=>p.y))-65,maxX=Math.max(...pts.map(p=>p.x))+110,maxY=Math.max(...pts.map(p=>p.y))+65;box={x:minX,y:minY,w:Math.max(300,maxX-minX),h:Math.max(260,maxY-minY)};setBox();}
  function setBox(){const svg=$('svg',host);if(svg)svg.setAttribute('viewBox',`${box.x} ${box.y} ${box.w} ${box.h}`);}
  function line(e,i){const a=positions.get(e.from),b=positions.get(e.to);if(e.from===e.to)return {d:`M ${a.x+65} ${a.y-8} C ${a.x+155} ${a.y-105}, ${a.x-65} ${a.y-110}, ${a.x-35} ${a.y-30}`,x:a.x+40,y:a.y-70};const dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy)||1,offset=(i%3-1)*12;const mx=(a.x+b.x)/2-dy/len*offset,my=(a.y+b.y)/2+dx/len*offset;return {d:`M ${a.x+dx/len*62} ${a.y+dy/len*24} Q ${mx} ${my} ${b.x-dx/len*75} ${b.y-dy/len*29}`,x:mx,y:my-7};}
  function draw(){host.innerHTML=`<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Граф ${esc(s.title)}"><defs><marker id="${marker}" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8" fill="#92aaa0"/></marker></defs><g>${graph.edges.slice(0,500).map((e,i)=>{const p=line(e,i);return `<path class="edge" d="${p.d}" marker-end="url(#${marker})"/><text class="edge-label" x="${p.x}" y="${p.y}" text-anchor="middle">${esc(e.type.slice(0,32))}<title>${esc(e.type+' '+e.notes)}</title></text>`;}).join('')}${graph.nodes.map(n=>{const p=positions.get(n.id);return `<g class="node ${n.id===focus?'selected':''} ${markings.get(n.id)||''}" data-graph-node="${esc(n.id)}" transform="translate(${p.x},${p.y})"><rect x="-80" y="-28" width="160" height="56" rx="9"/><text text-anchor="middle" y="-2">${esc(n.label.length>21?n.label.slice(0,20)+'…':n.label)}</text><text class="kind-label" text-anchor="middle" y="15">${esc(n.kind.slice(0,26))}</text><title>${esc(n.label+'\n'+n.notes)}</title></g>`;}).join('')}</g></svg>`;if(box)setBox();bind();}
  let drag;
  function point(e){const svg=$('svg',host),p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;return p.matrixTransform(svg.getScreenCTM().inverse());}
  function bind(){const svg=$('svg',host);svg.onpointerdown=e=>{if(e.button!==0)return;if(persist&&dirty&&!canLeave())return;const target=e.target.closest('[data-graph-node]');const p=point(e);drag={id:target?.dataset.graphNode,start:p,last:p,clientX:e.clientX,clientY:e.clientY,moved:false};svg.setPointerCapture(e.pointerId);};svg.onpointermove=e=>{if(!drag)return;const p=point(e);if(Math.hypot(e.clientX-drag.clientX,e.clientY-drag.clientY)>4)drag.moved=true;if(!drag.moved)return;if(drag.id){const pos=positions.get(drag.id);pos.x+=p.x-drag.last.x;pos.y+=p.y-drag.last.y;drag.last=p;const element=$(`[data-graph-node="${CSS.escape(drag.id)}"]`,host);element.setAttribute('transform',`translate(${pos.x},${pos.y})`);}else{box.x-=p.x-drag.last.x;box.y-=p.y-drag.last.y;setBox();}};svg.onpointerup=run(async()=>{if(!drag)return;const d=drag;drag=null;if(d.id&&!d.moved){onSelect(d.id);return;}if(d.id&&d.moved){draw();if(persist){const pos=positions.get(d.id);await mutate('position',{studyId:s.id,nodeId:d.id,x:pos.x,y:pos.y});}}});svg.onpointercancel=()=>{drag=null;};svg.onwheel=e=>{e.preventDefault();const p=point(e),f=e.deltaY>0?1.13:.885;if(box.w*f<100||box.w*f>200000)return;box.x=p.x-(p.x-box.x)*f;box.y=p.y-(p.y-box.y)*f;box.w*=f;box.h*=f;setBox();};}
  draw();fit();host.fit=fit;
  if(persist) $('#graph-caption').textContent=`Показано ${graph.nodes.length} из ${s.nodes.length} элементов · ${Math.min(graph.edges.length,500)} связей${graph.truncated||graph.edges.length>500?' · Ограничено для читаемости; используйте поиск и переходы':''}. Колесо — масштаб, фон — перемещение, узел — выбор / перетаскивание.`;
}
function compareOptions() {
  const active=state.studies.filter(s=>!s.archived);
  if(!active.some(s=>s.id===leftStudy))leftStudy=active[0]?.id;
  if(!active.some(s=>s.id===rightStudy)||rightStudy===leftStudy)rightStudy=active.find(s=>s.id!==leftStudy)?.id;
  for(const [selector,id]of [['#compare-left',leftStudy],['#compare-right',rightStudy]]){$(selector).innerHTML='<option value="">Выберите исследование</option>'+active.map(s=>`<option value="${esc(s.id)}" ${s.id===id?'selected':''}>${esc(s.title)}</option>`).join('');}
}
function renderCompare() {
  compareOptions();const l=study(leftStudy),r=study(rightStudy);
  if(!l||!r||l.id===r.id){$('#pair-details').innerHTML='<p class="hint">Создайте и выберите два разных исследования.</p>';$('#matches').innerHTML='';$('#comparison-summary').textContent='';for(const id of ['#compare-left-list','#compare-right-list','#compare-left-graph','#compare-right-graph'])$(id).innerHTML='';return;}
  if(!node(l,leftNode))leftNode=l.rootId;if(!node(r,rightNode))rightNode=r.rootId;
  for(const [side,s,nid]of [['left',l,leftNode],['right',r,rightNode]]) {
    const host=$(`#compare-${side}-list`);
    host.innerHTML=`<input type="search" placeholder="Найти элемент в ${esc(s.title)}" value="${esc(pairQueries[side])}" aria-label="Найти элемент ${side}"><div class="pair-nodes"></div><small class="muted"></small>`;
    function fill(){const rows=s.nodes.filter(n=>`${n.label} ${n.kind} ${n.notes}`.toLowerCase().includes(pairQueries[side].toLowerCase()));$('.pair-nodes',host).innerHTML=rows.slice(0,40).map(n=>`<button class="${n.id===nid?'active':''}" data-pair-node="${esc(n.id)}">${esc(n.label)} <span class="muted">${esc(n.kind)}</span></button>`).join('');$('small',host).textContent=`${Math.min(40,rows.length)} из ${rows.length} · уточните поиск для остальных`;$$('[data-pair-node]',host).forEach(e=>e.onclick=()=>{if(side==='left')leftNode=e.dataset.pairNode;else rightNode=e.dataset.pairNode;renderCompare();});}
    $('input',host).oninput=e=>{pairQueries[side]=e.target.value;fill();};fill();
    const markings=new Map();
    for(const m of state.matches)if(new Set([m.leftStudy,m.rightStudy]).has(leftStudy)&&new Set([m.leftStudy,m.rightStudy]).has(rightStudy)){const id=m.leftStudy===s.id?m.leftNode:m.rightNode;const mark=m.status==='confirmed'?'common':m.status==='rejected'?'disputed':'';if(mark&&markings.get(id)!=='common')markings.set(id,mark);}
    drawGraph($(`#compare-${side}-graph`),s,nid,id=>{if(side==='left')leftNode=id;else rightNode=id;renderCompare();},2,false,markings);
  }
  renderPair();renderMatches();
}
function pairMatch(a=leftNode,b=rightNode){return state.matches.find(m=>(m.leftNode===a&&m.rightNode===b)||(m.leftNode===b&&m.rightNode===a));}
function renderPair(){const l=node(study(leftStudy),leftNode),r=node(study(rightStudy),rightNode),match=pairMatch();if(!l||!r)return;
  const keys=['label','kind','notes','alternatives','source'],names={label:'Название',kind:'Тип / роль',notes:'Содержание',alternatives:'Альтернативы',source:'Источник'};
  $('#pair-details').innerHTML=`<div class="pair-card"><div class="toolbar"><h3>Выбранная пара: ${esc(l.label)} ↔ ${esc(r.label)}</h3><span class="tag ${match?.status||'pending'}">${statusNames[match?.status||'pending']}</span></div><div class="pair-columns">${[l,r].map(n=>`<div><div class="id-label">${esc(n.id)}</div>${keys.map(k=>`<div class="${l[k]===r[k]?'field-same':'field-diff'}"><strong>${names[k]}</strong><br>${esc(n[k]||'—')}</div>`).join('')}</div>`).join('')}</div>${match?.reason?`<p class="hint">${esc(match.reason)}</p>`:''}<p class="hint">Зелёным показаны равные поля, жёлтым — различия. Равные поля сами по себе не доказывают тождество элементов.</p><div class="actions"><button id="confirm-pair" class="primary">Подтвердить соответствие</button><button id="reject-pair">Отклонить соответствие</button><button id="pending-pair">Оставить кандидатом</button></div></div>`;
  $('#confirm-pair').onclick=()=>decidePair('confirmed');$('#reject-pair').onclick=()=>decidePair('rejected');$('#pending-pair').onclick=()=>decidePair('pending');
}
function decidePair(status){const l=node(study(leftStudy),leftNode),r=node(study(rightStudy),rightNode);if(!l||!r)return;const match=pairMatch();
  dialog(`${statusNames[status]}: «${l.label}» ↔ «${r.label}»`,`<p>Решение не меняет исходные структуры. Объединение выполняется отдельным действием.</p><label>Обоснование / неоднозначность<textarea name="reason" rows="4">${esc(match?.reason||'')}</textarea></label>`,async f=>{await mutate('match',{leftStudy,leftNode,rightStudy,rightNode,status,reason:f.get('reason')});},statusNames[status]);
}
function compareRows(){const l=study(leftStudy),r=study(rightStudy);if(!l||!r)return[];const ln=new Map(l.nodes.map(n=>[n.id,n])),rn=new Map(r.nodes.map(n=>[n.id,n]));const rows=[],seen=new Set();
  for(const m of state.matches){if(new Set([m.leftStudy,m.rightStudy]).has(l.id)&&new Set([m.leftStudy,m.rightStudy]).has(r.id)){const a=m.leftStudy===l.id?m.leftNode:m.rightNode,b=m.leftStudy===l.id?m.rightNode:m.leftNode;rows.push({a,b,status:m.status,reason:m.reason,id:m.id});seen.add(`${a}/${b}`);}}
  const labels=new Map();for(const n of r.nodes){const label=n.label.toLocaleLowerCase('ru').trim();if(!labels.has(label))labels.set(label,[]);labels.get(label).push(n.id);}
  let omitted=0;for(const n of l.nodes)for(const b of labels.get(n.label.toLocaleLowerCase('ru').trim())||[]){if(!seen.has(`${n.id}/${b}`)){if(rows.length<10000)rows.push({a:n.id,b,status:'pending',reason:'Совпадает название; семантическое решение отсутствует.'});else omitted++;}}
  $('#comparison-summary').textContent=`Подтверждено: ${rows.filter(x=>x.status==='confirmed').length} · отклонено: ${rows.filter(x=>x.status==='rejected').length} · кандидатов: ${rows.filter(x=>x.status==='pending').length}. Без подтверждённого соответствия: ${l.nodes.filter(n=>!rows.some(x=>x.status==='confirmed'&&x.a===n.id)).length} слева, ${r.nodes.filter(n=>!rows.some(x=>x.status==='confirmed'&&x.b===n.id)).length} справа.${omitted?` Ещё ${omitted} сочетаний одноимённых узлов не выведено; выбирайте нужную пару вручную.`:''}`;
  return rows.map(row=>({...row,left:ln.get(row.a),right:rn.get(row.b)})).filter(x=>x.left&&x.right);
}
function renderMatches(){const query=$('#match-search').value.toLowerCase(),rows=compareRows().filter(x=>`${x.left.label} ${x.right.label} ${x.reason}`.toLowerCase().includes(query));
  const host=$('#matches');host.innerHTML='<div id="match-pagination"></div><table class="table"><thead><tr><th>Первый элемент</th><th>Второй элемент</th><th>Решение и основание</th><th></th></tr></thead><tbody></tbody></table>';
  matchPage=pagination($('#match-pagination'),matchPage,rows.length,60,p=>{matchPage=p;renderMatches();});
  $('tbody',host).innerHTML=rows.slice(matchPage*60,(matchPage+1)*60).map(x=>`<tr><td>${esc(x.left.label)}<br><span class="muted">${esc(x.left.kind)}</span></td><td>${esc(x.right.label)}<br><span class="muted">${esc(x.right.kind)}</span></td><td><span class="tag ${x.status}">${statusNames[x.status]}</span><div class="reason">${esc(x.reason)}</div></td><td><button data-select-pair="${esc(x.a)}" data-right="${esc(x.b)}">Просмотреть пару</button></td></tr>`).join('')||'<tr><td colspan="4">Кандидатов по названию нет. Можно выбрать любые два элемента в графах или поиске выше.</td></tr>';
  $$('[data-select-pair]').forEach(e=>e.onclick=()=>{leftNode=e.dataset.selectPair;rightNode=e.dataset.right;renderCompare();$('#pair-details').scrollIntoView({behavior:'smooth',block:'center'});});
}
function mergeDialog(){const l=study(leftStudy),r=study(rightStudy);if(!l||!r||l.id===r.id)return toast('Выберите два разных исследования.',true);const rows=compareRows().filter(x=>x.status==='confirmed');
  if(!rows.length)return toast('Сначала вручную подтвердите хотя бы одно соответствие.',true);
  dialog('Новое объединённое исследование',`<p>Выберите соответствия для отождествления. Все остальные элементы останутся раздельными. Несколько выбранных пар с общим элементом образуют одну группу транзитивно. Исходные графы, отношения и интерпретации сохраняются.</p><label>Название<input name="title" value="${esc(l.title+' + '+r.title)}" required maxlength="1000"></label>${rows.map(x=>`<label class="checkbox"><input type="checkbox" name="match" value="${esc(x.id)}">${esc(x.left.label)} ↔ ${esc(x.right.label)} · ${esc(x.reason)}</label>`).join('')}`,async f=>{await mutate('merge',{leftStudy,rightStudy,title:f.get('title'),matchIds:f.getAll('match')});toast('Создано объединение с происхождением каждого элемента.');},'Создать объединение');
}
function fragmentUrl(){if(!study()||!node())throw new Error('Сначала выберите исследование и узел.');const depth=$('#export-depth').value.trim();if(depth!=='all'&&!/^\d+$/.test(depth))throw new Error('Глубина должна быть целым числом ≥0 или all.');return `/api/graph-export?study=${encodeURIComponent(selectedStudy)}&node=${encodeURIComponent(selectedNode)}&depth=${depth}`;}
async function clipboard(text){try{await navigator.clipboard.writeText(text);toast('Скопировано в буфер обмена.');}catch{dialog('Текст для копирования',`<p>Выделите текст и нажмите Ctrl+C.</p><textarea rows="14" id="copy-fallback">${esc(text)}</textarea>`);$('#copy-fallback').select();}}
async function copyFragment(){await clipboard(JSON.stringify(await api(fragmentUrl()),null,2));}
async function download(url,filename){const data=await api(url);downloadText(JSON.stringify(data,null,2),filename,'application/json');}
function downloadText(text,filename,type){const url=URL.createObjectURL(new Blob([text],{type})),a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function promptChatGPT(){const doc=await api(fragmentUrl());const n=node();const template={format:'concept-field-graph',version:1,kind:'changes',changes:[{operation:'node',studyId:selectedStudy,base:null,value:{id:'NEW-UNIQUE-ID',label:'Новый элемент',kind:'свободный тип',notes:'Предлагаемое содержание',alternatives:'',source:'Предложение ChatGPT, требует проверки',origins:[]}},{operation:'edge',studyId:selectedStudy,base:null,value:{id:'NEW-EDGE-ID',from:n.id,to:'NEW-UNIQUE-ID',type:'раскрывается через',notes:'',origins:[]}}]};await clipboard(`Предложи ручное раскрытие выбранного элемента «${n.label}». Это неподтверждённые кандидаты; не отождествляй элементы по названию. Верни только JSON concept-field-graph v1 kind changes. Для новых объектов используй новые уникальные ID (UUID), base:null. Для изменения существующего объекта сохрани ID, все атрибуты и origins, укажи полный исходный объект в base. Не меняй существующие данные без обоснования. Не возвращай сам diff как изменения.\nПример формы ответа:\n${JSON.stringify(template,null,2)}\nИсходный фрагмент:\n${JSON.stringify(doc,null,2)}`);}
async function stageImport(){const text=$('#import-text').value;if(!text.trim())throw new Error('Выберите файл или вставьте JSON.');let document;try{document=JSON.parse(text);}catch{throw new Error('JSON не разбирается. Вставьте только JSON, без Markdown ограждений и пояснений.');}
  const preview=await api('/api/import-preview',{document});
  dialog('Проверка импорта',`<p>Объектов / изменений: ${preview.changes}. Возможных конфликтов: ${preview.conflicts}. Записей исходной истории: ${preview.history}.</p><p>Следующий шаг только добавит отдельные кандидаты в очередь. Вы сможете сравнить каждый кандидат с текущим объектом, принять выбранные или отклонить. ID сохраняются; повторные объекты не дублируются.</p>`,async()=>{const result=await mutate('import',{document});$('#import-text').value='';$('#import-file').value='';toast(`Добавлено кандидатов: ${result.added}; повторов: ${result.duplicates}; конфликтов: ${result.conflicts}.`);},'Добавить в очередь');
}
async function renderProposals(){proposalRows=await api('/api/proposals');const pendingIds=new Set(proposalRows.map(p=>p.id));proposalSelection=new Set([...proposalSelection].filter(i=>pendingIds.has(i)));const host=$('#proposals');host.innerHTML='<div id="proposal-pagination"></div><table class="table"><thead><tr><th></th><th>Операция и объект</th><th>Состояние</th><th>Просмотр</th></tr></thead><tbody></tbody></table>';
  proposalPage=pagination($('#proposal-pagination'),proposalPage,proposalRows.length,60,p=>{proposalPage=p;run(renderProposals)();});
  $('tbody',host).innerHTML=proposalRows.slice(proposalPage*60,(proposalPage+1)*60).map(p=>`<tr><td><input type="checkbox" aria-label="Выбрать кандидат ${esc(p.value.label||p.value.title||p.value.id)}" data-proposal="${esc(p.id)}" ${proposalSelection.has(p.id)?'checked':''}></td><td><strong>${esc(p.value.label||p.value.title||p.value.type||p.value.id)}</strong><br><span class="muted">${esc(p.operation)} · ${esc(p.value.id)}</span></td><td><span class="tag ${p.conflict?'rejected':'pending'}">${p.conflict?'Конфликт':'Ожидает просмотра'}</span></td><td><button data-inspect-proposal="${esc(p.id)}">Текущий / предложенный</button></td></tr>`).join('')||'<tr><td colspan="4">Очередь пуста. Импортируйте файл или предложения изменений.</td></tr>';
  function summary(){$('#proposal-summary').textContent=`В очереди ${proposalRows.length} · конфликтов ${proposalRows.filter(p=>p.conflict).length} · выбрано ${proposalSelection.size}. Зависимые объекты принимайте вместе: исследование, его элементы, отношения.`;}
  $$('[data-proposal]').forEach(e=>e.onchange=()=>{if(e.checked)proposalSelection.add(e.dataset.proposal);else proposalSelection.delete(e.dataset.proposal);summary();});
  $$('[data-inspect-proposal]').forEach(e=>e.onclick=()=>{const p=proposalRows.find(p=>p.id===e.dataset.inspectProposal);dialog('Просмотр кандидата',`<p>${p.idCollision?'Конфликт ID: объект с этим ID принадлежит другому исследованию или имеет другой тип. Отклоните кандидат и запросите новый уникальный ID.':p.conflict?'Есть конфликт с текущим объектом. Принятие заменит его.':'Исходный объект совпадает с base или отсутствует.'}</p><div class="pair-columns"><div><h3>Текущее значение</h3><pre>${esc(JSON.stringify(p.current,null,2))}</pre></div><div><h3>Предложенное значение</h3><pre>${esc(JSON.stringify(p.value,null,2))}</pre></div></div><details><summary>Полный кандидат и base</summary><pre>${esc(JSON.stringify(p,null,2))}</pre></details>`);});summary();
}
function reviewProposals(decision){if(!proposalSelection.size)return toast('Выберите кандидатов.',true);const selected=proposalRows.filter(p=>proposalSelection.has(p.id)),clashes=selected.filter(p=>p.conflict).length;
  dialog(decision==='accept'?'Принять выбранные предложения':'Отклонить выбранные предложения',`<p>Выбрано ${selected.length} кандидатов; конфликтов ${clashes}. ${decision==='accept'?'Применение атомарно: при ошибке не изменится ни один объект. Соответствия из внешнего JSON будут кандидатами и потребуют отдельного семантического решения.':'Исходные объекты останутся без изменений; решение сохранится в истории.'}</p>${decision==='accept'&&clashes?'<label class="checkbox"><input type="checkbox" name="allowConflicts" required>Я сравнил конфликтующие объекты и разрешаю заменить их предложенными значениями. Предыдущие значения сохраняются в истории.</label>':''}<label>Обоснование<textarea name="reason" rows="3"></textarea></label>`,async f=>{await mutate('review_proposals',{proposalIds:[...proposalSelection],decision,allowConflicts:f.has('allowConflicts'),reason:f.get('reason')});proposalSelection.clear();await renderProposals();toast('Решение сохранено.');},decision==='accept'?'Принять':'Отклонить');
}
async function renderHistory(){const rows=await api('/api/history'),host=$('#history-list');host.innerHTML='<div id="history-pagination"></div><div id="history-rows"></div>';historyPage=pagination($('#history-pagination'),historyPage,rows.length,60,p=>{historyPage=p;run(renderHistory)();});$('#history-rows').innerHTML=rows.slice(historyPage*60,(historyPage+1)*60).map(r=>`<div class="history-entry"><div><strong>#${r.id} · ${esc(r.detail)}</strong><small>${esc(new Date(r.time).toLocaleString('ru-RU'))} · ${esc(r.action)}</small></div><div class="actions"><button data-history-diff="${r.id}">Различия исследования ↓</button><button data-restore="${r.id}" ${r.id===revision?'disabled':''}>Восстановить</button></div></div>`).join('');
  $$('[data-restore]').forEach(e=>e.onclick=()=>{const targetRevision=Number(e.dataset.restore);dialog(`Восстановление версии #${targetRevision}`,'<p>Всё рабочее пространство вернётся к выбранной версии, включая исследования, соответствия и очередь кандидатов. Текущая и последующие версии останутся в истории; действие обратимо.</p>',async()=>{await mutate('restore',{targetRevision});toast('Версия восстановлена новой записью истории.');},'Восстановить');});
  $$('[data-history-diff]').forEach(e=>e.onclick=run(async()=>{if(!study())throw new Error('Выберите исследование.');await download(`/api/diff?left=${encodeURIComponent(selectedStudy)}&revision=${e.dataset.historyDiff}`,'concept-field-version-diff.json');}));
}
function help(){dialog('Как работать с полем знаний',`<p>1. Создайте независимое исследование слова. В форме элемента записывайте любые характеристики, определения, альтернативы и источники. Поля типов свободные.</p><p>2. «Раскрыть узел» добавляет новый элемент и отношение. «Связать с существующим» позволяет повторное использование, циклы и самоссылки. Поиск охватывает название и содержание всех элементов; граф показывает ограниченное окружение выбранного узла.</p><p>3. Во вкладке сопоставления выберите две структуры и любые два элемента. Просмотрите равные и различающиеся поля, подтвердите или отклоните соответствие с обоснованием. После изменения элемента решение требует повторной проверки.</p><p>4. «Создать объединение» создаёт третью структуру. Выберите только нужные подтверждённые пары; все исходные интерпретации и отношения остаются в происхождении новых объектов.</p><p>5. Экспорт исследования и фрагмента содержит JSON v1, ID и историю. Импорт не дублирует исходные ID: предложения попадают в очередь, конфликты показываются до применения. Экспорт различий доступен между исследованиями и в истории между версиями.</p><p>6. Сохраняйте форму кнопкой «Сохранить элемент». Другие действия сохраняются сразу в SQLite. Для резервной копии используйте экспорт всего рабочего пространства. При повторном запуске с тем же файлом базы работа продолжается.</p><p>Ctrl+K — поиск элементов, Esc — закрыть диалог. Колесо — масштаб графа, перетаскивание фона — движение, перетаскивание узла — его позиция.</p>`);}
$('#new-study').onclick=newStudy;$('#empty-create').onclick=newStudy;$('#help').onclick=help;
$('#study-search').oninput=renderStudies;$('#toggle-archive').onclick=()=>{showArchive=!showArchive;renderStudies();};
$$('.tabs button').forEach(e=>e.onclick=()=>{if(!canLeave())return;view=e.dataset.view;render();});
$('#node-search').oninput=()=>{nodePage=0;renderNodes();};$('#match-search').oninput=()=>{matchPage=0;renderMatches();};
$('#add-independent').onclick=()=>addNode();$('#graph-depth').onchange=()=>{if(canLeave())renderEditor();};$('#fit-graph').onclick=()=>$('#graph').fit?.();
$('#save-svg').onclick=run(async()=>{const svg=$('svg',$('#graph'));if(!svg)throw new Error('Нет графа для экспорта.');const clone=svg.cloneNode(true),style=document.createElementNS('http://www.w3.org/2000/svg','style');style.textContent='.node rect{fill:white;stroke:#b7cac2;stroke-width:1.5}.node.selected rect{fill:#286c61;stroke:#194f43}.node text{fill:#223d36;font:13px Segoe UI,Arial,sans-serif}.node.selected text{fill:white}.node .kind-label{font-size:9px}.edge{fill:none;stroke:#a1b4ac;stroke-width:1.4}.edge-label{font:10px Segoe UI,Arial,sans-serif;fill:#5a7065}';clone.prepend(style);clone.setAttribute('width','1200');clone.setAttribute('height','800');downloadText(new XMLSerializer().serializeToString(clone),'concept-field-view.svg','image/svg+xml');});
$('#edit-study').onclick=()=>{if(!study()||!canLeave())return;const s=study();dialog('Название и описание',`<label>Название<input name="title" value="${esc(s.title)}" required maxlength="1000"></label><label>Описание<textarea name="description" rows="4">${esc(s.description)}</textarea></label>`,f=>mutate('edit_study',{studyId:s.id,...Object.fromEntries(f)}));};
$('#archive-study').onclick=run(async()=>{if(!study()||!canLeave())return;const s=study();if(confirm(s.archived?'Вернуть исследование из архива?':'Архивировать исследование? Его данные и история сохранятся.'))await mutate('archive_study',{studyId:s.id,archived:!s.archived});});
$('#export-study').onclick=run(async()=>{if(!study())throw new Error('Выберите исследование.');await download(`/api/graph-export?study=${encodeURIComponent(selectedStudy)}`,'concept-field-study.json');});
$('#backup').onclick=run(()=>download('/api/export','concept-field-workspace.json'));
for(const side of ['left','right'])$(`#compare-${side}`).onchange=e=>{if(side==='left'){leftStudy=e.target.value;leftNode=null;}else{rightStudy=e.target.value;rightNode=null;}matchPage=0;renderCompare();};
$('#merge').onclick=mergeDialog;$('#export-diff').onclick=run(()=>download(`/api/diff?left=${encodeURIComponent(leftStudy||'')}&right=${encodeURIComponent(rightStudy||'')}`,'concept-field-comparison-diff.json'));
$('#copy-fragment').onclick=run(copyFragment);$('#download-fragment').onclick=run(()=>download(fragmentUrl(),'concept-field-fragment.json'));$('#chatgpt-prompt').onclick=run(promptChatGPT);
$('#import-file').onchange=run(async e=>{const file=e.target.files[0];if(!file)return;if(file.size>64*1024*1024)throw new Error('Предел файла — 64 МиБ. Экспортируйте исследование или фрагмент.');$('#import-text').value=await file.text();});
$('#stage-import').onclick=run(stageImport);$('#select-proposals').onclick=run(async()=>{if(proposalSelection.size===proposalRows.length)proposalSelection.clear();else proposalRows.forEach(p=>proposalSelection.add(p.id));await renderProposals();});
$('#accept-proposals').onclick=()=>reviewProposals('accept');$('#reject-proposals').onclick=()=>reviewProposals('reject');
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
document.addEventListener('keydown',e=>{if(e.ctrlKey&&e.key.toLowerCase()==='k'){e.preventDefault();if(!canLeave())return;view='editor';render();$('#node-search').focus();}});
run(async()=>{const initial=await api('/api/state');({state,revision,token}=initial);selectedStudy=state.studies.find(s=>!s.archived)?.id;selectedNode=study()?.rootId;render();$('#save-status').textContent=`Сохранено · версия ${revision}`;})().catch(()=>{});
