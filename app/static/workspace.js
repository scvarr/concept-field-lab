'use strict';
// The existing constructor and SVG view operate on one canonical graph.
const $=s=>document.querySelector(s),h=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state,revision,token,busy=false,selected,graph,definitionUI,toastTimer,view='builder';
let ui={};try{ui=JSON.parse(localStorage.getItem('concept-field-permanent-ui')||'{}');}catch{}
function saveUI(){try{localStorage.setItem('concept-field-permanent-ui',JSON.stringify(ui));}catch{}}
const name=id=>state.designations.filter(d=>d.target===id).map(d=>d.text).join(' / ')||id;
const edgeName=e=>`${name(e.from)} → ${name(e.to)} · ${e.id}`;
const run=fn=>async(...args)=>{try{return await fn(...args);}catch(e){toast(e.message,true);}};
function toast(message,error=false){$('#toast').textContent=message;$('#toast').hidden=false;$('#toast').classList.toggle('error',error);clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,error?12000:4500);}
async function api(url,body){let response;try{response=await fetch(url,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Workspace-Token':token},body:JSON.stringify(body)});}catch{throw Error('Нет связи с локальным сервером; введённый текст остаётся в этой вкладке.');}const data=await response.json();if(!response.ok)throw Error(data.error||`HTTP ${response.status}`);return data;}
async function mutate(action,data){if(busy)throw Error('Дождитесь сохранения.');if(action!=='definition_save')definitionUI?.capture();busy=true;document.body.classList.add('busy');$('#save-status').textContent='Сохранение…';try{const result=await api('/api/action',{action,data,revision});({state,revision}=result);if(action==='import'||action==='restore')definitionUI.draft=null;render();return result.result;}finally{busy=false;document.body.classList.remove('busy');$('#save-status').textContent=`Сохранено · версия ${revision}`;}}
function dialog(title,content,submit,button='Сохранить'){
  $('#dialog-body').innerHTML=`<h2>${h(title)}</h2><form id="modal-form">${content}<div class="dialog-actions"><button id="modal-cancel" type="button">Отмена</button>${submit?`<button type="submit" class="primary">${h(button)}</button>`:'<button id="modal-close" type="button">Закрыть</button>'}</div></form>`;
  const dlg=$('#dialog');if(!dlg.open)dlg.showModal();$('#modal-cancel').onclick=()=>dlg.close();if($('#modal-close'))$('#modal-close').onclick=()=>dlg.close();$('#modal-form').onsubmit=run(async e=>{e.preventDefault();if(await submit(new FormData(e.target))!==false)dlg.close();});
}
async function download(url,filename){const r=await fetch(url);if(!r.ok)throw Error((await r.json()).error);const a=document.createElement('a');a.href=URL.createObjectURL(await r.blob());a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1500);}
function render(){if(view==='builder')definitionUI.render();else renderGraph();$('#global-count').textContent=`${state.nodes.length} концептов · ${state.edges.length} обычных рёбер · ${state.contextEdges.length} контекстных`;}
function showView(next){
  definitionUI.capture();view=next==='graph'?'graph':'builder';ui.workspaceView=view;saveUI();
  $('#builder').hidden=view!=='builder';$('#permanent-panel').hidden=view!=='graph';
  $('#go-builder').setAttribute('aria-pressed',String(view==='builder'));$('#go-graph').setAttribute('aria-pressed',String(view==='graph'));
  render();window.scrollTo(0,0);
}
function renderGraph(){
  if(!state.nodes.some(n=>n.id===selected))selected=state.nodes[0]?.id;
  const q=$('#graph-search').value.trim().toLocaleLowerCase('ru').replaceAll('ё','е');
  const rows=state.nodes.filter(n=>`${name(n.id)} ${n.id}`.toLocaleLowerCase('ru').replaceAll('ё','е').includes(q));
  $('#graph-results').innerHTML=q?`<small>${rows.length} совпадений · показано до 40</small>${rows.slice(0,40).map(n=>`<button data-global-node="${h(n.id)}">${h(name(n.id))}<code>${h(n.id)}</code><small>Позиция ${n.x}, ${n.y} · ${state.edges.filter(e=>e.from===n.id||e.to===n.id).length} связей</small></button>`).join('')}`:'';
  $('#graph-results').querySelectorAll('[data-global-node]').forEach(b=>b.onclick=()=>select(b.dataset.globalNode,true));
  let candidates=state.nodes;
  if($('#graph-mode').value==='neighbourhood'&&selected){const seen=new Set([selected]);let front=[selected];const depth=Math.max(0,Math.min(10,Number($('#graph-depth').value)||0));for(let i=0;i<depth;i++){const next=[];for(const e of state.edges)if(front.includes(e.from)||front.includes(e.to))for(const id of [e.from,e.to])if(!seen.has(id)){seen.add(id);next.push(id);}front=next;}candidates=state.nodes.filter(n=>seen.has(n.id));}
  let nodes=candidates.slice(0,1000);if(selected&&!nodes.some(n=>n.id===selected)){nodes=nodes.slice(0,999);nodes.push(state.nodes.find(n=>n.id===selected));}
  const ids=new Set(nodes.map(n=>n.id)),edges=state.edges.filter(e=>ids.has(e.from)&&ids.has(e.to));
  if(nodes.length){if(!graph){graph=new GraphView($('#permanent-graph'),{select:id=>select(id),editNode:id=>select(id,true),editEdge:id=>openEdge(id),canInteract:()=>!busy,savePosition:(id,p)=>mutate('position',{nodeId:id,...p}),error:e=>toast(e.message,true),changed:snapshot=>{ui.graph=snapshot;saveUI();}});if(ui.graph)graph.restore(ui.graph);}
    graph.update({id:'permanent',title:'Постоянный граф',rootId:selected},{nodes:nodes.map(n=>({...n,label:$('#graph-ids').checked?n.id:name(n.id)})),edges:edges.slice(0,3000).map(e=>({...e,displayTitle:edgeName(e)}))},selected);
  }else{$('#permanent-graph').textContent='Граф пуст. Выберите определение в конструкторе и подтвердите включение.';graph?.observer.disconnect();graph=null;}
  $('#graph-caption').textContent=`Показано ${nodes.length} из ${candidates.length} концептов, ${Math.min(edges.length,3000)} из ${edges.length} рёбер. Окружение показывает связность общего графа; допустимые маршруты задаются контекстом.`;
  inspector();
}
function select(id,center=false){selected=id;renderGraph();if(center)graph?.center(id);}
function inspector(){
  const host=$('#graph-inspector');if(!selected){host.innerHTML='';return;}
  const edges=state.edges.filter(e=>e.from===selected||e.to===selected),edgeIds=new Set(edges.map(e=>e.id)),contexts=state.contextEdges.filter(c=>edgeIds.has(c.from)||edgeIds.has(c.to));
  host.innerHTML=`<h3>${h(name(selected))}</h3><code>${h(selected)}</code><div class="actions"><button id="global-reuse">Использовать ID в черновике</button><button id="global-neighbours">Открыть окружение</button></div><h4>Обычные рёбра</h4>${edges.map(e=>`<button data-global-edge="${h(e.id)}">${h(edgeName(e))}</button>`).join('')}<h4>Контекст между рёбрами</h4>${contexts.map(c=>`<p><code>${h(c.from)} → ${h(c.to)}</code><small>${h(c.id)}</small></p>`).join('')||'<p>Контекстные пары отсутствуют.</p>'}`;
  $('#global-reuse').onclick=run(async()=>{showView('builder');await definitionUI.addExisting(selected);});$('#global-neighbours').onclick=()=>{$('#graph-mode').value='neighbourhood';renderGraph();graph?.fit();};host.querySelectorAll('[data-global-edge]').forEach(b=>b.onclick=()=>openEdge(b.dataset.globalEdge));
}
function openEdge(id){const edge=state.edges.find(e=>e.id===id);if(!edge)return;const contexts=state.contextEdges.filter(c=>c.from===id||c.to===id);dialog('Обычное ребро и контекст',`<p>${h(edgeName(edge))}</p><p>Направление ${h(edge.from)} → ${h(edge.to)}</p><h3>Контекстные связи</h3>${contexts.map(c=>`<p><code>${h(c.id)}</code><br>${h(c.from)} → ${h(c.to)}</p>`).join('')||'<p>Нет контекстных пар.</p>'}<details><summary>Происхождение</summary><pre>${h(JSON.stringify(edge.origins,null,2))}</pre></details><p>Корректировка маршрутов и контекстных пар — в конструкторе.</p>`);}
async function tools(){
  definitionUI.capture();if(definitionUI.changed)await definitionUI.save();const diagnostics=await api('/api/diagnostics'),rows=await api('/api/history');
  dialog('Данные, история и диагностика',`<button type="button" id="global-export">Экспорт графа и резервная копия JSON ↓</button><label>Импорт постоянного графа<input id="global-import-file" type="file" accept=".json,application/json"></label><button type="button" id="global-import-preview">Просмотреть импорт</button><p>Импорт сохраняет ID, добавляет отсутствующие объекты и отклоняет конфликты. Исторические документы открываются отдельно.</p>${diagnostics.legacyBackup?'<p id="transition-notice">Историческая база сохранена и проверена. Новый граф создан отдельно от прежних данных.</p><button type="button" id="legacy-download">Скачать проверенную старую SQLite ↓</button>':''}<details><summary>Диагностика и сохранность истории</summary><pre>${h(JSON.stringify(diagnostics,null,2))}</pre></details><details><summary>История постоянного графа (${rows.length})</summary>${rows.slice(0,80).map(r=>`<p>#${r.id} · ${h(r.time)} · ${h(r.action)}<br>${h(r.detail)} <button type="button" data-global-restore="${r.id}">Восстановить версию</button></p>`).join('')}</details>`);
  $('#global-export').onclick=run(async()=>{if(definitionUI.changed)await definitionUI.save();await download('/api/export','concept-field-permanent.json');});if($('#legacy-download'))$('#legacy-download').onclick=run(()=>download('/api/legacy-backup','concept-field-legacy-backup.sqlite3'));
  $('#global-import-preview').onclick=run(async()=>{const file=$('#global-import-file').files[0];if(!file)throw Error('Выберите JSON.');if(file.size>64*1024*1024)throw Error('Предел файла — 64 МиБ.');const document=JSON.parse(await file.text());const preview=await api('/api/import-preview',{document});dialog('Подтвердить импорт',`<pre>${h(JSON.stringify(preview,null,2))}</pre><label class="checkbox"><input name="confirmed" type="checkbox" required>Подтверждаю добавление объектов по исходным ID</label>`,async f=>{await mutate('import',{document,confirmed:f.has('confirmed')});},'Импортировать');});
  document.querySelectorAll('[data-global-restore]').forEach(b=>b.onclick=()=>{const targetRevision=Number(b.dataset.globalRestore);dialog('Восстановление всего постоянного графа',`<p>Текущие ${state.nodes.length} узлов / ${state.edges.length} рёбер будут заменены сохранённой версией #${targetRevision}. Более поздняя история сохранится.</p><label class="checkbox"><input name="confirmed" type="checkbox" required>Подтверждаю восстановление всего графа</label>`,f=>mutate('restore',{targetRevision,confirmed:f.has('confirmed')}),'Восстановить');});
}
definitionUI=new DefinitionBuilder({permanent:true,state:()=>state,study:()=>({...state,id:'permanent',title:'Постоянный граф'}),ui:()=>ui,saveUI,busy:()=>busy,api,mutate,toast,run,dialog,download});
$('#workspace-tools').onclick=run(tools);$('#graph-search').oninput=renderGraph;$('#graph-mode').onchange=renderGraph;$('#graph-depth').onchange=renderGraph;$('#graph-ids').onchange=renderGraph;$('#graph-fit').onclick=()=>graph?.fit();$('#go-builder').onclick=()=>showView('builder');$('#go-graph').onclick=()=>showView('graph');
window.addEventListener('beforeunload',e=>{if(definitionUI.changed){e.preventDefault();e.returnValue='';}});
run(async()=>{({state,revision,token}=await api('/api/state'));definitionUI.render();showView(ui.workspaceView);$('#save-status').textContent=`Сохранено · версия ${revision}`;})();
