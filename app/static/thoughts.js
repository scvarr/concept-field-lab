'use strict';
// The operator authors every binding. All persistent graph edits use M018.
const ThoughtLab=(()=>{
  const scratchKey='concept-field-thought-scratch:'+location.origin;
  let working=null,dirty=false,timer=null,pending=null,quiet=false,canvas=null,selectedLocal=null;
  const lab=()=>state.thoughtLab||{drafts:[],templates:[],candidates:[],currentDraftId:null};
  const label=id=>{const n=state.nodes.find(n=>n.id===id),text=name(id);return n?.operatorAlias||(text===id?'#'+id.slice(0,8):text);};
  const option=(id,text)=>`<option value="${h(id)}">${h(text)}</option>`;
  const fragment=()=>working?Array.from(working.text).slice(...working.selection).join(''):'';
  const current=()=>lab().drafts.find(d=>d.id===lab().currentDraftId);
  const writable=()=>working?.status==='draft';
  function touch(){dirty=true;try{localStorage.setItem(scratchKey,JSON.stringify({revision,draft:working}));}catch{}clearTimeout(timer);timer=setTimeout(run(()=>save()),600);}
  async function save(){
    clearTimeout(timer);if(pending)await pending;if(!dirty||!writable())return;
    const d=structuredClone(working);dirty=false;quiet=true;
    pending=mutate('thought_save',{draftId:d.id,text:d.text,config:d.config,selection:d.selection,anchors:d.anchors});
    try{await pending;}catch(e){dirty=true;try{localStorage.setItem(scratchKey,JSON.stringify({revision,draft:working}));}catch{}throw e;}finally{pending=null;quiet=false;}
    if(dirty)await save();else localStorage.removeItem(scratchKey);
  }
  async function act(action,data={}){await save();return mutate(action,{draftId:working?.id,...data});}
  function anchor(id){if(working.selection[0]<working.selection[1])working.anchors.push({id,start:working.selection[0],end:working.selection[1]});}
  function missing(){const c=working.contract||working.config,gaps=Object.keys(c).flatMap(k=>c[k].filter(v=>v.required).filter(v=>{const n=working.config[k].find(i=>i.id===v.id);return !n?.included||(k==='nodes'&&!n.value.trim());}).map(v=>v.id));return [...new Set([...gaps,...working.config.nodes.filter(n=>n.included&&!n.value.trim()).map(n=>n.id)])];}
  function uses(id){
    return (state.sceneLab?.scenes||[]).flatMap(s=>s.objects.filter(o=>o.conceptId===id||o.contentConceptId===id).map(o=>`${s.label}: ${o.label} · ${o.id}`));
  }
  function render(recovered=null){
    if(quiet)return;
    if(canvas){canvas.observer.disconnect();canvas=null;}
    working=recovered?structuredClone(recovered):current()?structuredClone(current()):null;dirty=Boolean(recovered);
    const d=working,c=d?.config,readOnly=d?.status==='complete';
    let scratch;try{scratch=JSON.parse(localStorage.getItem(scratchKey)||'null');}catch{}
    $('#thoughts-panel').innerHTML=`<h2>Ручной разбор фразы</h2>${scratch?.draft?.id===d?.id?'<p>Есть локальный несохранённый ввод. <button id="thought-recover">Восстановить в редактор для проверки</button></p>':''}<div class="scene-toolbar"><button id="thought-new">Новая фраза</button><label>Сохранённый разбор<select id="thought-open">${lab().drafts.map(d=>option(d.id,`${d.status==='complete'?'✓':'Черновик'} ${d.text||'Новая фраза'} · ${d.id}`)).join('')}</select></label><button id="thought-refresh">Обновить</button></div>
    ${d?`<div class="thought-layout"><article><label>Исходная фраза<textarea id="thought-text" ${readOnly?'readonly':''}>${h(d.text)}</textarea></label><p>Выбранный фрагмент: <strong id="thought-fragment">${h(fragment()||'выделите текст')}</strong></p><button id="thought-save" ${readOnly?'disabled':''}>Сохранить черновик</button><p id="thought-status">${readOnly?'Завершено · сцена '+h(d.sceneId):'Черновик · обязательных пробелов: '+missing().length} ${d.templateRef?'· выбран шаблон '+h(lab().templates.find(t=>t.id===d.templateRef.id)?.label)+' v'+d.templateRef.version:''}</p>
    <div class="actions"><button id="thought-node" ${readOnly?'disabled':''}>Новый концепт…</button><button id="thought-reuse" ${readOnly?'disabled':''}>Найти / использовать…</button><button id="thought-relation" ${readOnly?'disabled':''}>Связь экземпляров…</button><button id="thought-context" ${readOnly?'disabled':''}>Контекстное разрешение…</button><button id="thought-permission" ${readOnly?'disabled':''}>Использовать разрешение…</button></div>
    <p>Новый концепт и связь создаются редактором M018 с preview. Новый концепт сразу предлагается для локального заполнения; существующее ребро выбирается по ID. Alias — рабочая подпись, не словарное обозначение.</p>
    <div id="thought-markers"></div><div id="thought-canvas" class="graph" aria-label="Графическая конструкция мысли"></div><p>Синий: непосредственное использование. Оранжевый: доступное продолжение. Серый: исключено. Двойной щелчок по элементу — значение и обязательность.</p></article>
    <aside><h3>Текущая конструкция · локальные экземпляры</h3><div id="thought-elements">${c.nodes.map(n=>`<button class="object-choice" data-thought-node="${h(n.id)}">${n.included?'●':'○'} ${h(label(n.conceptId))} ${n.required?'· обязательно':''}<br>${h(n.value||'значение не заполнено')}<code>концепт ${h(n.conceptId)} · экземпляр ${h(n.id)}</code></button>`).join('')||'<p>Выделите фрагмент, создайте или выберите концепт.</p>'}</div>
    <h4>Использования обычных рёбер</h4>${c.edges.map(e=>`<button class="object-choice" data-thought-edge="${h(e.id)}">${h(e.edgeId)} · ${e.included?(e.activation==='context'?'активно по команде контекста':'непосредственно активно'):'не произошло'}${e.required?' · обязательно':''}<br>${h(localName(e.from))} → ${h(localName(e.to))}</button>`).join('')}
    <h4>Контекстные разрешения</h4>${c.contexts.map(p=>`<button class="object-choice" data-thought-context="${h(p.id)}">${h(p.contextId)} · ${p.included?'включено':'исключено'}${p.required?' · обязательно':''}<br>${h(p.from)} → ${h(p.to)}</button>`).join('')||'<p>Нет</p>'}
    <div id="thought-continuations"></div><h4>Сохранение мысли</h4><label>Сцена<select id="thought-scene"><option value="">Текущий разговор / новая сцена</option>${(state.sceneLab?.scenes||[]).map(s=>option(s.id,s.label+' · '+s.kind)).join('')}</select></label><button id="thought-complete" ${readOnly?'disabled':''}>Завершить мысль в сцене</button><button id="thought-detach" ${readOnly||!d.templateRef?'disabled':''}>Начать явное уточнение структуры</button><button id="thought-template" ${readOnly?'disabled':''}>Сохранить конструкцию как шаблон…</button>
    <details><summary>Соответствия фрагментов и ID (${d.anchors.length})</summary>${d.anchors.map(a=>`<p>«${h(Array.from(d.text).slice(a.start,a.end).join(''))}» → <code>${h(a.id)}</code></p>`).join('')}</details></aside></div>`:'<p>Начните с новой фразы. Постоянный граф может быть пустым.</p>'}
    <details id="thought-library" open><summary>Поиск конструкций и предыдущие применения</summary><input id="thought-template-query" type="search" aria-label="Поиск конструкций" placeholder="Название, alias, ID узла, ребра или контекста"><div id="thought-templates"></div></details>
    <details><summary>Гипотезы новых контекстных рёбер (${lab().candidates.length})</summary><p>Ручные кандидаты с обоснованием. Вычислимый математический критерий не реализован. Гипотеза не создаёт разрешение.</p><button id="thought-hypothesis">Зафиксировать гипотезу…</button><div id="thought-hypotheses">${lab().candidates.map(c=>`<p><code>${h(c.from)} → ${h(c.to)}</code> · ${h(c.status)}<br>${h(c.reason)}<br>${h(c.decision||'Решение не принято')}${c.status==='pending'?` <button data-thought-decide="${h(c.id)}">Решение…</button>`:''}</p>`).join('')}</div></details>`;
    if($('#thought-recover'))$('#thought-recover').onclick=()=>{render(scratch.draft);$('#thought-status').textContent='Локальный ввод восстановлен в редактор. Проверьте и сохраните; сервер проверит текущие ID и обязательность.';};
    $('#thought-new').onclick=run(newPhrase);$('#thought-refresh').onclick=run(async()=>{try{await save();}catch(e){toast(e.message+' Локальный ввод сохранён для восстановления.',true);}({state,revision,sceneView}=await api('/api/state'));render();$('#save-status').textContent=`Сохранено · версия ${revision}`;});
    $('#thought-open').value=d?.id||'';$('#thought-open').onchange=run(e=>act('thought_select',{draftId:e.target.value}));
    $('#thought-template-query').oninput=renderTemplates;renderTemplates();
    $('#thought-hypothesis').onclick=run(hypothesis);document.querySelectorAll('[data-thought-decide]').forEach(b=>b.onclick=run(()=>decide(b.dataset.thoughtDecide)));
    if(!d)return;
    const text=$('#thought-text');
    text.oninput=()=>{working.text=text.value;working.anchors=[];working.selection=[0,0];$('#thought-fragment').textContent='выделите текст';touch();};
    const selection=()=>{if(!writable())return;working.selection=[Array.from(text.value.slice(0,text.selectionStart)).length,Array.from(text.value.slice(0,text.selectionEnd)).length];$('#thought-fragment').textContent=fragment()||'выделите текст';touch();};
    text.onselect=selection;text.onkeyup=selection;text.onmouseup=selection;
    $('#thought-save').onclick=run(async()=>{await save();render();});
    $('#thought-node').onclick=run(async()=>{await save();await graphEditor.node(null,{afterApply:id=>addNode(id)});});
    $('#thought-reuse').onclick=run(reuse);$('#thought-relation').onclick=run(relation);$('#thought-context').onclick=run(async()=>{await save();await graphEditor.edge(null,true);});$('#thought-permission').onclick=run(permission);
    $('#thought-detach').onclick=run(()=>act('thought_detach'));$('#thought-template').onclick=run(template);$('#thought-complete').onclick=run(()=>act('thought_complete',{sceneId:$('#thought-scene').value||null}));
    document.querySelectorAll('[data-thought-node]').forEach(b=>b.onclick=run(()=>editNode(b.dataset.thoughtNode)));
    document.querySelectorAll('[data-thought-edge]').forEach(b=>b.onclick=run(()=>editEdge(b.dataset.thoughtEdge)));
    document.querySelectorAll('[data-thought-context]').forEach(b=>b.onclick=run(()=>editPermission(b.dataset.thoughtContext)));
    drawCanvas();drawContinuations();
  }
  function localName(id){const n=working.config.nodes.find(n=>n.id===id);return n?`${label(n.conceptId)}: ${n.value||'…'} · ${n.id}`:id;}
  async function newPhrase(templateId=null){
    await save();dialog('Новая фраза',`<label>Текст<textarea name="text" required></textarea></label><label>Конструкция<select name="templateId"><option value="">Построить вручную</option>${lab().templates.map(t=>option(t.id,t.label+' · v'+t.version)).join('')}</select></label>`,async f=>{await act('thought_new',{text:f.get('text'),templateId:f.get('templateId')||null});});
    if(typeof templateId==='string')$('#modal-form [name=templateId]').value=templateId;
  }
  function searchRows(query){
    const q=query.trim().toLocaleLowerCase('ru'),scenes=state.sceneLab?.scenes||[],cur=scenes.find(s=>s.id===state.sceneLab?.currentSceneId);
    const layers=[['Текущая динамическая сцена',cur?[cur]:[]],['Конкретные накопленные сцены',scenes.filter(s=>s.id!==cur?.id&&s.kind==='dialogue')],['Абстрактные сцены знаний',scenes.filter(s=>s.kind==='knowledge')]];
    const nodeText=n=>[n.id,label(n.id),n.operatorAlias,...state.designations.filter(d=>d.target===n.id).map(d=>d.text)].join(' ').toLocaleLowerCase('ru');
    let html=layers.map(([title,ss])=>`<h4>${title}</h4>${ss.flatMap(s=>s.objects.filter(o=>!q||[o.id,o.label,nodeText(state.nodes.find(n=>n.id===o.conceptId))].join(' ').toLocaleLowerCase('ru').includes(q)).slice(0,30).map(o=>`<button type="button" class="object-choice" data-reuse-id="${h(o.conceptId)}">${h(label(o.conceptId))} · ${h(o.conceptId)}<br>${h(s.label)}: ${h(o.label)} · прежний экземпляр ${h(o.id)}<small>Будет новый независимый локальный экземпляр.</small></button>`)).join('')||'<p>Нет совпадений</p>'}`).join('');
    const nodes=state.nodes.filter(n=>!q||nodeText(n).includes(q)||state.edges.some(e=>(e.from===n.id||e.to===n.id)&&[e.id,label(e.from),label(e.to)].join(' ').toLocaleLowerCase('ru').includes(q))).slice(0,60);
    html+=`<h4>Постоянный граф · окружение и прежние применения</h4>${nodes.map(n=>`<button type="button" class="object-choice" data-reuse-id="${h(n.id)}">${h(label(n.id))}<code>${h(n.id)}</code><small>${h(state.edges.filter(e=>e.from===n.id||e.to===n.id).slice(0,8).map(e=>`${label(e.from)} → ${label(e.to)} · ${e.id}`).join('; ')||'Окружение пусто')}<br>${h(uses(n.id).slice(-4).join('; ')||'Применений пока нет')}</small></button>`).join('')}`;
    return html;
  }
  async function reuse(){
    await save();dialog('Найти и использовать существующий ID',`<label>Поиск<input id="thought-search" type="search" value="${h(fragment())}"></label><p>Поиск по тексту, ID и окружению. Очистите запрос для просмотра безымянных элементов. Порядок источников фиксирован; смысловую применимость решает оператор.</p><div id="thought-search-results"></div>`);
    const draw=()=>{$('#thought-search-results').innerHTML=searchRows($('#thought-search').value);document.querySelectorAll('[data-reuse-id]').forEach(b=>b.onclick=run(()=>addNode(b.dataset.reuseId)));};$('#thought-search').oninput=draw;draw();
  }
  async function addNode(id){
    const n=state.nodes.find(n=>n.id===id);dialog('Локальное использование концепта',`<p>${h(label(id))} · <code>${h(id)}</code></p><label>Значение экземпляра<input name="value" value="${h(fragment())}"></label><label>Рабочий alias концепта (не словарное обозначение)<input name="alias" value="${h(n.operatorAlias||'')}"></label><label class="checkbox"><input name="required" type="checkbox" checked>Обязательный элемент шаблона</label>`,async f=>{
      if(f.get('alias')!==(n.operatorAlias||''))await act('thought_alias',{nodeId:id,alias:f.get('alias')});
      const count=working.config.nodes.length,local={id:crypto.randomUUID(),conceptId:id,value:f.get('value'),required:f.has('required'),included:true,x:120+(count%3)*250,y:90+Math.floor(count/3)*300+(count%3===1?80:0)};
      working.config.nodes.push(local);anchor(local.id);dirty=true;await save();render();
    });
  }
  async function editNode(id){
    await save();const n=working.config.nodes.find(n=>n.id===id);if(!n)return;selectedLocal=id;
    dialog('Элемент конструкции',`<p>${h(label(n.conceptId))} · <code>${h(n.conceptId)}</code><br>Локальный экземпляр <code>${h(n.id)}</code></p><label>Значение<input name="value" value="${h(n.value)}"></label><label class="checkbox"><input name="included" type="checkbox" ${n.included?'checked':''}>Включён в эту мысль</label><label class="checkbox"><input name="required" type="checkbox" ${n.required?'checked':''}>Обязателен в шаблоне</label><button id="thought-edit-permanent" type="button">Изменить постоянный концепт в M018…</button><button id="thought-edit-alias" type="button">Изменить рабочий alias…</button>`,writable()?async f=>{n.value=f.get('value');n.included=f.has('included');n.required=f.has('required');if(!n.included){for(const e of working.config.edges)if(e.from===id||e.to===id)e.included=false;}anchor(id);dirty=true;await save();render();}:null);
    $('#thought-edit-permanent').onclick=run(()=>graphEditor.node(n.conceptId));$('#thought-edit-alias').onclick=()=>dialog('Рабочий alias',`<p>Не устанавливает лексическую или семантическую идентичность.</p><input name="alias" value="${h(state.nodes.find(v=>v.id===n.conceptId).operatorAlias||'')}">`,async f=>{await act('thought_alias',{nodeId:n.conceptId,alias:f.get('alias')});});
  }
  async function relation(){
    await save();const ns=working.config.nodes.filter(n=>n.included);
    dialog('Связь локальных экземпляров',`<label>От<select name="from">${ns.map(n=>option(n.id,localName(n.id))).join('')}</select></label><label>К<select name="to">${ns.map(n=>option(n.id,localName(n.id))).join('')}</select></label><label>Обычное ребро<select name="edgeId" id="thought-edge-choice"></select></label><p id="thought-edge-help"></p><label class="checkbox"><input name="required" type="checkbox" checked>Обязательно в шаблоне</label><button type="button" id="thought-create-relation">Создать недостающее ребро M018…</button>`,async f=>{
      const e=state.edges.find(e=>e.id===f.get('edgeId'));if(!e)throw Error('Сначала создайте обычное ребро для этих концов.');
      if(working.config.edges.some(v=>v.edgeId===e.id&&v.from===f.get('from')&&v.to===f.get('to')))throw Error('Это локальное использование уже существует.');
      const local={id:crypto.randomUUID(),edgeId:e.id,from:f.get('from'),to:f.get('to'),template:Object.fromEntries(['id','from','to','role','type'].map(k=>[k,e[k]||''])),required:f.has('required'),included:true,activation:'direct'};
      working.config.edges.push(local);anchor(local.id);dirty=true;await save();render();
    });
    const draw=()=>{const a=ns.find(n=>n.id===$('#modal-form [name=from]').value),b=ns.find(n=>n.id===$('#modal-form [name=to]').value),es=state.edges.filter(e=>e.role==='relation'&&e.from===a?.conceptId&&e.to===b?.conceptId);$('#thought-edge-choice').innerHTML=es.map(e=>option(e.id,`${e.type||'Отношение'} · ${e.id}`)).join('');$('#thought-edge-help').textContent=es.length?'Существующее ребро используется по тому же ID; дополнительный seed не нужен.':'Подходящего ребра нет. Создайте его через M018, затем выберите здесь.';};
    $('#modal-form [name=from]').onchange=draw;$('#modal-form [name=to]').onchange=draw;draw();
    $('#thought-create-relation').onclick=run(async()=>{const a=ns.find(n=>n.id===$('#modal-form [name=from]').value),b=ns.find(n=>n.id===$('#modal-form [name=to]').value);await graphEditor.edge();if(a&&b){$('#modal-form [name=from]').value=a.conceptId;$('#modal-form [name=to]').value=b.conceptId;}});
  }
  async function editEdge(id){
    await save();const e=working.config.edges.find(e=>e.id===id);
    dialog('Использование обычного ребра',`<p>${h(localName(e.from))} → ${h(localName(e.to))}<br><code>${h(e.edgeId)}</code></p><label class="checkbox"><input name="included" type="checkbox" ${e.included?'checked':''}>Непосредственно использовать в этой мысли</label><label class="checkbox"><input name="required" type="checkbox" ${e.required?'checked':''}>Обязательно в шаблоне</label><button id="thought-edit-relation" type="button">Изменить ребро M018…</button>`,writable()?async f=>{e.included=f.has('included');e.required=f.has('required');e.activation='direct';anchor(e.id);dirty=true;await save();render();}:null);
    $('#thought-edit-relation').onclick=run(()=>graphEditor.edge(e.edgeId));
  }
  async function permission(){
    await save();const es=working.config.edges,options=end=>es.map(e=>option(e.id,`${e.edgeId} · ${localName(e.from)} → ${localName(e.to)}`)).join('');
    dialog('Использовать контекстное разрешение',`<label>Источник<select name="from">${options()}</select></label><label>Продолжение<select name="to">${options()}</select></label><label>Разрешение<select name="contextId" id="thought-context-choice"></select></label><label class="checkbox"><input name="required" type="checkbox">Обязательно в шаблоне</label>`,async f=>{
      const p=state.contextEdges.find(c=>c.id===f.get('contextId'));if(!p)throw Error('Нет существующего разрешения между этими рёбрами.');
      if(working.config.contexts.some(c=>c.contextId===p.id&&c.from===f.get('from')&&c.to===f.get('to')))throw Error('Локальное разрешение уже включено.');
      const c={id:crypto.randomUUID(),contextId:p.id,template:{id:p.id,from:p.from,to:p.to},from:f.get('from'),to:f.get('to'),included:true,required:f.has('required')};working.config.contexts.push(c);anchor(c.id);dirty=true;await save();render();
    });
    const draw=()=>{const a=es.find(e=>e.id===$('#modal-form [name=from]').value),b=es.find(e=>e.id===$('#modal-form [name=to]').value);$('#thought-context-choice').innerHTML=state.contextEdges.filter(c=>c.from===a?.edgeId&&c.to===b?.edgeId).map(c=>option(c.id,c.id)).join('');};$('#modal-form [name=from]').onchange=draw;$('#modal-form [name=to]').onchange=draw;draw();
  }
  async function editPermission(id){
    await save();const c=working.config.contexts.find(c=>c.id===id);dialog('Локальное контекстное разрешение',`<p><code>${h(c.contextId)}</code></p><label class="checkbox"><input name="included" type="checkbox" ${c.included?'checked':''}>Включить разрешение</label><label class="checkbox"><input name="required" type="checkbox" ${c.required?'checked':''}>Обязательно в шаблоне</label>`,writable()?async f=>{c.included=f.has('included');c.required=f.has('required');dirty=true;await save();render();}:null);
  }
  function available(){const c=working.config;return c.contexts.filter(p=>p.included).flatMap(p=>{const a=c.edges.find(e=>e.id===p.from),b=c.edges.find(e=>e.id===p.to);if(!a.included||b.included||![a.from,a.to,b.from,b.to].every(id=>c.nodes.some(n=>n.id===id&&n.included&&n.value.trim())))return [];const bind=e=>{const m={};for(const k of ['from','to']){(m[e.template[k]]??=new Set()).add(e[k]);}return m;},l=bind(a),r=bind(b);if(Object.keys(l).some(k=>r[k]&&([...l[k]].some(i=>!r[k].has(i))||l[k].size!==r[k].size)))return [];return [{from:a.id,to:b.id,contextId:p.id}];});}
  function drawContinuations(){const rows=available();$('#thought-continuations').innerHTML=`<h4>Доступно, ещё не произошло (${rows.length})</h4>${rows.map(v=>`<button data-thought-step="${h(v.to)}" data-permission="${h(v.contextId)}" ${writable()?'':'disabled'}>Выполнить продолжение ${h(v.to)}</button>`).join('')||'<p>Нет доступных продолжений при этих привязках.</p>'}`;document.querySelectorAll('[data-thought-step]').forEach(b=>b.onclick=run(()=>act('thought_step',{targetId:b.dataset.thoughtStep,contextId:b.dataset.permission})));}
  function drawCanvas(){
    const c=working.config,markings=new Map(),targets=new Set(available().map(v=>v.to));
    for(const n of c.nodes)markings.set(n.id,n.included?'thought-direct':'thought-excluded');
    const edges=c.edges.map(e=>({...e,role:'relation',type:e.included?(e.activation==='context'?'по контексту':'активно'):targets.has(e.id)?'доступно':'не произошло',displayTitle:e.edgeId,color:e.included?(e.activation==='context'?'#5363a6':'#2866a0'):targets.has(e.id)?'#ca7800':'#a3acb5'}));
    canvas=new GraphView($('#thought-canvas'),{circular:false,select:id=>{selectedLocal=id;},editNode:run(editNode),editEdge:run(editEdge),editContext:run(editPermission),createContext:run(async(a,b)=>{await save();const source=c.edges.find(e=>e.id===a),target=c.edges.find(e=>e.id===b);await graphEditor.edge(null,true);$('#modal-form [name=from]').value=source.edgeId;$('#modal-form [name=to]').value=target.edgeId;}),canInteract:()=>!busy,savePosition:async(id,p)=>{if(!writable())return;Object.assign(working.config.nodes.find(n=>n.id===id),p);dirty=true;await save();},error:e=>toast(e.message,true)});
    $('#thought-markers').append(canvas.controls);
    canvas.update({id:working.id,title:'Конструкция мысли',rootId:c.nodes[0]?.id},{nodes:c.nodes.map(n=>({...n,label:label(n.conceptId),kind:n.value||'…',displayTitle:localName(n.id),badge:(n.value||'…')+(n.required?' · обяз.':'')})),edges,contextEdges:c.contexts.filter(p=>p.included).map(p=>({...p}))},selectedLocal,markings);
    if(c.nodes.length)canvas.fit();
  }
  async function template(){
    await save();dialog('Сохранить операторскую конструкцию',`<p>Выберите необходимую структуру кнопками элементов / рёбер / разрешений. Локальные значения и фраза не входят в шаблон. Ни одного постоянного узла для класса мысли не создаётся.</p><details><summary>Выделить структуру для шаблона</summary>${Object.keys(working.config).map(k=>working.config[k].map(v=>`<label class="checkbox"><input name="selected" type="checkbox" value="${h(v.id)}" checked>${h(k==='nodes'?localName(v.id):v.edgeId||v.contextId)} · ${h(v.id)}</label>`).join('')).join('')}</details><label>Название<input name="label" required value="${h(lab().templates.find(t=>t.id===working.templateRef?.id)?.label||'')}"></label><label>Действие<select name="templateId"><option value="">Новая конструкция</option>${lab().templates.map(t=>option(t.id,'Уточнить '+t.label+' (новая версия)')).join('')}</select></label>`,f=>act('thought_template',{label:f.get('label'),templateId:f.get('templateId')||null,selection:f.getAll('selected')}));
  }
  function renderTemplates(){const q=$('#thought-template-query').value.trim().toLocaleLowerCase('ru');$('#thought-templates').innerHTML=lab().templates.filter(t=>[t.id,t.label,...t.config.nodes.flatMap(n=>[n.conceptId,label(n.conceptId)]),...t.config.edges.map(e=>e.edgeId),...t.config.contexts.map(c=>c.contextId)].join(' ').toLocaleLowerCase('ru').includes(q)).map(t=>{const uses=lab().drafts.filter(d=>d.templateRef?.id===t.id);return `<article class="thought-template"><h4>${h(t.label)} · v${t.version}</h4><code>${h(t.id)}</code><p>${t.config.nodes.length} элементов · ${t.config.edges.length} рёбер · ${t.config.contexts.length} разрешений</p><p>${h(t.config.nodes.map(n=>`${label(n.conceptId)}${n.required?'*':''} · ${n.conceptId}`).join('; '))}</p><details><summary>Структура отношений и прежние применения (${uses.length})</summary>${t.config.edges.map(e=>`<p><code>${h(e.from)} → ${h(e.to)} · ${h(e.edgeId)}</code> ${e.required?'обязательно':''}</p>`).join('')}${uses.map(d=>`<button data-thought-previous="${h(d.id)}">${h(d.text)} · ${h(d.status)} · v${d.templateRef.version}</button>`).join('')}</details><button data-thought-apply="${h(t.id)}">Применить к новой фразе</button></article>`;}).join('')||'<p>Конструкции не найдены. Совпадение узлов не устанавливает равенство структур.</p>';document.querySelectorAll('[data-thought-apply]').forEach(b=>b.onclick=run(()=>newPhrase(b.dataset.thoughtApply)));document.querySelectorAll('[data-thought-previous]').forEach(b=>b.onclick=run(()=>act('thought_select',{draftId:b.dataset.thoughtPrevious})));}
  async function hypothesis(){await save();const es=state.edges.filter(e=>e.role==='relation');dialog('Гипотеза нового контекстного ребра',`<label>Источник<select name="from">${es.map(e=>option(e.id,edgeName(e))).join('')}</select></label><label>Продолжение<select name="to">${es.map(e=>option(e.id,edgeName(e))).join('')}</select></label><label>Основание / ограничения<textarea name="reason" required></textarea></label>`,f=>act('thought_candidate',{from:f.get('from'),to:f.get('to'),reason:f.get('reason')}));}
  async function decide(id){await save();const c=lab().candidates.find(c=>c.id===id);dialog('Решение оператора по гипотезе',`<p>Принятие возможно после отдельного создания контекстного разрешения через M018.</p><label>Решение<select name="status"><option value="rejected">Отклонить</option><option value="accepted">Принять существующее разрешение</option></select></label><label>Обоснование<textarea name="decision" required></textarea></label><button type="button" id="thought-candidate-create">Создать разрешение M018…</button>`,f=>act('thought_decide',{candidateId:id,status:f.get('status'),decision:f.get('decision')}));$('#thought-candidate-create').onclick=run(async()=>{await graphEditor.edge(null,true);$('#modal-form [name=from]').value=c.from;$('#modal-form [name=to]').value=c.to;});}
  return {render,save,hasUnsaved:()=>dirty||Boolean(pending)};
})();
