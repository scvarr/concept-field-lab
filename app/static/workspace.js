'use strict';
// The existing constructor and SVG view operate on one canonical graph.
const $=s=>document.querySelector(s),h=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state,revision,token,sceneView,busy=false,selected,selectedEdge,selectedContext,graph,toastTimer,view='thoughts',layoutUI;
const canvasMenu=new CanvasMenu();
let ui={};try{ui=JSON.parse(localStorage.getItem('concept-field-permanent-ui')||'{}');}catch{}
function saveUI(){try{localStorage.setItem('concept-field-permanent-ui',JSON.stringify(ui));}catch{}}
let captionState,captionIndex;function captions(){if(captionState!==state){captionState=state;captionIndex=AlphaCaptions.create(state);}return captionIndex;}const name=id=>state?.nodes.find(n=>n.id===id)?.operatorAlias||captions().display(id);
const edgeName=e=>`${e.role==='component'?'Обязательный компонент: ':''}${state.nodes.find(n=>n.id===e.from)?.operatorAlias||name(e.from)} → ${state.nodes.find(n=>n.id===e.to)?.operatorAlias||name(e.to)} · ${e.id}`;
const run=fn=>async(...args)=>{try{return await fn(...args);}catch(e){toast(e.message,true);}};
function toast(message,error=false){$('#toast').textContent=message;$('#toast').hidden=false;$('#toast').classList.toggle('error',error);clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,error?12000:4500);}
async function api(url,body){let response;try{response=await fetch(url,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Workspace-Token':token},body:JSON.stringify(body)});}catch{throw Error('Нет связи с локальным сервером; введённый текст остаётся в этой вкладке.');}const data=await response.json();if(!response.ok)throw Error(data.error||`HTTP ${response.status}`);return data;}
async function mutate(action,data){if(busy)throw Error('Дождитесь сохранения.');busy=true;document.body.classList.add('busy');$('#save-status').textContent='Сохранение…';try{const result=await api('/api/action',{action,data,revision});({state,revision,sceneView}=result);if(action==='import'||action==='restore'||action==='manage_apply'){ui.graphHidden=false;ui.graph=null;ThoughtLab.discard();}render();return result.result;}finally{busy=false;document.body.classList.remove('busy');$('#save-status').textContent=`Сохранено · версия ${revision}`;}}
function closeDialog(){$('#dialog').close();canvasMenu.close(false);}
function dialog(title,content,submit,button='Сохранить'){
  canvasMenu.close(false);
  $('#dialog-body').innerHTML=`<h2>${h(title)}</h2><form id="modal-form">${content}<div class="dialog-actions"><button id="modal-cancel" type="button">Отмена</button>${submit?`<button type="submit" class="primary">${h(button)}</button>`:'<button id="modal-close" type="button">Закрыть</button>'}</div></form>`;
  const dlg=$('#dialog');if(!dlg.open)dlg.showModal();dlg.scrollTop=0;$('#modal-cancel').onclick=closeDialog;if($('#modal-close'))$('#modal-close').onclick=closeDialog;$('#modal-form').onsubmit=run(async e=>{e.preventDefault();if(submit&&await submit(new FormData(e.target))!==false)dlg.close();});
}
async function download(url,filename){const r=await fetch(url);if(!r.ok)throw Error((await r.json()).error);const a=document.createElement('a');a.href=URL.createObjectURL(await r.blob());a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1500);}
function render(){if(view==='thoughts')ThoughtLab.render();else if(view==='scenes')SceneLab.render();else renderGraph();$('#global-count').textContent=`${state.nodes.length} концептов · ${state.edges.filter(e=>e.role==='relation').length} отношений · ${state.edges.filter(e=>e.role==='component').length} компонентов · ${state.contextEdges.length} контекстных`;}
function showView(next){
  if(view==='thoughts'&&next!=='thoughts'){ThoughtLab.save().catch(e=>toast(e.message,true));}
  if(next!=='graph'&&(layoutUI?.preview||layoutUI?.worker))layoutUI.cancel();canvasMenu.close(false);view=['graph','scenes','thoughts'].includes(next)?next:'thoughts';ui.workspaceView=view;saveUI();
  $('#thoughts-panel').hidden=view!=='thoughts';$('#go-thoughts').setAttribute('aria-pressed',String(view==='thoughts'));
  $('#scenes-panel').hidden=view!=='scenes';$('#go-scenes').setAttribute('aria-pressed',String(view==='scenes'));$('#permanent-panel').hidden=view!=='graph';
  $('#go-graph').setAttribute('aria-pressed',String(view==='graph'));
  render();window.scrollTo(0,0);
}
function renderGraph(){
  if(ui.graphHidden){graph?.observer.disconnect();graph=null;$('#permanent-graph').textContent='Полотно скрыто. Сохранённые данные не удалены; нажмите «Показать сохранённый граф».';return;}
  if(!state.nodes.some(n=>n.id===selected))selected=state.nodes[0]?.id;
  if(!state.edges.some(e=>e.id===selectedEdge))selectedEdge=null;
  if(!state.contextEdges.some(c=>c.id===selectedContext))selectedContext=null;
  const q=$('#graph-search').value.trim().toLocaleLowerCase('ru').replaceAll('ё','е');
  const rows=state.nodes.filter(n=>captions().matches(n.id,q)||n.id.includes(q)||(n.operatorAlias||'').toLocaleLowerCase('ru').includes(q)).sort((a,b)=>captions().rank(a.id,q)-captions().rank(b.id,q)||name(a.id).localeCompare(name(b.id),'ru')||a.id.localeCompare(b.id));const matches=new Set(q?rows.map(n=>n.id):[]);
  $('#graph-results').innerHTML=q?`<small>${rows.length} совпадений · показано до 40</small>${rows.slice(0,40).map(n=>`<button data-global-node="${h(n.id)}">${h(name(n.id))}<code>${h(n.id)}</code><small>Позиция ${n.x}, ${n.y} · ${state.edges.filter(e=>e.from===n.id||e.to===n.id).length} связей</small></button>`).join('')}`:'';
  $('#graph-results').querySelectorAll('[data-global-node]').forEach(b=>b.onclick=()=>select(b.dataset.globalNode,true));
  let candidates=state.nodes;
  if($('#graph-mode').value==='neighbourhood'&&selected){const seen=new Set([selected]);let front=[selected];const depth=Math.max(0,Math.min(10,Number($('#graph-depth').value)||0));for(let i=0;i<depth;i++){const next=[];for(const e of state.edges)if(front.includes(e.from)||front.includes(e.to))for(const id of [e.from,e.to])if(!seen.has(id)){seen.add(id);next.push(id);}front=next;}candidates=state.nodes.filter(n=>seen.has(n.id));}
  let nodes=(q?[...candidates].sort((a,b)=>Number(matches.has(b.id))-Number(matches.has(a.id))):candidates).slice(0,2000);if(selected&&!nodes.some(n=>n.id===selected)){nodes=nodes.slice(0,1999);nodes.push(state.nodes.find(n=>n.id===selected));}
  const metric=OverviewGeometry.metrics(state),ids=new Set(nodes.map(n=>n.id)),edges=state.edges.filter(e=>ids.has(e.from)&&ids.has(e.to));
  if(nodes.length){if(!graph){graph=new GraphView($('#permanent-graph'),{createContext:run(prepareMarkerContext),circular:true,edgeLimit:6000,contextBudgetMs:120,minScale:.002,labelMode:()=>ui.graphLabelMode||'auto',select:id=>select(id),editNode:id=>openNode(id),editEdge:id=>openEdge(id),editContext:id=>openContext(id),contextMenu:(kind,id,e)=>globalMenu(kind,id,e),canInteract:id=>!busy&&(!id||!layoutUI?.preview),savePosition:(id,p)=>mutate('position',{nodeId:id,...p}),error:e=>toast(e.message,true),changed:snapshot=>{ui.graph=snapshot;saveUI();}});if(ui.graph)graph.restore(ui.graph);}
    graph.update({id:'permanent',title:'Постоянный граф',rootId:selected},{nodes:nodes.map(n=>({...n,...metric.get(n.id),...layoutUI?.preview?.positions[n.id],label:$('#graph-ids').checked?n.id:name(n.id),displayTitle:captions().label(n.id)+'\nID: '+n.id,badge:n.operatorAlias?'рабочий alias':n.structure==='alpha'?(captions().anonymous(n.id)?'α · #'+captions().token(n.id):'α · обязательный состав'):n.kind})),edges:edges.slice(0,6000).map(e=>({...e,displayTitle:edgeName(e)})),contextEdges:state.contextEdges},selected,new Map(nodes.map(n=>[n.id,q?(matches.has(n.id)?'search-match':'search-dim'):''])));
  }else{$('#permanent-graph').textContent='Постоянный граф пуст. Создайте концепт через «Редактировать граф» или из текущего разбора.';graph?.observer.disconnect();graph=null;}
  const overlaps=OverviewGeometry.overlaps(nodes.map(n=>({...n,...metric.get(n.id),...layoutUI?.preview?.positions[n.id]}))),overlap=overlaps.length;
  $('#graph-caption').textContent=`Показано ${nodes.length} из ${candidates.length} концептов, ${Math.min(edges.length,6000)} из ${edges.length} рёбер. Цвет: concept — синий, α — фиолетовый. Поиск — подсветка интерфейса.${overlap?` Наложения узлов: ${overlaps.truncated?'≥':''}${overlap}; используйте раскладку.`:''}`;
}
function select(id,center=false){selected=id;selectedEdge=null;selectedContext=null;renderGraph();if(center)graph?.center(id);}
async function reuseNode(id){closeDialog();showView('thoughts');return ThoughtLab.useConcept(id);}
function neighbours(id){closeDialog();selected=id;selectedEdge=null;selectedContext=null;$('#graph-mode').value='neighbourhood';renderGraph();graph?.fit();}
function openNode(id){return inspectNode(id);}
function globalMenu(kind,id,event){
  if(busy)return;
const call=(key,label,fn)=>({id:key,label,run:run(fn)});const actions=kind==='node'?[call('edit-node','Свойства и обозначения…',()=>inspectNode(id)),call('edit','Изменить постоянный концепт…',()=>graphEditor.node(id)),call('reuse','Использовать концепт в разборе…',()=>reuseNode(id)),call('delete','Удалить с preview зависимостей…',()=>Management.remove(['node:'+id]))]:kind==='edge'||kind==='context'?[call('edit','Изменить связь…',()=>graphEditor.edge(id,kind==='context')),call('delete','Удалить с preview зависимостей…',()=>Management.remove([(kind==='context'?'context:':'edge:')+id]))]:[call('new','Создать концепт…',()=>graphEditor.node()),call('fit','Вписать граф',()=>graph?.fit()),call('manage','Выбрать группу объектов…',()=>Management.home(true))];canvasMenu.open(event,'Постоянный уровень',actions);
}
function openContexts(){
  dialog('Контекстные связи постоянного графа',`<p>Все пары доступны независимо от фильтра и геометрии полотна. Поиск: контекстный ID или ID обычного ребра.</p><input id="global-context-search" type="search" aria-label="Поиск контекстных связей" placeholder="ID контекста или обычного ребра"><div id="global-context-results"></div>`);
  const draw=()=>{const q=$('#global-context-search').value.trim().toLowerCase(),rows=state.contextEdges.filter(c=>`${c.id} ${c.from} ${c.to}`.toLowerCase().includes(q));$('#global-context-results').innerHTML=`<p>${rows.length} пар · показано до 800</p>${rows.slice(0,800).map(c=>`<button type="button" class="object-choice" data-global-context="${h(c.id)}">${h(edgeName(state.edges.find(e=>e.id===c.from)))}<br>→ ${h(edgeName(state.edges.find(e=>e.id===c.to)))}<code>${h(c.id)}</code></button>`).join('')}`;$('#global-context-results').querySelectorAll('[data-global-context]').forEach(b=>b.onclick=()=>openContext(b.dataset.globalContext));};$('#global-context-search').oninput=draw;draw();
}
async function prepareMarkerContext(from,to){await graphEditor.edge(null,true);$('#modal-form [name=from]').value=from;$('#modal-form [name=to]').value=to;}
function openEdge(id){return graphEditor.edge(id);}
function openContext(id){return graphEditor.edge(id,true);}
async function tools(){
  await ThoughtLab.save();
  const rows=await api('/api/history');
  dialog('Данные, история и диагностика',`<button type="button" id="global-export">Экспорт графа и резервная копия JSON ↓</button><label>Импорт постоянного графа<input id="global-import-file" type="file" accept=".json,application/json"></label><button type="button" id="global-import-preview">Просмотреть импорт</button><p>Импорт сохраняет ID, добавляет отсутствующие объекты и отклоняет конфликты. Поддерживается только актуальный формат.</p><details><summary>История каркаса и сцен (${rows.length})</summary>${rows.slice(0,80).map(r=>`<p>#${r.id} · ${h(r.time)} · ${h(r.action)}<br>${h(r.detail)} <button type="button" data-global-restore="${r.id}">Восстановить версию</button></p>`).join('')}</details>`);
  $('#global-export').onclick=run(async()=>{await download('/api/export','concept-field-permanent.json');});
  $('#global-import-preview').onclick=run(async()=>{const file=$('#global-import-file').files[0];if(!file)throw Error('Выберите JSON.');if(file.size>64*1024*1024)throw Error('Предел файла — 64 МиБ.');const document=JSON.parse(await file.text());const preview=await api('/api/import-preview',{document});dialog('Подтвердить импорт',`<pre>${h(JSON.stringify(preview,null,2))}</pre><label class="checkbox"><input name="confirmed" type="checkbox" required>Подтверждаю добавление объектов по исходным ID</label>`,async f=>{await mutate('import',{document,confirmed:f.has('confirmed')});},'Импортировать');});
  document.querySelectorAll('[data-global-restore]').forEach(b=>b.onclick=()=>{const targetRevision=Number(b.dataset.globalRestore);dialog('Восстановление каркаса, сцен и рабочих областей',`<p>Текущие ${state.nodes.length} узлов / ${state.edges.length} рёбер и все сцены/рабочие области будут заменены сохранённой версией #${targetRevision}. Более поздняя история сохранится.</p><label class="checkbox"><input name="confirmed" type="checkbox" required>Подтверждаю восстановление всего состояния</label>`,f=>mutate('restore',{targetRevision,confirmed:f.has('confirmed')}),'Восстановить');});
}
function neighbourhoodIds(){const seen=new Set([selected]),adj=new Map(state.nodes.map(n=>[n.id,[]]));for(const e of state.edges){adj.get(e.from).push(e.to);adj.get(e.to).push(e.from);}let front=[selected];for(let i=0;i<Number($('#graph-depth').value);i++){const next=[];for(const id of front)for(const n of adj.get(id)||[])if(!seen.has(n)){seen.add(n);next.push(n);}front=next;}return [...seen];}
layoutUI=new PermanentLayout({state:()=>state,revision:()=>revision,selected:()=>selected,neighbourhood:neighbourhoodIds,render:renderGraph,graph:()=>graph,dialog,toast,mutate});
$('#graph-label-mode').value=ui.graphLabelMode||'auto';$('#graph-label-mode').onchange=()=>{ui.graphLabelMode=$('#graph-label-mode').value;saveUI();graph?.paintLabels();};
$('#graph-layout').onclick=run(()=>layoutUI.open());$('#graph-layout-apply').onclick=run(()=>layoutUI.apply());$('#graph-layout-cancel').onclick=()=>layoutUI.cancel();$('#graph-layout-undo').onclick=run(()=>layoutUI.undo());
$('#graph-actions').onclick=e=>globalMenu(selectedContext?'context':selectedEdge?'edge':selected?'node':'canvas',selectedContext||selectedEdge||selected,e);$('#permanent-graph').oncontextmenu=e=>{if(e.target.closest('svg'))return;e.preventDefault();globalMenu('canvas',null,e);};$('#workspace-tools').onclick=run(tools);$('#graph-search').oninput=renderGraph;$('#graph-mode').onchange=renderGraph;$('#graph-depth').onchange=renderGraph;$('#graph-ids').onchange=renderGraph;$('#graph-fit').onclick=()=>graph?.fit();$('#go-thoughts').onclick=()=>showView('thoughts');$('#go-scenes').onclick=()=>showView('scenes');$('#go-graph').onclick=()=>showView('graph');
window.addEventListener('beforeunload',e=>{if(ThoughtLab.hasUnsaved()){e.preventDefault();e.returnValue='';}});
run(async()=>{({state,revision,token,sceneView}=await api('/api/state'));showView(ui.workspaceView||'thoughts');$('#save-status').textContent=`Сохранено · версия ${revision}`;})();

$('#workspace-manage').onclick=run(()=>Management.home());$('#graph-remove').onclick=run(()=>Management.home(true));$('#graph-clear-view').onclick=()=>{ui.graphHidden=true;saveUI();renderGraph();};$('#graph-show-all').onclick=()=>{ui.graphHidden=false;ui.graph=null;$('#graph-search').value='';$('#graph-mode').value='all';$('#graph-depth').value='1';layoutUI.cancel();saveUI();renderGraph();graph?.fit();};

function inspectNode(id){
 const n=state.nodes.find(n=>n.id===id);if(!n)throw Error('Концепт отсутствует.');
 dialog('Постоянный концепт: свойства, обозначения и происхождение',`<p><code>${h(id)}</code></p><p>Рабочий alias: ${h(n.operatorAlias||'не задан')}</p><button type="button" id="concept-edit">Изменить концепт…</button><button type="button" id="concept-reuse">Использовать в разборе…</button><label>Новое внешнее обозначение<input name="text" required></label><p>Словарное обозначение не является рабочим alias.</p>${state.designations.filter(d=>d.target===id).map(d=>`<p>${h(d.text)} <button type="button" data-remove-word="${h(d.id)}">Удалить обозначение…</button></p>`).join('')}<details><summary>Происхождение и прежний владелец</summary><pre>${h(JSON.stringify(n,null,2))}</pre></details>`,async f=>{await mutate('designation_save',{nodeId:id,text:f.get('text')});},'Добавить обозначение');
 $('#concept-edit').onclick=run(()=>graphEditor.node(id));$('#concept-reuse').onclick=run(()=>reuseNode(id));document.querySelectorAll('[data-remove-word]').forEach(b=>b.onclick=run(()=>Management.remove(['designation:'+b.dataset.removeWord])));
}
