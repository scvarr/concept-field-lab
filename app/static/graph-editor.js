'use strict';
// One graph editor with explicit transaction previews.
const graphEditor={
  options(rows,current,label){return rows.map(v=>`<option value="${h(v.id)}" ${v.id===current?'selected':''}>${h(label(v))} · ${h(v.id)}</option>`).join('');},
  nodes(current){return this.options(state.nodes,current,n=>n.operatorAlias?`${n.operatorAlias} (рабочий alias)`:name(n.id));},
  async preview(operations,afterApply,{compactLabel}={}){
    const payload={operations},p=await api('/api/graph-preview',payload);
    $('#toast').hidden=true;
    const describe=(key,v)=>{
      if(!v)return '<em>Отсутствует</em>';
      const ids=rows=>(rows||[]).map(id=>`<code>${h(id)}</code>`).join(', ')||'нет';
      if(key==='nodes')return `<p>${v.structure==='alpha'?'α':'Концепт'} · ${h(name(v.id))}</p><p>${h(v.kind)}<br>${h(v.notes)}</p>`;
      if(key==='edges')return `<p>${v.role==='component'?'Обязательный компонент α':'Обычное отношение'}</p><p>${h(name(v.from))} → ${h(name(v.to))}</p><p><code>${h(v.from)}</code> → <code>${h(v.to)}</code></p><p>${h(v.type)} ${h(v.notes)}</p>`;
      if(key==='contextEdges')return `<p>Контекст: <code>${h(v.from)}</code> → <code>${h(v.to)}</code></p>`;
      if(key==='designations')return `<p>${h(v.text)} → ${h(name(v.target))}</p><code>${h(v.target)}</code>`;
    };
    const rows=(key,title)=>p[key].length?`<h3>${title} (${p[key].length})</h3>${p[key].map(v=>`<article class="graph-change"><p><strong>${v.before?v.after?'Изменение':'Удаление':'Создание'}</strong> · <code>${h(v.id)}</code></p><div class="graph-change-columns"><section><strong>До</strong>${describe(key,v.before)}</section><section><strong>После</strong>${describe(key,v.after)}</section></div><details><summary>Точные данные и происхождение</summary><pre>${h(JSON.stringify({до:v.before,после:v.after},null,2))}</pre></details></article>`).join('')}`:'';
    dialog('Предварительный результат общего графа',`<p>Версия ${p.revision}. Применение атомарно; полная предыдущая версия остаётся в истории.</p>${rows('nodes','Концепты / α')}${rows('edges','Обычные отношения / обязательные компоненты α')}${rows('contextEdges','Контекстные пары')}${rows('designations','Внешние обозначения')}<h3>Контекст затронутых рёбер (ID сохраняются)</h3><pre>${h(JSON.stringify(p.affectedContexts,null,2))}</pre><label class="checkbox"><input type="checkbox" name="confirmed" required>Я просмотрел все изменения и подтверждаю их</label>`,async()=>{await mutate('graph_apply',{...payload,confirmed:true,previewRevision:p.revision});toast('Общий граф обновлён. Предыдущая версия доступна в истории.');if(afterApply){await afterApply();return false;}},'Применить изменения');
    const simple=operations.every(o=>o.op==='put')&&!p.affectedContexts.length&&p.nodes.every(v=>v.after?.structure==='concept')&&p.edges.every(v=>v.after?.role==='relation')&&!p.contextEdges.length;
    if(simple&&(compactLabel||[...p.nodes,...p.edges,...p.designations].every(v=>!v.before))){
      const form=$('#modal-form'),actions=form.querySelector('.dialog-actions'),confirm=form.querySelector('[name=confirmed]');confirm.checked=true;confirm.required=false;confirm.closest('label').hidden=true;
      const details=document.createElement('details');details.className='compact-preview-details';details.innerHTML='<summary>Подробности</summary>';for(const child of [...form.children])if(child!==actions&&child!==confirm.closest('label'))details.append(child);form.prepend(details);
      const names=new Map([...state.nodes,...p.nodes.map(v=>v.after)].map(n=>[n.id,n.operatorAlias||name(n.id)])),edge=p.edges[0]?.after;
      const heading=document.createElement('h3');heading.textContent=compactLabel||(edge?'Создать: '+names.get(edge.from)+' → '+names.get(edge.to):'Создать: '+p.nodes.map(v=>names.get(v.id)).join(', '));form.prepend(heading);
      const counts=document.createElement('p');counts.textContent=p.nodes.length+' концепта · '+p.edges.length+' обычное ребро';heading.after(counts);actions.querySelector('[type=submit]').textContent='Подтвердить';
    }
  },
  home(){
    dialog('Редактор постоянного графа',`<div class="actions"><button type="button" id="edit-choose-region">Выбрать узлы области…</button><button type="button" id="edit-create-node">Создать концепт / α</button><button type="button" id="edit-create-edge">Создать отношение / компонент α</button><button type="button" id="edit-create-context">Создать контекстную пару</button></div><label>Объект<select id="edit-object">${this.nodes(selected)}</select></label><div class="actions"><button type="button" id="edit-node">Изменить выбранный ID</button><button type="button" id="edit-uses">Использования / преобразование</button></div><h3>Рёбра и контекст по ID</h3><label>ID<input id="edit-exact-id"></label><button type="button" id="edit-exact">Открыть объект</button>`);
    $('#edit-choose-region').onclick=()=>this.chooseRegion();
    $('#edit-create-node').onclick=run(()=>this.node());$('#edit-create-edge').onclick=run(()=>this.edge());$('#edit-create-context').onclick=run(()=>this.edge(null,true));
    $('#edit-node').onclick=run(()=>this.node($('#edit-object').value));$('#edit-uses').onclick=run(()=>this.uses($('#edit-object').value));
    $('#edit-exact').onclick=run(()=>{const id=$('#edit-exact-id').value.trim();if(state.nodes.some(n=>n.id===id))return this.node(id);if(state.edges.some(e=>e.id===id))return this.edge(id);if(state.contextEdges.some(c=>c.id===id))return this.edge(id,true);throw Error('ID не найден.');});
  },
  async node(id,{afterApply}={}){
    const old=state.nodes.find(n=>n.id===id),n=old||{id:crypto.randomUUID(),label:'',designationOnly:true,structure:'concept',kind:'',notes:'',x:0,y:0};
    const components=state.edges.filter(e=>e.role==='component'&&e.from===n.id);
    dialog(old?'Общий концепт / α':'Новый общий концепт / α',`<p><code>${h(n.id)}</code></p><label>Структура<select name="structure"><option value="concept" ${n.structure==='concept'?'selected':''}>Концепт</option><option value="alpha" ${n.structure==='alpha'?'selected':''}>α</option></select></label>${old?'':`<label>Первоначальное внешнее обозначение (необязательно)<input name="designation"></label>`}<label>Характеристика<input name="kind" maxlength="1000" value="${h(n.kind)}"></label><label>Примечание<textarea name="notes">${h(n.notes)}</textarea></label><details ${n.structure==='alpha'?'open':''}><summary>Обязательные компоненты α</summary><p>Для α выберите хотя бы один компонент. Переход в концепт требует снять все компоненты.</p>${state.nodes.filter(v=>v.id!==n.id).map(v=>`<label class="checkbox"><input name="component" type="checkbox" value="${h(v.id)}" ${components.some(e=>e.to===v.id)?'checked':''}>${h(name(v.id))} · <code>${h(v.id)}</code></label>`).join('')}</details>${old?'<button type="button" id="edit-delete">Удалить ID…</button><button type="button" id="edit-node-uses">Все использования / преобразование…</button><button type="button" id="edit-aliases">Обозначения…</button>':''}`,async f=>{
      const operations=[{op:'put',collection:'nodes',value:{...n,structure:f.get('structure'),kind:f.get('kind'),notes:f.get('notes')}}],targets=f.getAll('component');
      for(const e of components)if(!targets.includes(e.to))operations.push({op:'delete',collection:'edges',id:e.id});
      for(const target of targets)if(!components.some(e=>e.to===target))operations.push({op:'put',collection:'edges',value:{id:crypto.randomUUID(),from:n.id,to:target,role:'component',type:'',notes:''}});
      if(!old&&f.get('designation').trim())operations.push({op:'put',collection:'designations',value:{id:crypto.randomUUID(),target:n.id,text:f.get('designation').trim(),notes:'',source:'Редактор графа'}});
      await this.preview(operations,afterApply?()=>afterApply(n.id):null);return false;
    },'Предпросмотр');
    $('#modal-form [name=structure]').onchange=e=>{$('#modal-form details').open=e.target.value==='alpha'||!!$('#modal-form [name=component]:checked');};
    if(old){$('#edit-delete').onclick=run(()=>this.removeNode(id));$('#edit-node-uses').onclick=run(()=>this.uses(id));$('#edit-aliases').onclick=()=>openNode(id);}
  },
  async removeNode(id){return Management.remove(['node:'+id]);},
  async edge(id,context=false,{afterApply}={}){
    const key=context?'contextEdges':'edges',old=state[key].find(e=>e.id===id),e=old||{id:crypto.randomUUID(),role:'relation',from:'',to:'',type:'',notes:''};
    const options=current=>context?this.options(state.edges.filter(e=>e.role==='relation'),current,edgeName):this.nodes(current);
    dialog(context?'Общая контекстная пара':'Общее ребро / компонент α',`<p><code>${h(e.id)}</code></p><label>От<select name="from">${options(e.from)}</select></label><label>К<select name="to">${options(e.to)}</select></label>${context?'':`<label>Функция<select name="role"><option value="relation" ${e.role==='relation'?'selected':''}>Обычное отношение</option><option value="component" ${e.role==='component'?'selected':''}>Обязательный компонент α</option></select></label><label>Обоснование нового параллельного отношения<input name="parallelReason" value="${h(e.parallelReason)}"></label><label>Тип<input name="type" value="${h(e.type)}"></label><label>Примечание<textarea name="notes">${h(e.notes)}</textarea></label>`}${old?'<button type="button" id="edit-delete">Удалить связь…</button>':''}`,async f=>{const value={...e,from:f.get('from'),to:f.get('to')};if(!context)Object.assign(value,{role:f.get('role'),type:f.get('type'),notes:f.get('notes'),parallelReason:f.get('parallelReason')});await this.preview([{op:'put',collection:key,value}],afterApply?()=>afterApply(e.id):null);return false;},'Предпросмотр');
    if(old)$('#edit-delete').onclick=run(()=>Management.remove([(context?'context:':'edge:')+id]));
  },
  uses(id){
    const structural=new Set([id]),parents=new Map();for(const e of state.edges)if(e.role==='component'){if(!parents.has(e.to))parents.set(e.to,[]);parents.get(e.to).push(e.from);}const pending=[id];while(pending.length)for(const parent of parents.get(pending.pop())||[])if(!structural.has(parent)){structural.add(parent);pending.push(parent);}
    const edges=state.edges.filter(e=>e.from===id||e.to===id),edgeIds=new Set(edges.map(e=>e.id)),aliases=state.designations.filter(d=>d.target===id),indirect=state.edges.filter(e=>!edgeIds.has(e.id)&&(structural.has(e.from)||structural.has(e.to))),reviewEdges=new Set([...edgeIds,...indirect.map(e=>e.id)]),contexts=state.contextEdges.filter(c=>reviewEdges.has(c.from)||reviewEdges.has(c.to));
    dialog('Все использования и преобразование концепта',`<p>${h(name(id))} · <code>${h(id)}</code></p><p>Оператор выбирает соответствие и каждое использование. Структуру вокруг целевого ID можно предварительно построить в графе или группе концептов.</p><label>Целевой существующий ID<select name="target">${this.options(state.nodes.filter(n=>n.id!==id),null,n=>name(n.id))}</select></label><h3>Выберите концы отношений / компонентов α</h3>${edges.flatMap(e=>['from','to'].filter(end=>e[end]===id).map(end=>`<label class="checkbox"><input type="checkbox" name="use" value="${h(e.id)}|${end}">${h(edgeName(e))} · ${end} · ${e.role==='component'?'компонент α':'отношение'}</label>`)).join('')||'<p>Рёбер нет</p>'}<h3>Перепривязать обозначения с сохранением их ID</h3>${aliases.map(d=>`<label class="checkbox"><input type="checkbox" name="designation" value="${h(d.id)}">${h(d.text)} · <code>${h(d.id)}</code></label>`).join('')||'<p>Нет</p>'}<h3>Зависимости через обязательный состав α</h3>${[...structural].filter(n=>n!==id).map(n=>`<p>${h(name(n))} · <code>${h(n)}</code></p>`).join('')||'<p>Нет</p>'}${indirect.map(e=>`<p>Для просмотра: ${h(edgeName(e))}</p>`).join('')}<p>Эти родительские ID и их отношения не перенаправляются автоматически.</p><h3>Контекстные пары затронутых рёбер</h3>${contexts.map(c=>`<p><code>${h(c.id)}</code>: ${h(c.from)} → ${h(c.to)}</p>`).join('')||'<p>Нет</p>'}<label class="checkbox"><input type="checkbox" name="deleteSource">Удалить исходный концепт, если не осталось зависимостей</label>`,async f=>{await this.preview([{op:'redirect',source:id,target:f.get('target'),uses:f.getAll('use').map(v=>{const at=v.lastIndexOf('|');return {id:v.slice(0,at),end:v.slice(at+1)};}),designationIds:f.getAll('designation'),deleteSource:f.has('deleteSource')}]);return false;},'Предпросмотр преобразования');
  },
  bulk(ids){
    const nodes=state.nodes.filter(n=>ids.includes(n.id));if(!nodes.length)return this.node();
    dialog('Изменить группу постоянных концептов',`<p>Правка общих объектов без создания определения. Перед записью — preview общего редактора.</p>${nodes.map((n,i)=>`<fieldset><legend>${h(n.operatorAlias||name(n.id))} · ${h(n.id)}</legend><label>Рабочий alias<input name="alias-${i}" value="${h(n.operatorAlias||'')}"></label><label>Примечание<textarea name="notes-${i}">${h(n.notes)}</textarea></label></fieldset>`).join('')}`,async f=>{await this.preview(nodes.map((n,i)=>({op:'put',collection:'nodes',value:{...n,operatorAlias:f.get('alias-'+i),notes:f.get('notes-'+i)}})));return false;},'Предпросмотр');
  },
  chooseRegion(){
    const chosen=new Set(neighbourhoodIds());
    dialog('Выбрать область общего графа',`<p>До 80 узлов / 160 рёбер / 800 контекстных пар. Внутренние рёбра и пары выбираются по существующим ID. Группа изменяется в общем редакторе.</p><label>Поиск<input id="region-search" type="search"></label><div id="region-choices">${state.nodes.map(n=>`<label class="checkbox" data-region-label="${h((name(n.id)+' '+n.id).toLocaleLowerCase('ru'))}"><input type="checkbox" name="region-node" value="${h(n.id)}" ${chosen.has(n.id)?'checked':''}>${h(name(n.id))} · <code>${h(n.id)}</code></label>`).join('')}</div>`,async f=>{await this.region(f.getAll('region-node'));},'Открыть область');
    $('#region-search').oninput=e=>{const q=e.target.value.toLocaleLowerCase('ru');for(const row of document.querySelectorAll('[data-region-label]'))row.hidden=!row.dataset.regionLabel.includes(q);};
  },
  async region(ids){return this.bulk(ids);}
};
$('#graph-editor').onclick=run(()=>graphEditor.home());$('#graph-region').onclick=run(()=>graphEditor.region(neighbourhoodIds()));
