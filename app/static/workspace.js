'use strict';
// The existing constructor and SVG view operate on one canonical graph.
const $=s=>document.querySelector(s),h=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state,revision,token,sceneView,busy=false,selected,selectedEdge,selectedContext,graph,definitionUI,toastTimer,view='builder',layoutUI;
const canvasMenu=new CanvasMenu();
let ui={};try{ui=JSON.parse(localStorage.getItem('concept-field-permanent-ui')||'{}');}catch{}
function saveUI(){try{localStorage.setItem('concept-field-permanent-ui',JSON.stringify(ui));}catch{}}
let captionState,captionIndex;function captions(){if(captionState!==state){captionState=state;captionIndex=AlphaCaptions.create(state);}return captionIndex;}const name=id=>captions().display(id);
const edgeName=e=>`${e.role==='component'?'Обязательный компонент: ':''}${state.nodes.find(n=>n.id===e.from)?.operatorAlias||name(e.from)} → ${state.nodes.find(n=>n.id===e.to)?.operatorAlias||name(e.to)} · ${e.id}`;
const run=fn=>async(...args)=>{try{return await fn(...args);}catch(e){toast(e.message,true);}};
function toast(message,error=false){$('#toast').textContent=message;$('#toast').hidden=false;$('#toast').classList.toggle('error',error);clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,error?12000:4500);}
async function api(url,body){let response;try{response=await fetch(url,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Workspace-Token':token},body:JSON.stringify(body)});}catch{throw Error('Нет связи с локальным сервером; введённый текст остаётся в этой вкладке.');}const data=await response.json();if(!response.ok)throw Error(data.error||`HTTP ${response.status}`);return data;}
async function mutate(action,data){if(busy)throw Error('Дождитесь сохранения.');if(action!=='definition_save')definitionUI?.capture();busy=true;document.body.classList.add('busy');$('#save-status').textContent='Сохранение…';try{const result=await api('/api/action',{action,data,revision});({state,revision,sceneView}=result);if(action==='graph_apply'&&definitionUI?.draft){const d=state.definitionDrafts.find(d=>d.id===definitionUI.draft.id);if(d?.graphBase&&!definitionUI.changed)definitionUI.draft=structuredClone(d);else if(d?.graphStale)definitionUI.draft.graphStale=d.graphStale;}if(action==='import'||action==='restore')definitionUI.draft=null;render();return result.result;}finally{busy=false;document.body.classList.remove('busy');$('#save-status').textContent=`Сохранено · версия ${revision}`;}}
function closeDialog(){definitionUI?.capture();$('#dialog').close();canvasMenu.close(false);}
function dialog(title,content,submit,button='Сохранить'){
  definitionUI?.capture();canvasMenu.close(false);
  $('#dialog-body').innerHTML=`<h2>${h(title)}</h2><form id="modal-form">${content}<div class="dialog-actions"><button id="modal-cancel" type="button">Отмена</button>${submit?`<button type="submit" class="primary">${h(button)}</button>`:'<button id="modal-close" type="button">Закрыть</button>'}</div></form>`;
  const dlg=$('#dialog');if(!dlg.open)dlg.showModal();dlg.scrollTop=0;$('#modal-cancel').onclick=closeDialog;if($('#modal-close'))$('#modal-close').onclick=closeDialog;$('#modal-form').onsubmit=run(async e=>{e.preventDefault();if(submit&&await submit(new FormData(e.target))!==false)dlg.close();});
}
async function download(url,filename){const r=await fetch(url);if(!r.ok)throw Error((await r.json()).error);const a=document.createElement('a');a.href=URL.createObjectURL(await r.blob());a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1500);}
function render(){if(view==='thoughts')ThoughtLab.render();else if(view==='builder')definitionUI.render();else if(view==='scenes')SceneLab.render();else renderGraph();$('#global-count').textContent=`${state.nodes.length} концептов · ${state.edges.filter(e=>e.role==='relation').length} отношений · ${state.edges.filter(e=>e.role==='component').length} компонентов · ${state.contextEdges.length} контекстных`;}
function showView(next){
  if(view==='thoughts'&&next!=='thoughts'){ThoughtLab.save().catch(e=>toast(e.message,true));}
  if(next!=='graph'&&(layoutUI?.preview||layoutUI?.worker))layoutUI.cancel();definitionUI.capture();canvasMenu.close(false);view=['graph','scenes','thoughts'].includes(next)?next:'builder';ui.workspaceView=view;saveUI();
  $('#thoughts-panel').hidden=view!=='thoughts';$('#go-thoughts').setAttribute('aria-pressed',String(view==='thoughts'));
  $('#scenes-panel').hidden=view!=='scenes';$('#go-scenes').setAttribute('aria-pressed',String(view==='scenes'));$('#builder').hidden=view!=='builder';$('#permanent-panel').hidden=view!=='graph';
  $('#go-builder').setAttribute('aria-pressed',String(view==='builder'));$('#go-graph').setAttribute('aria-pressed',String(view==='graph'));
  render();window.scrollTo(0,0);
}
function renderGraph(){
  if(!state.nodes.some(n=>n.id===selected))selected=state.nodes[0]?.id;
  if(!state.edges.some(e=>e.id===selectedEdge))selectedEdge=null;
  if(!state.contextEdges.some(c=>c.id===selectedContext))selectedContext=null;
  const q=$('#graph-search').value.trim().toLocaleLowerCase('ru').replaceAll('ё','е');
  const rows=state.nodes.filter(n=>captions().matches(n.id,q)).sort((a,b)=>captions().rank(a.id,q)-captions().rank(b.id,q)||name(a.id).localeCompare(name(b.id),'ru')||a.id.localeCompare(b.id));const matches=new Set(q?rows.map(n=>n.id):[]);
  $('#graph-results').innerHTML=q?`<small>${rows.length} совпадений · показано до 40</small>${rows.slice(0,40).map(n=>`<button data-global-node="${h(n.id)}">${h(name(n.id))}<code>${h(n.id)}</code><small>Позиция ${n.x}, ${n.y} · ${state.edges.filter(e=>e.from===n.id||e.to===n.id).length} связей</small></button>`).join('')}`:'';
  $('#graph-results').querySelectorAll('[data-global-node]').forEach(b=>b.onclick=()=>select(b.dataset.globalNode,true));
  let candidates=state.nodes;
  if($('#graph-mode').value==='neighbourhood'&&selected){const seen=new Set([selected]);let front=[selected];const depth=Math.max(0,Math.min(10,Number($('#graph-depth').value)||0));for(let i=0;i<depth;i++){const next=[];for(const e of state.edges)if(front.includes(e.from)||front.includes(e.to))for(const id of [e.from,e.to])if(!seen.has(id)){seen.add(id);next.push(id);}front=next;}candidates=state.nodes.filter(n=>seen.has(n.id));}
  let nodes=(q?[...candidates].sort((a,b)=>Number(matches.has(b.id))-Number(matches.has(a.id))):candidates).slice(0,2000);if(selected&&!nodes.some(n=>n.id===selected)){nodes=nodes.slice(0,1999);nodes.push(state.nodes.find(n=>n.id===selected));}
  const metric=OverviewGeometry.metrics(state),ids=new Set(nodes.map(n=>n.id)),edges=state.edges.filter(e=>ids.has(e.from)&&ids.has(e.to));
  if(nodes.length){if(!graph){graph=new GraphView($('#permanent-graph'),{createContext:run(prepareMarkerContext),circular:true,edgeLimit:6000,contextBudgetMs:120,minScale:.002,labelMode:()=>ui.graphLabelMode||'auto',select:id=>select(id),editNode:id=>openNode(id),editEdge:id=>openEdge(id),editContext:id=>openContext(id),contextMenu:(kind,id,e)=>globalMenu(kind,id,e),canInteract:id=>!busy&&(!id||!layoutUI?.preview),savePosition:(id,p)=>mutate('position',{nodeId:id,...p}),error:e=>toast(e.message,true),changed:snapshot=>{ui.graph=snapshot;saveUI();}});if(ui.graph)graph.restore(ui.graph);}
    graph.update({id:'permanent',title:'Постоянный граф',rootId:selected},{nodes:nodes.map(n=>({...n,...metric.get(n.id),...layoutUI?.preview?.positions[n.id],label:$('#graph-ids').checked?n.id:name(n.id),displayTitle:captions().label(n.id)+'\nID: '+n.id,badge:n.structure==='alpha'?(captions().anonymous(n.id)?'α · #'+captions().token(n.id):'α · обязательный состав'):n.kind})),edges:edges.slice(0,6000).map(e=>({...e,displayTitle:edgeName(e)})),contextEdges:state.contextEdges},selected,new Map(nodes.map(n=>[n.id,q?(matches.has(n.id)?'search-match':'search-dim'):''])));
  }else{$('#permanent-graph').textContent='Граф пуст. Выберите определение в конструкторе и подтвердите включение.';graph?.observer.disconnect();graph=null;}
  const overlaps=OverviewGeometry.overlaps(nodes.map(n=>({...n,...metric.get(n.id),...layoutUI?.preview?.positions[n.id]}))),overlap=overlaps.length;
  $('#graph-caption').textContent=`Показано ${nodes.length} из ${candidates.length} концептов, ${Math.min(edges.length,6000)} из ${edges.length} рёбер. Цвет: concept — синий, α — фиолетовый. Поиск — подсветка интерфейса.${overlap?` Наложения узлов: ${overlaps.truncated?'≥':''}${overlap}; используйте раскладку.`:''}`;
}
function select(id,center=false){selected=id;selectedEdge=null;selectedContext=null;renderGraph();if(center)graph?.center(id);}
async function reuseNode(id){closeDialog();showView('builder');await definitionUI.addExisting(id);}
function neighbours(id){closeDialog();selected=id;selectedEdge=null;selectedContext=null;$('#graph-mode').value='neighbourhood';renderGraph();graph?.fit();}
async function editDefinition(id){
  definitionUI.capture();if(definitionUI.changed)await definitionUI.save();
  const draft=state.definitionDrafts.find(d=>d.id===id);if(!draft)throw Error('Черновик происхождения не найден.');
  closeDialog();definitionUI.draft=structuredClone(draft);definitionUI.route=[];definitionUI.interaction=null;definitionUI.selectedObject=null;ui.definitionDraft=id;showView('builder');
}
function openNode(id){selected=id;selectedEdge=null;selectedContext=null;definitionUI.openNode(id,{global:true,reuse:reuseNode,neighbours,editDefinition});}
function globalMenu(kind,id,event){
  if(busy)return;
  if(kind==='node'){selected=id;selectedEdge=null;selectedContext=null;}else if(kind==='edge'){selectedEdge=id;selectedContext=null;}else if(kind==='context'){selectedContext=id;selectedEdge=null;}
  const action=(id,label,fn)=>({id,label,run:run(fn)});
  const actions=kind==='context'?[action('inspect-context','Контекстная связь…',()=>openContext(id)),action('edit-definition','Редактировать в конструкторе…',()=>editDefinition(state.contextEdges.find(c=>c.id===id).definitionId))]:kind==='node'?[action('edit-node','Обозначения и свойства…',()=>openNode(id)),action('reuse','Использовать ID в миниграфе',()=>reuseNode(id)),action('neighbours','Открыть окружение',()=>neighbours(id)),action('edit-definition','Редактировать в конструкторе…',()=>editDefinition(state.nodes.find(n=>n.id===id).definitionId))]:kind==='edge'?[action('inspect-edge','Ребро и его контекст…',()=>openEdge(id)),action('edit-definition','Редактировать в конструкторе…',()=>editDefinition(state.edges.find(e=>e.id===id).definitionId))]:[action('builder','Открыть конструктор',()=>showView('builder')),action('all','Показать весь граф',()=>{$('#graph-mode').value='all';renderGraph();graph?.fit();}),action('fit','Вписать граф',()=>graph?.fit())];
  if(kind==='node')actions.push(action('graph-edit','Изменить общий объект…',()=>graphEditor.node(id)),action('graph-uses','Использования и преобразование…',()=>graphEditor.uses(id)),action('graph-region','Редактировать область в миниграфе…',()=>graphEditor.region(neighbourhoodIds())));
  if(kind==='edge'||kind==='context')actions.push(action('graph-edit','Изменить общий объект…',()=>graphEditor.edge(id,kind==='context')));
  if(kind==='node')actions.push(action('pin',state.nodes.find(n=>n.id===id).layoutPinned?'Открепить узел':'Закрепить узел',async()=>{layoutUI.cancel();await mutate('layout_pin',{nodeIds:[id],pinned:!state.nodes.find(n=>n.id===id).layoutPinned});}));
  actions.push(action('contexts','Контекстные связи по ID…',()=>openContexts()));
  canvasMenu.open(event,kind==='node'?name(id):kind==='edge'?edgeName(state.edges.find(e=>e.id===id)):kind==='context'?'Контекст '+id:'Постоянный граф',actions);
}
function openContexts(){
  dialog('Контекстные связи постоянного графа',`<p>Все пары доступны независимо от фильтра и геометрии полотна. Поиск: контекстный ID или ID обычного ребра.</p><input id="global-context-search" type="search" aria-label="Поиск контекстных связей" placeholder="ID контекста или обычного ребра"><div id="global-context-results"></div>`);
  const draw=()=>{const q=$('#global-context-search').value.trim().toLowerCase(),rows=state.contextEdges.filter(c=>`${c.id} ${c.from} ${c.to}`.toLowerCase().includes(q));$('#global-context-results').innerHTML=`<p>${rows.length} пар · показано до 800</p>${rows.slice(0,800).map(c=>`<button type="button" class="object-choice" data-global-context="${h(c.id)}">${h(edgeName(state.edges.find(e=>e.id===c.from)))}<br>→ ${h(edgeName(state.edges.find(e=>e.id===c.to)))}<code>${h(c.id)}</code></button>`).join('')}`;$('#global-context-results').querySelectorAll('[data-global-context]').forEach(b=>b.onclick=()=>openContext(b.dataset.globalContext));};$('#global-context-search').oninput=draw;draw();
}
async function prepareMarkerContext(from,to){
  const edges=[from,to].map(id=>state.edges.find(e=>e.id===id));
  if(edges.some(e=>!e||e.role!=='relation'))throw Error('Контекст связывает только обычные рёбра.');
  dialog('Контекст между выбранными рёбрами',`<p><code>${h(from)}</code> → <code>${h(to)}</code></p><p>Существующие ID будут выбраны в текущий черновик. Контекст добавляется в конструкторе; включение в постоянный граф требует прежнего preview и подтверждения.</p>`,async()=>{
    definitionUI.capture();const d=structuredClone(definitionUI.draft);
    for(const edge of edges){
      for(const id of [edge.from,edge.to])if(!d.nodes.some(n=>n.id===id)){const n=state.nodes.find(n=>n.id===id);d.nodes.push({id,existing:true,designation:name(id),x:n.x,y:n.y,base:structuredClone(n)});}
      if(!d.edges.some(e=>e.id===edge.id))d.edges.push({id:edge.id,from:edge.from,to:edge.to,existing:true});
    }
    if(d.nodes.length>80||d.edges.length>160)throw Error('В текущем черновике недостаточно места для этих ID. Выберите другой черновик в конструкторе.');
    definitionUI.draft=d;await definitionUI.save();showView('builder');definitionUI.openRoutes();$('#def-context-from').value=from;$('#def-context-to').value=to;return false;
  },'Выбрать ID в конструктор');
}
function openEdge(id){selectedContext=null;selectedEdge=id;const edge=state.edges.find(e=>e.id===id);if(!edge)return;const contexts=state.contextEdges.filter(c=>c.from===id||c.to===id);dialog(edge.role==='component'?'Обязательный компонент α':'Обычное ребро и контекст',`<p>${h(edgeName(edge))}</p><p>Направление ${h(edge.from)} → ${h(edge.to)}</p><h3>Контекстные связи</h3>${contexts.map(c=>`<p><code>${h(c.id)}</code><br>${h(c.from)} → ${h(c.to)}</p>`).join('')||'<p>Нет контекстных пар.</p>'}<details><summary>Происхождение</summary><pre>${h(JSON.stringify(edge.origins,null,2))}</pre></details><button type="button" id="edge-origin">Редактировать в конструкторе</button>`);$('#edge-origin').onclick=run(()=>editDefinition(edge.definitionId));}
function openContext(id){
  const c=state.contextEdges.find(v=>v.id===id);if(!c)return;selectedContext=id;selectedEdge=null;
  dialog('Направленная контекстная связь',`<p><code>${h(c.id)}</code></p><p>${h(edgeName(state.edges.find(e=>e.id===c.from)))}<br>→ ${h(edgeName(state.edges.find(e=>e.id===c.to)))}</p><p>Контекст соединяет обычные рёбра, а не концепты.</p><button type="button" id="context-origin">Редактировать в конструкторе</button>`);$('#context-origin').onclick=run(()=>editDefinition(c.definitionId));
}
async function tools(){
  definitionUI.capture();if(definitionUI.changed)await definitionUI.save();const diagnostics=await api('/api/diagnostics'),rows=await api('/api/history');
  dialog('Данные, история и диагностика',`<button type="button" id="global-export">Экспорт графа и резервная копия JSON ↓</button><label>Импорт постоянного графа<input id="global-import-file" type="file" accept=".json,application/json"></label><button type="button" id="global-import-preview">Просмотреть импорт</button><p>Импорт сохраняет ID, добавляет отсутствующие объекты и отклоняет конфликты. Исторические документы открываются отдельно.</p>${diagnostics.legacyBackup?'<p id="transition-notice">Историческая база сохранена и проверена. Новый граф создан отдельно от прежних данных.</p><button type="button" id="legacy-download">Скачать проверенную старую SQLite ↓</button>':''}<details><summary>Диагностика и сохранность истории</summary><pre>${h(JSON.stringify(diagnostics,null,2))}</pre></details><details><summary>История каркаса и сцен (${rows.length})</summary>${rows.slice(0,80).map(r=>`<p>#${r.id} · ${h(r.time)} · ${h(r.action)}<br>${h(r.detail)} <button type="button" data-global-restore="${r.id}">Восстановить версию</button></p>`).join('')}</details>`);
  $('#global-export').onclick=run(async()=>{if(definitionUI.changed)await definitionUI.save();await download('/api/export','concept-field-permanent.json');});if($('#legacy-download'))$('#legacy-download').onclick=run(()=>download('/api/legacy-backup','concept-field-legacy-backup.sqlite3'));
  $('#global-import-preview').onclick=run(async()=>{const file=$('#global-import-file').files[0];if(!file)throw Error('Выберите JSON.');if(file.size>64*1024*1024)throw Error('Предел файла — 64 МиБ.');const document=JSON.parse(await file.text());const preview=await api('/api/import-preview',{document});dialog('Подтвердить импорт',`<pre>${h(JSON.stringify(preview,null,2))}</pre><label class="checkbox"><input name="confirmed" type="checkbox" required>Подтверждаю добавление объектов по исходным ID</label>`,async f=>{await mutate('import',{document,confirmed:f.has('confirmed')});},'Импортировать');});
  document.querySelectorAll('[data-global-restore]').forEach(b=>b.onclick=()=>{const targetRevision=Number(b.dataset.globalRestore);dialog('Восстановление каркаса, сцен и рабочих областей',`<p>Текущие ${state.nodes.length} узлов / ${state.edges.length} рёбер и все сцены/рабочие области будут заменены сохранённой версией #${targetRevision}. Более поздняя история сохранится.</p><label class="checkbox"><input name="confirmed" type="checkbox" required>Подтверждаю восстановление всего состояния</label>`,f=>mutate('restore',{targetRevision,confirmed:f.has('confirmed')}),'Восстановить');});
}
definitionUI=new DefinitionBuilder({permanent:true,state:()=>state,study:()=>({...state,id:'permanent',title:'Постоянный граф'}),ui:()=>ui,saveUI,busy:()=>busy,api,mutate,toast,run,dialog,download,closeDialog,menu:canvasMenu});
function neighbourhoodIds(){const seen=new Set([selected]),adj=new Map(state.nodes.map(n=>[n.id,[]]));for(const e of state.edges){adj.get(e.from).push(e.to);adj.get(e.to).push(e.from);}let front=[selected];for(let i=0;i<Number($('#graph-depth').value);i++){const next=[];for(const id of front)for(const n of adj.get(id)||[])if(!seen.has(n)){seen.add(n);next.push(n);}front=next;}return [...seen];}
layoutUI=new PermanentLayout({state:()=>state,revision:()=>revision,selected:()=>selected,neighbourhood:neighbourhoodIds,render:renderGraph,graph:()=>graph,dialog,toast,mutate});
$('#graph-label-mode').value=ui.graphLabelMode||'auto';$('#graph-label-mode').onchange=()=>{ui.graphLabelMode=$('#graph-label-mode').value;saveUI();graph?.paintLabels();};
$('#graph-layout').onclick=run(()=>layoutUI.open());$('#graph-layout-apply').onclick=run(()=>layoutUI.apply());$('#graph-layout-cancel').onclick=()=>layoutUI.cancel();$('#graph-layout-undo').onclick=run(()=>layoutUI.undo());
$('#graph-actions').onclick=e=>globalMenu(selectedContext?'context':selectedEdge?'edge':selected?'node':'canvas',selectedContext||selectedEdge||selected,e);$('#permanent-graph').oncontextmenu=e=>{if(e.target.closest('svg'))return;e.preventDefault();globalMenu('canvas',null,e);};$('#workspace-tools').onclick=run(tools);$('#graph-search').oninput=renderGraph;$('#graph-mode').onchange=renderGraph;$('#graph-depth').onchange=renderGraph;$('#graph-ids').onchange=renderGraph;$('#graph-fit').onclick=()=>graph?.fit();$('#go-thoughts').onclick=()=>showView('thoughts');$('#go-scenes').onclick=()=>showView('scenes');$('#go-builder').onclick=()=>showView('builder');$('#go-graph').onclick=()=>showView('graph');
window.addEventListener('keydown',e=>{if(e.key==='Escape'&&view==='builder'&&definitionUI.interaction){definitionUI.interaction=null;definitionUI.render();}});
$('#dialog').addEventListener('cancel',()=>definitionUI.capture());
window.addEventListener('beforeunload',e=>{if(definitionUI.changed||ThoughtLab.hasUnsaved()){e.preventDefault();e.returnValue='';}});
run(async()=>{({state,revision,token,sceneView}=await api('/api/state'));definitionUI.render();showView(ui.workspaceView||'thoughts');$('#save-status').textContent=`Сохранено · версия ${revision}`;})();
