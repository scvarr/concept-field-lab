'use strict';
window.DefinitionBuilder = class {
  constructor(ctx) { this.ctx=ctx;this.host=document.querySelector('#builder');this.route=[];this.ids=false;this.query='';this.sequence=0; }
  h(v) { return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
  canvas() { return this.ctx.permanent?this.ctx.study():(this.ctx.study()?.accumulation?this.ctx.study():null); }
  metadata() { return this.ctx.permanent?this.canvas():this.canvas()?.accumulation; }
  drafts() { return this.metadata()?.definitionDrafts||[]; }
  name(id) { const n=this.draft?.nodes.find(n=>n.id===id),s=this.canvas();if(this.ctx.permanent)return this.aliases(id)[0]?.text||id;return n?.designation||s?.designations?.find(d=>d.target===id)?.text||s?.nodes.find(n=>n.id===id)?.label||id; }
  aliases(id) {
    if(this.canvas()?.nodes.some(n=>n.id===id))return this.canvas().designations.filter(d=>d.target===id);
    const n=this.draft?.nodes.find(n=>n.id===id);if(!n)return [];
    if(!n.designations)n.designations=n.designation?[{id:crypto.randomUUID(),text:n.designation}]:[];
    return n.designations;
  }
  sourceSummary(d) { const s=d.lexicalSource;return s?`${s.name} · ${s.entry||s.lemma||''} · значение ${s.senseId||'не указано'} · revision ${s.revision||'не указана'}`:d.source||'Ручное обозначение · словарное значение не указано'; }
  aliasFields(id) { return `<div class="field-aliases"><span>Словарные обозначения · точки входа</span>${this.aliases(id).map(d=>`<div class="alias-row"><strong>${this.h(d.text)}</strong><code>${this.h(d.id)}</code><small>${this.h(this.sourceSummary(d))}</small><button data-alias-edit="${this.h(d.id)}" data-alias-node="${this.h(id)}">Изменить</button><button data-alias-remove="${this.h(d.id)}" data-alias-node="${this.h(id)}">Удалить</button></div>`).join('')||'<p>Обозначений нет. Концепт доступен по ID.</p>'}<button data-alias-add="${this.h(id)}">Добавить обозначение</button></div>`; }
  editAlias(id,aliasId) {
    this.capture();const original=this.aliases(id).find(d=>d.id===aliasId),h=v=>this.h(v);let source=structuredClone(original?.lexicalSource||null),request=0;
    this.ctx.dialog('Словарное обозначение точки входа',`<p>Концепт <code>${h(id)}</code>. Обозначение не устанавливает синонимичность и не меняет рёбра.</p><label>Слово / словарная форма<input name="text" required maxlength="1000" value="${h(original?.text)}"></label><label>Примечание<input name="notes" value="${h(original?.notes)}"></label><button type="button" id="alias-senses">Получить значения слова</button><div id="alias-meanings"></div><details open><summary>Необязательный источник значения</summary><label>Источник<input name="sourceName" value="${h(source?.name)}"></label><label>Словарная статья / омоним<input name="entry" value="${h(source?.entry)}"></label><label>Номер значения<input name="senseId" value="${h(source?.senseId)}"></label><label>Редакция<input name="revision" value="${h(source?.revision)}"></label><label>Ссылка на редакцию<input name="revisionUrl" value="${h(source?.revisionUrl)}"></label><button type="button" id="alias-clear-source">Убрать источник значения</button></details>`,async f=>{
      const text=f.get('text').trim(),name=f.get('sourceName').trim();
      const lexicalSource=name?{...source,name,lemma:source?.lemma||text,entry:f.get('entry'),senseId:f.get('senseId'),revision:f.get('revision'),revisionUrl:f.get('revisionUrl')}:null;
      const value={id:aliasId||crypto.randomUUID(),text,notes:f.get('notes'),lexicalSource};
      if(this.canvas().nodes.some(n=>n.id===id)){await this.save();await this.ctx.mutate('designation_save',{nodeId:id,designationId:aliasId,text,notes:value.notes,lexicalSource});}
      else{const rows=this.aliases(id),old=rows.find(d=>d.id===aliasId);if(old)Object.assign(old,value);else rows.push(value);await this.save();}
    });
    const form=document.querySelector('#modal-form'),fill=s=>{source=s;for(const [field,key] of [['sourceName','name'],['entry','entry'],['senseId','senseId'],['revision','revision'],['revisionUrl','revisionUrl']])form.elements[field].value=s?.[key]??'';};
    form.querySelector('#alias-clear-source').onclick=()=>fill(null);
    form.querySelector('#alias-senses').onclick=this.ctx.run(async()=>{
      const sequence=++request,lemma=form.elements.text.value.trim(),host=form.querySelector('#alias-meanings');host.textContent='Получение значений…';
      const result=await this.ctx.api('/api/definitions?'+new URLSearchParams({lemma}));if(sequence!==request||!form.isConnected)return;
      host.innerHTML=`<p>${h(result.message)}</p>${result.senses.map((s,i)=>`<article class="sense"><strong>${h(s.entry)} · значение ${h(s.id)}</strong><p>${h(s.text)}</p><small>${h(s.source.name)} · revision ${h(s.source.revision)} · ${h(s.source.license)}</small><button type="button" data-alias-sense="${i}">Связать с этим значением</button></article>`).join('')}`;
      host.querySelectorAll('[data-alias-sense]').forEach(b=>b.onclick=()=>{const sense=result.senses[Number(b.dataset.aliasSense)];fill({...sense.source,lemma,senseId:sense.id,entry:sense.entry,originalText:sense.text});});
    });
  }
  removeAlias(id,aliasId) {
    this.capture();const value=this.aliases(id).find(d=>d.id===aliasId);
    this.ctx.dialog('Удалить отдельное соответствие',`<p>${this.h(value.text)} → <code>${this.h(id)}</code></p><p>Концепт, остальные обозначения, обычные и контекстные рёбра сохранятся. Последнее обозначение тоже можно удалить: останется ID.</p>`,async()=>{
      if(this.canvas().nodes.some(n=>n.id===id)){await this.save();await this.ctx.mutate('designation_remove',{designationId:aliasId});}
      else{const n=this.draft.nodes.find(n=>n.id===id);n.designations=this.aliases(id).filter(d=>d.id!==aliasId);await this.save();}
    },'Удалить соответствие');
  }
  edgeName(id) { const e=this.draft?.edges.find(e=>e.id===id);return e?`${this.name(e.from)} → ${this.name(e.to)} · ${id}`:id; }
  capture() {
    if(!this.draft)return;
    const active=!this.ctx.permanent||document.querySelector('#dialog')?.open;
    const title=active?(this.ctx.permanent?document.querySelector('#modal-form #def-title'):this.host.querySelector('#def-title')):null,definition=active?(this.ctx.permanent?document.querySelector('#modal-form #def-text'):this.host.querySelector('#def-text')):null;
    if(title){this.draft.title=title.value;this.draft.definition=definition.value;if(this.draft.source)this.draft.source.operatorEdited=definition.value!==this.draft.source.originalText;}
  }
  async save(capture=true) { if(capture)this.capture();await this.ctx.mutate('definition_save',{studyId:this.canvas().id,draft:this.draft});this.changed=false; }
  act(fn) { return this.ctx.run(async()=>{this.capture();await fn();}); }
  render() {
    if(this.ctx.permanent)return this.renderCanvas();
    const s=this.canvas();
    if(!s){this.host.innerHTML=`<div class="intro"><h2>Конструктор определений</h2><p>Откройте существующее накопительное полотно или создайте его во вкладке «Единое полотно».</p>${this.ctx.state().studies.filter(s=>s.accumulation&&!s.archived).map(s=>`<button data-def-canvas="${this.h(s.id)}">${this.h(s.title)}</button>`).join('')}</div>`;this.host.querySelectorAll('[data-def-canvas]').forEach(b=>b.onclick=()=>{this.ctx.activate(b.dataset.defCanvas);});return;}
    if(this.canvasId!==s.id){this.draft=null;this.canvasId=s.id;this.route=[];}
    if(this.ctx.permanent&&!this.draft&&!this.drafts().length)this.draft={id:crypto.randomUUID(),title:'Новое определение',definition:'',nodes:[],edges:[],contextEdges:[],routes:[]};
    if(!this.draft&&this.drafts().length)this.draft=structuredClone(this.drafts().find(d=>d.id===this.ctx.ui().definitionDraft)||this.drafts()[0]);
    this.host.innerHTML=`${this.ctx.permanent?'':`<div class="intro"><h2>Конструктор определений · ${this.h(s.title)}</h2><p>Определение и смысловые решения вводите вручную. Словарь предлагает внешние формы; совпадение не устанавливает тождество.</p></div>`}
      <div class="toolbar"><select id="def-open" aria-label="Сохранённые определения"><option value="">Открыть черновик…</option>${this.drafts().map(d=>`<option value="${this.h(d.id)}" ${d.id===this.draft?.id?'selected':''}>${this.h(d.title)} · ${this.h(d.id)}</option>`).join('')}</select><button id="def-new">Новое определение</button><button id="def-export" ${this.ctx.permanent?'hidden':''}>Экспорт полотна с черновиками ↓</button></div><div id="def-body"></div>`;
    this.host.querySelector('#def-new').onclick=this.act(async()=>{if(this.draft)await this.save();this.draft={id:crypto.randomUUID(),title:'Новое определение',definition:'',nodes:[],edges:[],contextEdges:[],routes:[]};this.route=[];this.ctx.ui().definitionDraft=this.draft.id;await this.save(false);});
    this.host.querySelector('#def-open').onchange=this.act(async()=>{const id=this.host.querySelector('#def-open').value;if(!id)return;if(this.draft)await this.save();this.draft=structuredClone(this.drafts().find(d=>d.id===id));this.ctx.ui().definitionDraft=id;this.route=[];this.render();});
    this.host.querySelector('#def-export').onclick=this.act(async()=>{if(this.draft)await this.save();await this.ctx.download(`/api/graph-export?study=${encodeURIComponent(s.id)}`,'concept-field-definitions.json');});
    if(!this.draft)return;
    this.ctx.ui().definitionDraft=this.draft.id;this.ctx.saveUI();
    const d=this.draft,h=v=>this.h(v),nodeOptions=d.nodes.map(n=>`<option value="${h(n.id)}">${h(this.name(n.id))} · ${h(n.id)}</option>`).join(''),edgeOptions=d.edges.map(e=>`<option value="${h(e.id)}">${h(this.edgeName(e.id))}</option>`).join('');
    let sourceUrl=null;try{const url=new URL(d.source?.revisionUrl);if(url.protocol==='https:'&&url.hostname==='ru.wiktionary.org')sourceUrl=url.href;}catch{}
    this.host.querySelector('#def-body').innerHTML=`
      <div class="definition-layout"><section class="card"><label>Название<input id="def-title" value="${h(d.title)}" maxlength="1000"></label><label>Исходное определение<textarea id="def-text" rows="3" maxlength="50000" placeholder="Введите определение из выбранного источника">${h(d.definition)}</textarea></label>${d.source?`<p class="definition-source">${sourceUrl?`<a href="${h(sourceUrl)}" target="_blank" rel="noreferrer">${h(d.source.name)} · редакция ${h(d.source.revision)}</a>`:h(d.source.name)} · ${h(d.source.license)}${d.source.operatorEdited?' · текст изменён оператором':''}</p>`:''}<button id="def-save">Сохранить черновик</button><p id="def-save-hint" class="hint">Черновик в SQLite · ${h(d.id)}</p>
      <h3>Найти концепт или словарную форму</h3><input id="def-search" type="search" value="${h(this.query)}" placeholder="Лемма, часть обозначения или ID" aria-label="Поиск словаря и концептов"><div id="def-results"></div><div id="def-senses"></div><label>Обозначение нового концепта<input id="def-new-label" maxlength="1000" placeholder="Внешнее обозначение"></label><button id="def-add-node">Создать новый концепт</button></section>
      <section class="card"><div class="actions"><label class="checkbox"><input id="def-ids" type="checkbox" ${this.ids?'checked':''}>Показывать ID вместо слов</label><button id="def-fit">Вписать миниграф</button></div><div id="def-graph" class="graph" aria-label="Миниграф определения"></div><p>Стрелки — обычные рёбра. Контекст между рёбрами показан отдельным списком ниже.</p></section></div>
      <section class="card"><h3>Поля миниграфа</h3><div class="definition-fields">${d.nodes.map(n=>`<div><strong>${h(this.name(n.id))}</strong><code>${h(n.id)}</code><span>${n.existing?(this.ctx.permanent?'Существующий ID графа':'Повторное использование ID полотна'):'Новый концепт · внешнее обозначение'}</span>${n.existing||this.ctx.permanent?'':`<input data-def-label="${h(n.id)}" value="${h(n.designation)}" aria-label="Обозначение ${h(n.id)}">`}${this.ctx.permanent?this.aliasFields(n.id):''}<button data-def-inspect="${h(n.id)}">Где используется</button><button data-def-remove-node="${h(n.id)}">Убрать поле</button></div>`).join('')}</div>
      <h3>Соединить поля</h3><div class="actions"><label>От<select id="def-from">${nodeOptions}</select></label><label>К<select id="def-to">${nodeOptions}</select></label><button id="def-connect">Соединить →</button></div><div class="definition-edge-list">${d.edges.map(e=>`<div><code>${h(e.id)}</code> ${h(this.name(e.from))} → ${h(this.name(e.to))} · ${e.existing?'существующий ID':'новое ребро'} <button data-def-route-edge="${h(e.id)}">＋ В маршрут</button><button data-def-remove-edge="${h(e.id)}">Убрать ребро</button></div>`).join('')}</div></section>
      <section class="card"><h3>Подтвердить маршрут</h3><p>Выберите последовательность кнопками «＋ В маршрут». Подтверждение предложит только пары «раньше → позже» внутри выбранной последовательности.</p><ol>${this.route.map(id=>`<li>${h(this.edgeName(id))}</li>`).join('')}</ol><div class="actions"><button id="def-route-clear">Очистить выбор</button><button id="def-route-confirm">Просмотреть и подтвердить маршрут</button></div><details><summary>Записанные маршруты (${d.routes.length})</summary>${d.routes.map(r=>`<p>${r.edgeIds.map(id=>h(this.edgeName(id))).join('<br>')}<button data-def-remove-route="${h(r.id)}">Удалить запись маршрута</button></p>`).join('')}</details>
      <h3>Направленные контекстные связи между рёбрами</h3><div class="actions"><label>От ребра<select id="def-context-from">${edgeOptions}</select></label><label>К ребру<select id="def-context-to">${edgeOptions}</select></label><button id="def-context-add">Добавить контекст →</button></div><div>${d.contextEdges.map(c=>`<div class="definition-context"><code>${h(c.id)}</code><span>${h(this.edgeName(c.from))}<br>→ ${h(this.edgeName(c.to))}</span><button data-def-context-reverse="${h(c.id)}">Развернуть</button><button data-def-context-remove="${h(c.id)}">Удалить</button></div>`).join('')}</div><p class="hint">Ручные правки меняют допустимые переходы; запись маршрута остаётся свидетельством первоначального подтверждения.</p></section>
      <section class="card"><button id="def-preview" class="primary">Просмотреть изменения для полотна</button><p>Включение — отдельное подтверждение. Повторное включение обновляет только объекты этого определения; чужие участки защищены.</p></section>`;
    this.host.querySelector('#def-save').onclick=this.act(()=>this.save());
    for(const id of ['def-title','def-text'])this.host.querySelector('#'+id).oninput=()=>{this.changed=true;this.host.querySelector('#def-save-hint').textContent='Есть несохранённый текст — сохраните черновик';};
    this.host.querySelector('#def-search').oninput=e=>{this.query=e.target.value;clearTimeout(this.searchTimer);this.searchTimer=setTimeout(()=>this.search(),180);};
    this.host.querySelector('#def-add-node').onclick=this.act(async()=>{const designation=this.host.querySelector('#def-new-label').value.trim();if(!designation)throw Error('Введите внешнее обозначение.');await this.addNew(designation);});
    this.host.querySelector('#def-ids').onchange=e=>{this.capture();this.ids=e.target.checked;this.draw();};
    this.host.querySelector('#def-fit').onclick=()=>this.graph?.fit();
    this.host.querySelectorAll('[data-def-label]').forEach(input=>input.onchange=this.act(async()=>{d.nodes.find(n=>n.id===input.dataset.defLabel).designation=input.value;await this.save();}));
    this.host.querySelectorAll('[data-alias-add]').forEach(b=>b.onclick=()=>this.editAlias(b.dataset.aliasAdd));
    this.host.querySelectorAll('[data-alias-edit]').forEach(b=>b.onclick=()=>this.editAlias(b.dataset.aliasNode,b.dataset.aliasEdit));
    this.host.querySelectorAll('[data-alias-remove]').forEach(b=>b.onclick=()=>this.removeAlias(b.dataset.aliasNode,b.dataset.aliasRemove));
    this.host.querySelectorAll('[data-def-inspect]').forEach(b=>b.onclick=()=>this.inspect(b.dataset.defInspect));
    this.host.querySelectorAll('[data-def-remove-node]').forEach(b=>b.onclick=this.act(async()=>{const id=b.dataset.defRemoveNode;d.nodes=d.nodes.filter(n=>n.id!==id);const removed=d.edges.filter(e=>e.from===id||e.to===id).map(e=>e.id);d.edges=d.edges.filter(e=>!removed.includes(e.id));this.prune(removed);await this.save();}));
    this.host.querySelector('#def-connect').onclick=this.act(()=>this.connect());
    this.host.querySelectorAll('[data-def-remove-edge]').forEach(b=>b.onclick=this.act(async()=>{const id=b.dataset.defRemoveEdge;d.edges=d.edges.filter(e=>e.id!==id);this.prune([id]);await this.save();}));
    this.host.querySelectorAll('[data-def-route-edge]').forEach(b=>b.onclick=this.act(()=>{const id=b.dataset.defRouteEdge;if(!this.route.includes(id))this.route.push(id);this.render();}));
    this.host.querySelector('#def-route-clear').onclick=this.act(()=>{this.route=[];this.render();});
    this.host.querySelector('#def-route-confirm').onclick=this.act(()=>this.confirmRoute());
    this.host.querySelectorAll('[data-def-remove-route]').forEach(b=>b.onclick=this.act(async()=>{d.routes=d.routes.filter(r=>r.id!==b.dataset.defRemoveRoute);await this.save();}));
    this.host.querySelector('#def-context-add').onclick=this.act(async()=>{this.addContext(this.host.querySelector('#def-context-from').value,this.host.querySelector('#def-context-to').value);await this.save();});
    this.host.querySelectorAll('[data-def-context-remove]').forEach(b=>b.onclick=this.act(async()=>{d.contextEdges=d.contextEdges.filter(c=>c.id!==b.dataset.defContextRemove);await this.save();}));
    this.host.querySelectorAll('[data-def-context-reverse]').forEach(b=>b.onclick=this.act(async()=>{const c=d.contextEdges.find(c=>c.id===b.dataset.defContextReverse);if(d.contextEdges.some(v=>v.from===c.to&&v.to===c.from))throw Error('Обратная пара уже записана.');[c.from,c.to]=[c.to,c.from];await this.save();}));
    this.host.querySelector('#def-preview').onclick=this.act(()=>this.preview());
    if(this.ctx.permanent){this.host.querySelector('#def-preview').textContent='Просмотреть изменения постоянного графа';}
    this.draw();if(this.query)this.ctx.run(()=>this.search())();
  }
  draw() {
    const host=this.host.querySelector('#def-graph');if(!host)return;
    const d=this.draft,snapshot=this.graphDraft===d.id?this.graph?.snapshot():null;this.graph?.observer.disconnect();this.graphDraft=d.id;
    if(!d.nodes.length){this.graph=null;host.textContent='Найдите существующий концепт или создайте первое поле.';return;}
    const nodes=d.nodes.map((n,i)=>({id:n.id,label:this.ids?n.id:this.name(n.id),x:n.x??(i%4)*245,y:n.y??Math.floor(i/4)*125,origins:[],badge:n.existing?'Повторно используется':this.ctx.permanent&&this.canvas().nodes.some(v=>v.id===n.id)?'В постоянном графе':'Новый'}));
    this.graph=new GraphView(host,{select:id=>this.ctx.permanent?this.pickObject('node',id):this.inspect(id),editNode:id=>this.ctx.permanent?this.openNode(id):this.inspect(id),editEdge:id=>this.ctx.permanent?this.pickObject('edge',id):this.ctx.dialog('Обычное ребро',`<p>${this.h(this.edgeName(id))}</p>`),editContext:this.ctx.permanent?id=>this.pickObject('context',id):undefined,contextMenu:this.ctx.permanent?(kind,id,e)=>this.objectMenu(kind,id,e):undefined,activateNode:this.ctx.permanent?id=>this.interaction?this.pickObject('node',id):this.openNode(id):undefined,savePosition:this.ctx.run(async(id,p)=>{this.capture();Object.assign(d.nodes.find(n=>n.id===id),p);await this.save();}),canInteract:()=>!this.ctx.busy(),error:e=>this.ctx.toast(e.message,true)});
    if(snapshot)this.graph.restore(snapshot);
    this.graph.update({id:d.id,rootId:nodes[0]?.id,nodes,edges:d.edges},{nodes,edges:d.edges.map(e=>({...e,type:'',highlight:this.route.includes(e.id),displayTitle:this.edgeName(e.id)})),contextEdges:this.ctx.permanent?d.contextEdges:[]},this.selectedObject?.kind==='node'?this.selectedObject.id:nodes[0]?.id);if(!snapshot)this.graph.fit();
  }
  prune(ids) { this.draft.contextEdges=this.draft.contextEdges.filter(c=>!ids.includes(c.from)&&!ids.includes(c.to));this.draft.routes=this.draft.routes.filter(r=>!r.edgeIds.some(id=>ids.includes(id)));this.route=this.route.filter(id=>!ids.includes(id)); }
  async addNew(designation,dictionaryId) { this.draft.nodes.push({id:crypto.randomUUID(),designation,existing:false,dictionaryId:dictionaryId||null,...(this.spawnPosition||{}),...(this.ctx.permanent?{designations:[{id:crypto.randomUUID(),text:designation,...(this.draft.source?.lemma===designation?{lexicalSource:structuredClone(this.draft.source)}:{})}]}:{})});this.spawnPosition=null;await this.save();if(this.ctx.permanent)this.ctx.closeDialog(); }
  async loadSenses(lemma,refresh=false) {
    const sequence=this.senseSequence=(this.senseSequence||0)+1,host=this.searchHost('#def-senses');if(!host)return;
    host.innerHTML='<p>Получение толкований… Можно продолжать ручной ввод.</p>';
    const result=await this.ctx.api('/api/definitions?'+new URLSearchParams({lemma,refresh:refresh?'1':'0'}));if(sequence!==this.senseSequence||!host.isConnected)return;
    host.innerHTML=`<h3>Словарные значения: ${this.h(lemma)}</h3><p>${this.h(result.message)}</p><button id="def-refresh-senses">Обновить толкования</button>${result.senses.map((s,i)=>`<article class="sense"><strong>${this.h(s.entry)} · значение ${this.h(s.id)}</strong><p>${this.h(s.text)}</p><small><a href="${this.h(s.source.revisionUrl)}" target="_blank" rel="noreferrer">${this.h(s.source.name)} · revision ${this.h(s.source.revision)}</a> · ${this.h(s.source.license)}</small><button data-def-sense="${i}">Взять это определение</button></article>`).join('')}<p>Толкование не добавляет концептов или рёбер. Смысловые решения — ваши.</p>`;
    host.querySelector('#def-refresh-senses').onclick=this.ctx.run(()=>this.loadSenses(lemma,true));
    host.querySelectorAll('[data-def-sense]').forEach(b=>b.onclick=this.act(async()=>{
      const sense=result.senses[Number(b.dataset.defSense)];
      if(this.draft.definition.trim()||this.draft.nodes.length){await this.save();this.draft={id:crypto.randomUUID(),nodes:[],edges:[],contextEdges:[],routes:[]};}
      Object.assign(this.draft,{title:lemma,definition:sense.text,source:{...sense.source,lemma,senseId:sense.id,entry:sense.entry,originalText:sense.text}});
      await this.ctx.mutate('definition_save',{draft:this.draft});this.changed=false;
      if(this.ctx.permanent)this.ctx.closeDialog();
    }));
  }
  async addExisting(id) { if(this.draft.nodes.some(n=>n.id===id))return this.ctx.toast('Этот ID уже выбран.');const n=this.canvas().nodes.find(n=>n.id===id);this.draft.nodes.push({id,existing:true,designation:this.canvas().designations?.find(d=>d.target===id)?.text||n.label||id,base:structuredClone(n),...(this.spawnPosition||{})});this.spawnPosition=null;await this.save();if(this.ctx.permanent)this.ctx.closeDialog(); }
  searchHost(selector) { return this.ctx.permanent?document.querySelector('#modal-form '+selector):this.host.querySelector(selector); }
  async search() {
    const seq=++this.sequence,s=this.canvas(),host=this.searchHost('#def-results');if(!s||!host)return;
    const result=await this.ctx.api('/api/dictionary?'+new URLSearchParams({q:this.query,study:s.id}));if(seq!==this.sequence||s.id!==this.canvas()?.id)return;
    if(!host.isConnected)return;this.results=result;
    host.innerHTML=`<p>${this.h(result.source.source)} · ${this.h(result.source.license)}<br>${result.wordCount} словарных вариантов; ${result.conceptCount} представлений концептов.${result.multipleConcepts?' Несколько ID — выберите по окружению.':''}</p><div class="definition-search-results">${result.concepts.map((c,i)=>`<div><strong>${this.h(c.labels.join(' / '))}</strong><span>${c.location==='permanent'?'ID постоянного графа':c.location==='canvas'?'Концепт на накопительном полотне':'Концепт исходного исследования'} · ${this.ctx.permanent?'':this.h(c.studyTitle)}${c.archived?' · архив':''}</span><code>${this.h(c.nodeId)}</code><small>${this.h((c.designations||[]).map(d=>`${d.text}: ${this.sourceSummary(d)}`).join(' · '))}</small><span>${c.edges.length} связей · ${this.h(c.kind)} · ${this.h(c.notes.slice(0,180))}</span><button data-def-result-inspect="${i}">Окружение и происхождение</button>${c.selectable?`<button data-def-use="${this.h(c.nodeId)}">Использовать этот ID</button>`:c.location==='source'?`<button data-def-source="${i}">Добавить исходник после просмотра</button>`:''}</div>`).join('')}${result.words.map((w,i)=>`<div><strong>${this.h(w.lemma)}</strong><span>Словарь ${this.h(w.id)} · ${this.h(w.grammemes.join(', '))}</span><span>${w.hasConcept?'Есть совпадения обозначений — тождество не установлено':'Слово есть в словаре; концепт с этим обозначением не найден'}</span>${this.ctx.permanent?`<button data-def-meanings="${i}">Показать толкования</button>`:''}<button data-def-word="${i}">Создать отдельный концепт</button></div>`).join('')}</div>`;
    host.querySelectorAll('button').forEach(b=>b.type='button');
    host.querySelectorAll('[data-def-use]').forEach(b=>b.onclick=this.act(()=>this.addExisting(b.dataset.defUse)));
    host.querySelectorAll('[data-def-meanings]').forEach(b=>b.onclick=this.ctx.run(()=>this.loadSenses(result.words[Number(b.dataset.defMeanings)].lemma)));
    host.querySelectorAll('[data-def-word]').forEach(b=>b.onclick=this.act(()=>{const w=result.words[Number(b.dataset.defWord)];return this.addNew(w.lemma,w.id);}));
    host.querySelectorAll('[data-def-result-inspect]').forEach(b=>b.onclick=()=>this.showUsage(result.concepts[Number(b.dataset.defResultInspect)]));
    if(this.ctx.permanent){const word=result.words.find(w=>w.lemma.toLocaleLowerCase('ru').replaceAll('ё','е')===this.query.toLocaleLowerCase('ru').replaceAll('ё','е'));if(word)this.ctx.run(()=>this.loadSenses(word.lemma))();else{this.senseSequence=(this.senseSequence||0)+1;const senses=this.searchHost('#def-senses');if(senses)senses.innerHTML='';}}
    host.querySelectorAll('[data-def-source]').forEach(b=>b.onclick=this.act(()=>this.includeSource(result.concepts[Number(b.dataset.defSource)])));
  }
  inspect(id) {
    const c=this.canvas(),n=c.nodes.find(n=>n.id===id);if(!n)return this.ctx.dialog('Новое поле',`<p>${this.h(this.name(id))} · ${this.h(id)}</p><p>Ещё не включено на полотно.</p>`);
    this.showUsage({nodeId:id,studyTitle:c.title,labels:[this.name(id)],designations:c.designations.filter(d=>d.target===id),origins:n.origins,definitions:Object.entries((this.ctx.permanent?c:c.accumulation).definitionPublications||{}).filter(([,p])=>p.nodeIds.includes(id)).map(([id,p])=>({id,...p})),edges:c.edges.filter(e=>e.from===id||e.to===id),contexts:((this.ctx.permanent?c:c.accumulation.manual)?.contextEdges||[]).filter(v=>c.edges.some(e=>(e.from===id||e.to===id)&&(v.from===e.id||v.to===e.id)))});
  }
  showUsage(c) { this.ctx.dialog('Использование концепта',`<p>${this.h(c.labels.join(' / '))} · ${this.h(c.nodeId)} · ${this.ctx.permanent?'':this.h(c.studyTitle)}</p><h3>Словарные обозначения и значения</h3><pre>${this.h(JSON.stringify(c.designations||[],null,2))}</pre><h3>Подтверждённые определения</h3><pre>${this.h(JSON.stringify(c.definitions||[],null,2))}</pre><h3>Существующие связи</h3><pre>${this.h(JSON.stringify(c.edges,null,2))}</pre><h3>Контекст между рёбрами</h3><pre>${this.h(JSON.stringify(c.contexts||[],null,2))}</pre><h3>Происхождение</h3><pre>${this.h(JSON.stringify(c.origins,null,2))}</pre>`); }
  includeSource(c) {
    const s=this.canvas(),source=s.accumulation.sources.find(v=>v.studyId===c.studyId);
    if(source){const n=s.nodes.find(n=>n.origins.some(o=>o.studyId===c.studyId&&o.nodeId===c.nodeId));return this.addExisting(n.id);}
    const original=this.ctx.state().studies.find(s=>s.id===c.studyId);
    this.ctx.dialog('Добавить исходник на полотно',`<p>Будет добавлен целый снимок «${this.ctx.permanent?'':this.h(c.studyTitle)}»: ${original.nodes.length} узлов / ${original.edges.length} рёбер. Исходное исследование сохранится; совпадения не объединятся.</p><p>Исходный ID ${this.h(c.nodeId)} будет представлен ID копии полотна с происхождением. Прежние копии сохраняют свои ID.</p>`,async()=>{await this.save();await this.ctx.mutate('accumulation_add_source',{studyId:s.id,sourceStudyId:c.studyId});const n=this.canvas().nodes.find(n=>n.origins.some(o=>o.studyId===c.studyId&&o.nodeId===c.nodeId));await this.addExisting(n.id);},'Подтвердить добавление исходника');
  }
  async connect(from=this.host.querySelector('#def-from')?.value,to=this.host.querySelector('#def-to')?.value) {
    if(!from||!to)throw Error('Выберите два поля.');
    const available=this.canvas().edges.filter(e=>e.from===from&&e.to===to&&(!e.role||e.role==='relation'));
    if(this.draft.edges.some(e=>e.from===from&&e.to===to))throw Error('Эти поля уже соединены в черновике.');
    if(available.length){this.ctx.dialog('Выбрать ID обычного ребра',`<p>Эти концепты уже соединены. Выберите существующий ID или обоснуйте новое параллельное ребро.</p><select name="edgeId">${available.map(e=>`<option value="${this.h(e.id)}">${this.h(e.id)} · ${this.h(e.type||'без типа')} · ${this.h(e.notes)}</option>`).join('')}<option value="new">Новое параллельное ребро</option></select><label>Причина нового ребра<input name="reason"></label>`,async f=>{const id=f.get('edgeId');this.draft.edges.push(id==='new'?{id:crypto.randomUUID(),from,to,existing:false,parallelReason:f.get('reason')}:{id,from,to,existing:true});await this.save();},'Выбрать');return;}
    this.draft.edges.push({id:crypto.randomUUID(),from,to,existing:false});await this.save();
  }
  addContext(from,to) {
    if(!from||!to||from===to)throw Error('Выберите два разных обычных ребра.');
    if(this.draft.contextEdges.some(c=>c.from===from&&c.to===to))return;
    const c=(this.ctx.permanent?this.canvas():this.canvas().accumulation.manual)?.contextEdges.find(c=>c.from===from&&c.to===to);
    this.draft.contextEdges.push(c?{id:c.id,from,to}:{id:crypto.randomUUID(),from,to});
  }
  confirmRoute() {
    if(!this.route.length)throw Error('Выберите хотя бы одно ребро маршрута.');
    const edges=this.route.map(id=>this.draft.edges.find(e=>e.id===id));if(edges.some((e,i)=>i&&edges[i-1].to!==e.from))throw Error('Следующее ребро должно начинаться в конце предыдущего.');
    const pairs=[];for(let i=0;i<edges.length;i++)for(let j=i+1;j<edges.length;j++)pairs.push([edges[i].id,edges[j].id]);
    this.ctx.dialog('Подтвердить допустимый маршрут',`<p>Маршрут задан оператором. Пары только внутри этой последовательности:</p><ol>${pairs.map(([a,b])=>`<li>${this.h(this.edgeName(a))}<br>→ ${this.h(this.edgeName(b))}</li>`).join('')}</ol>`,async()=>{this.draft.routes.push({id:crypto.randomUUID(),edgeIds:[...this.route]});for(const [a,b] of pairs)this.addContext(a,b);this.route=[];await this.save();},'Подтвердить маршрут');
  }
  async preview() {
    await this.save();const sid=this.canvas().id,did=this.draft.id;
    const preview=await this.ctx.api('/api/definition-preview?'+new URLSearchParams({study:sid,draft:did}));
    this.ctx.dialog(this.ctx.permanent?'Изменения постоянного графа':'Изменения постоянного полотна',`<p>Новые / обновляемые концепты: ${preview.nodes.length}; рёбра: ${preview.edges.length}; контекстные пары: ${preview.contextEdges.length}. Повторно используются ${preview.reusedNodes.length} узлов / ${preview.reusedEdges.length} рёбер.</p><pre>${this.h(JSON.stringify(preview,null,2))}</pre><label class="checkbox"><input type="checkbox" name="confirmed" required>Я просмотрел ID и подтверждаю включение миниграфа</label>`,async f=>{if(!f.has('confirmed'))throw Error('Требуется подтверждение оператора.');await this.ctx.mutate('definition_publish',{studyId:sid,draftId:did,confirmed:true});this.ctx.toast(this.ctx.permanent?'Миниграф включён в постоянный граф.':'Миниграф включён на постоянное полотно.');},this.ctx.permanent?'Включить в граф':'Включить на полотно');
  }
};
