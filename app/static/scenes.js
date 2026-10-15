'use strict';
// Forms address scene IDs and template IDs explicitly. Text is never parsed.
const SceneLab=(()=>{
  let sceneId=null,workspaceId=null,sourceId=null;
  const lab=()=>state.sceneLab||{scenes:[],workspaces:[],currentSceneId:null};
  const opt=(id,text)=>`<option value="${h(id)}">${h(text)}</option>`;
  const title=s=>`${s.label} · ${s.kind==='knowledge'?'знание':'разговор'} · ${s.id}`;
  const objectName=(s,id)=>s.objects.find(o=>o.id===id)?.label||id;
  const factText=(s,f)=>`${objectName(s,f.from)} — ${f.template.type||f.edgeId} → ${objectName(s,f.to)}`;
  const call=(action,data)=>mutate(action,data);
  const contextName=id=>id?`${lab().scenes.find(s=>s.id===id)?.label||id} · ${id}`:'не задан';
  function render(){
    const model=lab(),panel=$('#scenes-panel');
    if(!model.scenes.some(s=>s.id===sceneId))sceneId=model.currentSceneId||model.scenes[0]?.id;
    const scene=model.scenes.find(s=>s.id===sceneId),current=model.scenes.find(s=>s.id===model.currentSceneId);
    const workspaces=model.workspaces.filter(w=>w.sceneId===current?.id);
    if(!workspaces.some(w=>w.id===workspaceId))workspaceId=workspaces.at(-1)?.id;
    const workspace=workspaces.find(w=>w.id===workspaceId);
    panel.innerHTML=`<h2>Сцены и динамическая рабочая область · эксперимент MVP</h2>
      <p>Каркас задаёт возможные связи. Оператор задаёт объекты, заполнения и изменения. Текст входа сохраняется без автоматического понимания.</p>
      <div class="scene-toolbar"><button id="scene-new">Создать сцену</button><label>Просмотр сцены<select id="scene-open">${model.scenes.map(s=>opt(s.id,title(s))).join('')}</select></label><button id="scene-refresh">Обновить с сервера</button></div>
      <p id="scene-current">Текущий разговор: ${current?h(title(current)):'не выбран'}</p><p id="scene-current-context">Действующий контекст: ${h(contextName(sceneView.activeContext[current?.id]))}</p>
      <div class="scene-columns"><article id="scene-detail">${scene?sceneHTML(scene):'<p>Создайте сцену знаний, затем разговорную сцену.</p>'}</article>
      <article id="scene-workspace"><h3>Рабочая область текущего разговора</h3><p>Извлечение копирует только выбранные заполнения и обязательный состав α. Локальные состояния: inactive / seed / context. Переход разрешён внутри одной группы извлечения. Сопоставление независимых сцен не реализовано. Совпадение содержательных ID не запускает переходы; семантическая применимость не установлена.</p>
      ${current?`<button id="scene-workspace-new">Новая рабочая область</button><label>Область<select id="scene-workspace-open">${workspaces.map(w=>opt(w.id,w.label+' · '+w.id)).join('')}</select></label>`:'<p>Создайте или выберите разговорную сцену.</p>'}
      ${workspace?workspaceHTML(workspace,current):''}</article></div>`;
    $('#scene-new').onclick=run(newScene);
    $('#scene-refresh').onclick=run(async()=>{({state,revision,sceneView}=await api('/api/state'));render();$('#save-status').textContent=`Сохранено · версия ${revision}`;});
    $('#scene-open').value=sceneId||'';
    $('#scene-open').onchange=e=>{sceneId=e.target.value;render();};
    if(scene)bindScene(scene);
    if(current){
      $('#scene-workspace-new').onclick=run(()=>dialog('Новая рабочая область', '<label>Обозначение<input name="label" required value="Рабочая область"></label>',async f=>{workspaceId=(await call('scene_workspace',{sceneId:current.id,label:f.get('label')})).workspaceId;render();}));
      $('#scene-workspace-open').value=workspaceId||'';
      $('#scene-workspace-open').onchange=e=>{workspaceId=e.target.value;render();};
    }
    if(workspace)bindWorkspace(workspace);
  }
  function sceneHTML(s){
    const current=sceneView.current[s.id]||[];
    return `<h3>${h(s.label)}</h3><code>${h(s.id)}</code><p>${s.kind==='knowledge'?'Накопленная сцена знания':'Изменяемая разговорная сцена'}</p>
      ${s.kind==='dialogue'?'<button id="scene-select">Сделать текущим разговором</button>':''}
      <button id="scene-object-new">Добавить объект</button><button id="scene-link-new">Связать со сценой</button>
      <details><summary>Объекты (${s.objects.length})</summary>${s.objects.map(o=>`<p>${h(o.label)} · объект <code>${h(o.id)}</code><br>Позиция шаблона: ${h(name(o.conceptId))} · <code>${h(o.conceptId)}</code><br>Содержательный концепт: ${o.contentConceptId?`${h(name(o.contentConceptId))} · <code data-content-concept="${h(o.contentConceptId)}">${h(o.contentConceptId)}</code>`:'не задан (содержательная идентичность не установлена)'}</p>`).join('')}</details>
      <p>Накопленные ссылки (доступность): ${s.links.map(id=>`<button data-scene-link="${h(id)}">${h(lab().scenes.find(s=>s.id===id)?.label||id)}</button>`).join(' ')||'нет'}</p>
      <form id="scene-input-form"><h4>Структурированный вход</h4><label>Назначение<select id="scene-input-kind"><option value="state">Сведения / текущее состояние</option><option value="event">Событие</option>${s.kind==='dialogue'?'<option value="context">Выбор контекста по обозначению сцены</option>':''}</select></label>
      <label>Текст входа<input id="scene-input-text" required placeholder="Например: Винт лежит на столе"></label>
      <div id="scene-input-context" hidden><label>Сцена действующего контекста<select id="scene-context-target"><option value="">Найти по точному обозначению текста</option>${lab().scenes.filter(v=>v.kind==='knowledge').map(v=>opt(v.id,title(v))).join('')}</select></label><p>Для фразы «Теперь обсуждаем химию» вручную выберите сцену «Химия». Текст не разбирается автоматически.</p></div><div id="scene-input-structure"><p>Заполнения связывают конкретные объекты через отношение каркаса. Одинаковый непустой слот заменяет прежнее состояние того же объекта; слот назначает оператор.</p>
      <div id="scene-input-rows"></div><button type="button" id="scene-row-new">Ещё заполнение</button>
      <fieldset><legend>Явно снять текущее утверждение</legend>${current.map(f=>`<label class="checkbox"><input name="retract" type="checkbox" value="${h(f.id)}">${h(factText(s,f))} · ${h(f.id)}</label>`).join('')||'<p>Текущих утверждений нет.</p>'}</fieldset></div>
      <button type="submit">Сохранить вход</button></form>
      <h4>Вычисленное текущее состояние (${current.length})</h4><div id="scene-current-facts">${current.map(f=>`<p>${h(factText(s,f))}<br>Слот: ${h(f.slot||'не задан')} · <code>${h(f.id)}</code></p>`).join('')||'<p>Нет текущих утверждений.</p>'}</div>
      <h4>Последовательность входов (${s.entries.length})</h4><div id="scene-history">${s.entries.map((e,i)=>`<details><summary>${i+1}. [${h(e.kind)}] ${h(e.text)}</summary><code>${h(e.id)}</code>${e.assertions.map(f=>`<p>${h(factText(s,f))}<br><code>${h(f.id)}</code></p>`).join('')}<p>Сняты: ${h(e.retracts.join(', ')||'нет')}</p>${e.contextSceneId?`<p>Контекст: ${h(e.contextSceneId)}</p>`:''}<pre>${h(JSON.stringify(e,null,2))}</pre></details>`).join('')}</div>`;
  }
  function bindScene(s){
    if($('#scene-select'))$('#scene-select').onclick=run(()=>call('scene_select',{sceneId:s.id}));
    $('#scene-object-new').onclick=run(()=>dialog('Объект сцены',`<label>Обозначение объекта<input name="label" required></label><label>Концепт позиции шаблона<select name="conceptId">${state.nodes.map(n=>opt(n.id,name(n.id)+' · '+n.id)).join('')}</select></label><label>Содержательный концепт<select name="contentConceptId"><option value="">Не задан</option>${state.nodes.map(n=>opt(n.id,name(n.id)+' · '+n.id)).join('')}</select></label><p>Общий содержательный ID повторно используется между сценами; локальные объекты остаются разными. Привязку задаёт оператор, она не означает наследования или автоматического вывода.</p><p>Для другого конкретного объекта создайте новый ID. Для продолжения сообщения выбирайте прежний объект.</p>`,f=>call('scene_object',{sceneId:s.id,label:f.get('label'),conceptId:f.get('conceptId'),...(f.get('contentConceptId')?{contentConceptId:f.get('contentConceptId')}:{})})));
    $('#scene-link-new').onclick=run(()=>dialog('Ссылка на накопленную или составную сцену',`<label>Сцена<select name="targetId">${lab().scenes.filter(v=>v.id!==s.id).map(v=>opt(v.id,title(v))).join('')}</select></label>`,f=>call('scene_link',{sceneId:s.id,targetId:f.get('targetId')})));
    document.querySelectorAll('[data-scene-link]').forEach(b=>b.onclick=()=>{sceneId=b.dataset.sceneLink;render();});
    $('#scene-input-kind').onchange=()=>{const isContext=$('#scene-input-kind').value==='context';$('#scene-input-structure').hidden=isContext;$('#scene-input-context').hidden=!isContext;};
    $('#scene-row-new').onclick=()=>addRow(s);
    addRow(s);
    $('#scene-input-form').onsubmit=run(async e=>{
      e.preventDefault();const kind=$('#scene-input-kind').value,text=$('#scene-input-text').value;
      if(kind==='context'){await call('scene_context',{sceneId:s.id,text,...($('#scene-context-target').value?{contextSceneId:$('#scene-context-target').value}:{})});return;}
      const assertions=[...document.querySelectorAll('.scene-input-row')].filter(row=>row.querySelector('[data-edge]').value).map(row=>({edgeId:row.querySelector('[data-edge]').value,from:row.querySelector('[data-from]').value,to:row.querySelector('[data-to]').value,slot:row.querySelector('[data-slot]').value}));
      const retracts=[...document.querySelectorAll('[name=retract]:checked')].map(v=>v.value);
      await call('scene_input',{sceneId:s.id,text,kind,assertions,retracts});
    });
  }
  function addRow(s){
    const row=document.createElement('fieldset');row.className='scene-input-row';
    row.innerHTML=`<label>Отношение каркаса<select data-edge><option value="">Без заполнения</option>${state.edges.filter(e=>e.role==='relation').map(e=>opt(e.id,`${e.type||'Отношение'} · ${name(e.from)} → ${name(e.to)} · ${e.id}`)).join('')}</select></label><div class="scene-toolbar"><label>От объекта<select data-from></select></label><label>К объекту<select data-to></select></label><label>Слот замены<input data-slot placeholder="Например: положение"></label><button data-remove type="button">Убрать</button></div>`;
    const refresh=()=>{const edge=state.edges.find(e=>e.id===row.querySelector('[data-edge]').value);for(const end of ['from','to'])row.querySelector('[data-'+end+']').innerHTML=s.objects.filter(o=>o.conceptId===edge?.[end]).map(o=>opt(o.id,o.label+' · '+o.id)).join('');};
    row.querySelector('[data-edge]').onchange=refresh;row.querySelector('[data-remove]').onclick=()=>row.remove();$('#scene-input-rows').append(row);refresh();
  }
  function newScene(){
    dialog('Создать сцену','<label>Обозначение<input name="label" required></label><label>Назначение<select name="kind"><option value="knowledge">Накопленное знание</option><option value="dialogue">Разговор</option></select></label>',async f=>{sceneId=(await call('scene_create',{label:f.get('label'),kind:f.get('kind')})).sceneId;render();});
  }
  function workspaceHTML(w,current){
    const active=new Set(sceneView.contextSources[current.id]||[]),allowed=new Set([current.id,...(sceneView.reachable[current.id]||[])]),sources=lab().scenes.filter(s=>allowed.has(s.id));
    if(!sources.some(s=>s.id===sourceId))sourceId=sources[0]?.id;
    const source=sources.find(s=>s.id===sourceId),available=new Set(sceneView.available[sourceId]||[]);
    return `<h4>${h(w.label)}</h4><code>${h(w.id)}</code><label>Источник извлечения<select id="scene-extract-source"><optgroup label="Текущий разговор">${opt(current.id,title(current))}</optgroup><optgroup label="Действующий контекст">${sources.filter(s=>s.id!==current.id&&active.has(s.id)).map(s=>opt(s.id,title(s))).join('')}</optgroup><optgroup label="Другие доступные источники вне контекста">${sources.filter(s=>s.id!==current.id&&!active.has(s.id)).map(s=>opt(s.id,title(s))).join('')}</optgroup></select></label><p id="scene-extract-scope">${sourceId===current.id?'Источник — текущий разговор':active.has(sourceId)?'Источник входит в действующий контекст':'Источник доступен по накопленной ссылке, но вне действующего контекста'}</p>
      <form id="scene-extract-form"><fieldset><legend>Явный выбор заполнений</legend>${source?source.entries.flatMap(e=>e.assertions.filter(f=>available.has(f.id)).map(f=>`<label class="checkbox"><input name="extract" type="checkbox" value="${h(f.id)}">[${h(e.kind)}] ${h(factText(source,f))}<code>${h(f.id)}</code></label>`)).join(''):''}</fieldset><button type="submit">Извлечь независимую копию</button></form>
      <p>Извлечений: ${w.bundles.length}. Предел области: 200 заполнений. Изменения источника не обновляют копии; повторное извлечение создаёт новые ID.</p><button id="scene-reset">Сбросить локальную активацию</button>
      <div id="scene-working-copies">${w.bundles.map(b=>`<section class="scene-bundle"><h4>Источник: ${h(lab().scenes.find(s=>s.id===b.sourceSceneId)?.label)} · версия #${b.sourceRevision}</h4><code>${h(b.id)}</code><p>${active.has(b.sourceSceneId)?'Источник входит в действующий контекст':b.sourceSceneId===current.id?'Источник — текущий разговор':'Источник вне действующего контекста; копия сохранена'}</p><p>Содержательные привязки: ${b.objects.filter(o=>o.contentConceptId).map(o=>`${h(o.label)} → ${h(name(o.contentConceptId))} · <code>${h(o.contentConceptId)}</code>`).join('; ')||'не заданы'}</p>
      ${b.assertions.map(f=>`<div class="scene-working-fact"><strong>${h(b.objects.find(o=>o.id===f.from)?.label)} — ${h(f.template.type||f.edgeId)} → ${h(b.objects.find(o=>o.id===f.to)?.label)}</strong><p>Состояние: <b data-activation="${h(f.id)}">${h(f.activation)}</b> · <code>${h(f.id)}</code></p><p>Происхождение: сцена ${h(f.origin.sceneId)}, вход ${h(f.origin.entryId)}, утверждение ${h(f.origin.assertionId)}, версия #${f.origin.revision}</p>${f.activation==='inactive'?`<button data-scene-seed="${h(f.id)}">Задать seed вручную</button>`:''}${(sceneView.continuations[w.id]||[]).filter(c=>c.to===f.id).map(c=>`<button data-scene-step="${h(f.id)}" data-from="${h(c.from)}" data-context="${h(c.contextId)}">Шаг по ${h(c.contextId)} от ${h(c.from)}</button>`).join('')}</div>`).join('')}
      <details><summary>Копии объектов, α и разрешений</summary><pre>${h(JSON.stringify(b,null,2))}</pre></details></section>`).join('')||'<p>Рабочая область пуста. Выбор контекста ничего не загружает автоматически.</p>'}</div>
      <details><summary>Локальный журнал (${w.trace.length})</summary><pre>${h(JSON.stringify(w.trace,null,2))}</pre></details>`;
  }
  function bindWorkspace(w){
    $('#scene-extract-source').value=sourceId;$('#scene-extract-source').onchange=e=>{sourceId=e.target.value;render();};
    $('#scene-extract-form').onsubmit=run(async e=>{e.preventDefault();await call('scene_extract',{workspaceId:w.id,sourceSceneId:sourceId,assertionIds:[...document.querySelectorAll('[name=extract]:checked')].map(v=>v.value)});});
    $('#scene-reset').onclick=run(()=>call('scene_reset',{workspaceId:w.id}));
    document.querySelectorAll('[data-scene-seed]').forEach(b=>b.onclick=run(()=>call('scene_seed',{workspaceId:w.id,assertionId:b.dataset.sceneSeed})));
    document.querySelectorAll('[data-scene-step]').forEach(b=>b.onclick=run(()=>call('scene_step',{workspaceId:w.id,assertionId:b.dataset.sceneStep,fromId:b.dataset.from,contextId:b.dataset.context})));
  }
  return {render};
})();
