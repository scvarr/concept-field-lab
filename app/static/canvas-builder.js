'use strict';
// Canvas presentation of the existing DefinitionBuilder; persistence and semantics
// remain in builder.js and the same preview/publish API used by the legacy UI.
Object.assign(DefinitionBuilder.prototype,{
  renderCanvas() { this.captionIndex=null;
    const s=this.canvas();if(!s)return;
    if(!this.draft){this.draft=structuredClone(this.drafts().find(d=>d.id===this.ctx.ui().definitionDraft)||this.drafts()[0]||{id:crypto.randomUUID(),title:'Новое определение',definition:'',nodes:[],edges:[],contextEdges:[],routes:[]});this.route=[];this.interaction=null;this.selectedObject=null;}
    const d=this.draft,h=v=>this.h(v);this.ctx.ui().definitionDraft=d.id;this.ctx.saveUI();
    this.route=this.route.filter(id=>d.edges.some(e=>e.id===id&&e.role!=='component'));
    if(this.selectedObject&&!d[this.selectedObject.kind==='node'?'nodes':this.selectedObject.kind==='context'?'contextEdges':'edges'].some(v=>v.id===this.selectedObject.id))this.selectedObject=null;
    if(this.interaction&&!d[this.interaction.kind==='connect'?'nodes':'edges'].some(v=>v.id===this.interaction.from))this.interaction=null;
    this.host.innerHTML=`<div class="canvas-toolbar"><select id="def-open" aria-label="Сохранённые определения">${this.drafts().some(v=>v.id===d.id)?'':`<option value="${h(d.id)}">${h(d.title)}</option>`}${this.drafts().map(v=>`<option value="${h(v.id)}" ${v.id===d.id?'selected':''}>${h(v.title)}</option>`).join('')}</select><button id="def-new" aria-label="Новое определение">Новое</button><button id="def-definition">Определение</button><button id="def-search-open">Добавить поле</button><button id="def-routes-open">Маршруты и контекст</button><button id="def-preview" class="primary">Включить в граф…</button><button id="def-actions" aria-haspopup="menu">Действия ▾</button><button id="def-fit">Вписать</button><label class="checkbox"><input id="def-ids" type="checkbox" ${this.ids?'checked':''}>ID</label></div><div id="def-graph" class="graph canvas-surface" tabindex="0" aria-label="Миниграф определения"></div><div class="canvas-status"><span id="def-canvas-status" role="status"></span><button id="def-mode-cancel" ${this.interaction?'':'hidden'}>Отменить выбор</button><button id="def-route-confirm" ${this.route.length?'':'hidden'}>Подтвердить маршрут (${this.route.length})</button><button id="def-route-clear" ${this.route.length?'':'hidden'}>Очистить маршрут</button></div>`;
    const bind=(sel,fn)=>this.host.querySelector(sel).onclick=this.act(fn);
    this.host.querySelector('#def-open').onchange=this.act(async()=>{const id=this.host.querySelector('#def-open').value;if(id===this.draft.id)return;await this.save();this.draft=structuredClone(this.drafts().find(v=>v.id===id));this.route=[];this.interaction=null;this.selectedObject=null;this.render();});
    bind('#def-new',async()=>{await this.save();this.draft={id:crypto.randomUUID(),title:'Новое определение',definition:'',nodes:[],edges:[],contextEdges:[],routes:[]};this.route=[];this.interaction=null;this.selectedObject=null;await this.save(false);this.openDefinition();});
    bind('#def-definition',()=>this.openDefinition());bind('#def-search-open',()=>{this.spawnPosition=null;this.openSearch();});bind('#def-routes-open',()=>this.openRoutes());bind('#def-preview',()=>this.preview());
    this.host.querySelector('#def-actions').onclick=e=>{const target=this.selectedObject||{kind:'canvas'};this.objectMenu(target.kind,target.id,e);};
    this.host.querySelector('#def-fit').onclick=()=>this.graph?.fit();this.host.querySelector('#def-ids').onchange=e=>{this.ids=e.target.checked;this.draw();};
    bind('#def-route-confirm',()=>this.confirmRoute());bind('#def-route-clear',()=>{this.route=[];this.render();});bind('#def-mode-cancel',()=>{this.interaction=null;this.render();});
    const host=this.host.querySelector('#def-graph');host.oncontextmenu=e=>{if(e.target.closest('svg'))return;e.preventDefault();this.objectMenu('canvas',null,e);};host.onkeydown=e=>{if(!e.target.closest('svg')&&(e.key==='ContextMenu'||e.key==='F10'&&e.shiftKey)){e.preventDefault();this.objectMenu('canvas',null,e);}};
    if(d.graphStale){const button=document.createElement('button');button.textContent='Открыть актуальную область…';button.onclick=this.act(()=>graphEditor.region(d.nodes.filter(n=>this.canvas().nodes.some(v=>v.id===n.id)).map(n=>n.id)));this.host.querySelector('.canvas-toolbar').prepend(button);const banner=document.createElement("p");banner.className="error";banner.textContent=d.graphStale;this.host.prepend(banner);}else if(d.graphBase){this.host.querySelector("#def-preview").textContent="Применить область…";this.host.querySelector("#def-definition").textContent="Область · описание";}
    this.draw();this.refreshStatus();
  },
  refreshStatus() {
    const host=this.host.querySelector('#def-canvas-status');if(!host)return;
    const d=this.draft,mode=this.interaction;
    host.textContent=mode?`${mode.kind==='connect'?'Выберите конечное поле для связи от':'Выберите последующее ребро для контекста от'} ${mode.kind==='connect'?this.name(mode.from):this.edgeName(mode.from)} · Escape — отмена`:this.route.length?`Маршрут: ${this.route.map(id=>this.edgeName(id)).join(' → ')}`:`${d.nodes.length} полей · ${d.edges.length} рёбер · ${d.contextEdges.length} контекстных · правый щелчок или «Действия» · ${this.changed?'есть несохранённый текст':'черновик '+d.id}`;
  },
  pickObject(kind,id) {
    this.ctx.run(async()=>{
      const mode=this.interaction;
      if(mode){if(kind!==(mode.kind==='connect'?'node':'edge'))return this.ctx.toast('Выберите объект указанного типа.');if(mode.kind==='context'&&this.draft.edges.find(e=>e.id===id)?.role==='component')throw Error('Компонентность не участвует в контексте.');if(mode.kind==='context'&&id===mode.from)throw Error('Выберите другое обычное ребро.');this.interaction=null;if(mode.kind==='connect')await this.connect(mode.from,id);else{this.addContext(mode.from,id);await this.save();}this.render();return;}
      this.selectedObject={kind,id};if(kind==='context')this.openContext(id);else if(kind==='edge')this.openDraftEdge(id);else{this.draw();this.refreshStatus();}
    })();
  },
  startPick(kind,from) { this.ctx.closeDialog();this.interaction={kind,from};this.render(); },
  objectMenu(kind,id,event) {
    if(this.ctx.busy())return;this.capture();if(kind!=='canvas')this.selectedObject={kind,id};
    let position=null;if(kind==='canvas'&&this.graph&&event?.clientX!==undefined){const p=this.graph.point(event);position={x:Math.max(-100000,Math.min(100000,p.x)),y:Math.max(-100000,Math.min(100000,p.y))};}
    const action=(actionId,label,fn,disabled=false)=>({id:actionId,label,disabled:disabled||(kind==='edge'&&this.draft.edges.find(e=>e.id===id)?.role==='component'&&['route-add','context'].includes(actionId)),run:this.act(fn)});
    const globalActions=kind==='node'&&this.canvas().nodes.some(n=>n.id===id)?[action('global-edit','Изменить общий объект…',()=>graphEditor.node(id)),action('global-uses','Все использования и преобразование…',()=>graphEditor.uses(id))]:[];
    if((kind==='edge'&&this.canvas().edges.some(e=>e.id===id))||(kind==='context'&&this.canvas().contextEdges.some(c=>c.id===id)))globalActions.push(action('global-edit','Изменить общий объект…',()=>graphEditor.edge(id,kind==='context')));
    const common=[...globalActions,action('definition','Исходное определение…',()=>this.openDefinition()),action('search','Добавить поле / найти ID…',()=>{this.spawnPosition=position;this.openSearch();}),action('objects','Поля и рёбра по ID…',()=>this.openObjects()),action('routes','Маршруты и контекст…',()=>this.openRoutes()),action('publish','Просмотреть и включить…',()=>this.preview())];
    const actions=kind==='context'?[...globalActions,action('edit-context','Контекстная связь…',()=>this.openContext(id)),action('routes','Все маршруты и контекст…',()=>this.openRoutes())]:kind==='node'?[action('edit-node','Обозначения и свойства…',()=>this.openNode(id)),action('connect','Соединить отсюда →',()=>this.startPick('connect',id)),action('alias','Добавить обозначение…',()=>this.editAlias(id)),action('usage','Окружение и происхождение…',()=>this.inspect(id)),action('remove-node','Убрать поле из миниграфа…',()=>this.removeField(id)),...common]:kind==='edge'?[...globalActions,action('edit-edge','Ребро и его контекст…',()=>this.openDraftEdge(id)),action('route-add','＋ В выбранный маршрут',()=>{if(!this.route.includes(id))this.route.push(id);this.render();}),action('context','Контекст отсюда →',()=>this.startPick('context',id)),action('route-confirm','Подтвердить выбранный маршрут…',()=>this.confirmRoute(),!this.route.length),action('remove-edge','Убрать ребро из миниграфа…',()=>this.removeDraftEdge(id)),action('routes','Все маршруты и контекст…',()=>this.openRoutes()),action('objects','Поля и рёбра по ID…',()=>this.openObjects())]:[...common,action('route-confirm','Подтвердить выбранный маршрут…',()=>this.confirmRoute(),!this.route.length),action('fit','Вписать миниграф',()=>this.graph?.fit())];
    this.ctx.menu.open(event,kind==='node'?this.name(id):kind==='edge'?this.edgeName(id):kind==='context'?'Контекст '+id:'Миниграф',actions);
  },
  openDefinition() {
    this.capture();const d=this.draft,h=v=>this.h(v),source=d.source;
    this.ctx.dialog('Исходное определение',`<label>Название<input id="def-title" required maxlength="1000" value="${h(d.title)}"></label><label>Определение<textarea id="def-text" rows="6" maxlength="50000">${h(d.definition)}</textarea></label>${source?`<details><summary>${h(source.name)} · ${h(source.entry)} · значение ${h(source.senseId)} · revision ${h(source.revision)}</summary><pre>${h(JSON.stringify(source,null,2))}</pre></details>`:''}<p>Смысловые решения и поля задаёте вы.</p>`,()=>this.save(),'Сохранить определение');
    for(const id of ['def-title','def-text'])document.querySelector('#'+id).oninput=()=>{this.changed=true;this.capture();this.refreshStatus();};
  },
  openSearch() {
    this.capture();const h=v=>this.h(v);
    this.ctx.dialog('Добавить поле / открыть словарное определение',`<input id="def-search" type="search" value="${h(this.query)}" placeholder="Словарная форма или концептуальный ID" aria-label="Поиск словаря и концептов"><div id="def-results"></div><div id="def-senses"></div><label>Обозначение нового концепта<input id="def-new-label" maxlength="1000"></label><button type="button" id="def-add-node">Создать новый концепт</button>`);
    document.querySelector('#def-search').oninput=e=>{this.query=e.target.value;clearTimeout(this.searchTimer);this.searchTimer=setTimeout(this.ctx.run(()=>this.search()),180);};
    document.querySelector('#def-add-node').onclick=this.act(async()=>{const text=document.querySelector('#def-new-label').value.trim();if(!text)throw Error('Введите обозначение.');await this.addNew(text);});
    const alpha=document.createElement('button');alpha.type='button';alpha.id='def-add-alpha';alpha.textContent='Создать α (обозначение необязательно)';document.querySelector('#modal-form').insertBefore(alpha,document.querySelector('.dialog-actions'));alpha.onclick=this.act(()=>this.addNew(document.querySelector('#def-new-label').value.trim(),null,'alpha'));
    if(this.query)this.ctx.run(()=>this.search())();document.querySelector('#def-search').focus();
  },
  openObjects() {
    const h=v=>this.h(v),d=this.draft;
    this.ctx.dialog('Поля и рёбра миниграфа',`<p>Объекты можно выбрать по ID, даже если они перекрываются на полотне.${this.interaction?' Выберите конечный объект текущей операции.':''}</p><h3>Поля (${d.nodes.length})</h3>${d.nodes.map(n=>`<button type="button" class="object-choice" data-object-node="${h(n.id)}">${h(this.name(n.id))}<code>${h(n.id)}</code></button>`).join('')}<h3>Обычные рёбра (${d.edges.length})</h3>${d.edges.map(e=>`<button type="button" class="object-choice" data-object-edge="${h(e.id)}">${h(this.edgeName(e.id))}</button>`).join('')}<h3>Контекстные связи (${d.contextEdges.length})</h3>${d.contextEdges.map(c=>`<button type="button" class="object-choice" data-object-context="${h(c.id)}">${h(c.from)} → ${h(c.to)}<code>${h(c.id)}</code></button>`).join('')}`);
    document.querySelectorAll('[data-object-node]').forEach(b=>b.onclick=()=>{const id=b.dataset.objectNode;if(this.interaction){this.ctx.closeDialog();this.pickObject('node',id);}else this.openNode(id);});
    document.querySelectorAll('[data-object-context]').forEach(b=>b.onclick=()=>this.interaction?this.ctx.toast('Выберите обычное ребро или поле.'):this.openContext(b.dataset.objectContext));
    document.querySelectorAll('[data-object-edge]').forEach(b=>b.onclick=()=>{const id=b.dataset.objectEdge;if(this.interaction){this.ctx.closeDialog();this.pickObject('edge',id);}else this.openDraftEdge(id);});
  },
  openNode(id,options={}) {
    this.capture();const h=v=>this.h(v),actual=this.canvas().nodes.find(n=>n.id===id),field=this.draft.nodes.find(n=>n.id===id);
    this.ctx.dialog('Концепт и словарные обозначения',`<p><strong>${h(options.global?this.captions(true).display(id):this.name(id))}</strong><br><code>${h(id)}</code></p><p>${actual?'Постоянный ID графа':'Поле черновика · ещё не включено в общий граф'}</p>${this.aliasFields(id)}<div class="actions"><button type="button" id="node-usage">Окружение и происхождение</button>${options.global?'<button type="button" id="global-reuse">Использовать ID в черновике</button><button type="button" id="global-neighbours">Открыть окружение</button><button type="button" id="node-origin">Редактировать в конструкторе</button>':field?'<button type="button" id="node-connect">Соединить отсюда →</button><button type="button" id="node-remove">Убрать поле из миниграфа</button>':''}</div>`);
    const form=document.querySelector('#modal-form');form.querySelectorAll('[data-alias-add]').forEach(b=>b.onclick=()=>this.editAlias(id));form.querySelectorAll('[data-alias-edit]').forEach(b=>b.onclick=()=>this.editAlias(id,b.dataset.aliasEdit));form.querySelectorAll('[data-alias-remove]').forEach(b=>b.onclick=()=>this.removeAlias(id,b.dataset.aliasRemove));
    form.querySelector('#node-usage').onclick=()=>this.inspect(id);
    if(options.global){form.querySelector('#global-reuse').onclick=this.ctx.run(()=>options.reuse(id));form.querySelector('#global-neighbours').onclick=()=>options.neighbours(id);form.querySelector('#node-origin').onclick=this.ctx.run(()=>options.editDefinition(actual.definitionId));}
    else if(field){form.querySelector('#node-connect').onclick=()=>this.startPick('connect',id);form.querySelector('#node-remove').onclick=()=>this.removeField(id);}
    const properties=options.global?actual:field?.existing?actual:field;if(properties?.kind||properties?.notes){const section=document.createElement('section');section.innerHTML=`<h3>Собственные характеристики</h3><p>${h(properties.kind)}</p><p>${h(properties.notes)}</p>`;form.insertBefore(section,form.querySelector('.dialog-actions'));}
    if((options.global?actual?.structure:field?.structure||field?.base?.structure||actual?.structure)==='alpha'){
      const section=document.createElement('section');section.innerHTML=`<h3>α · обязательный состав</h3><pre>${h(this.structureText(id,options.global))}</pre><p>Отношения целого и компонентов сохраняются у своих ID. Состав не переносит характеристики.</p>${field&&!field.existing&&!options.global?'<button type="button" id="alpha-components">Редактировать обязательные компоненты</button>':''}`;form.insertBefore(section,form.querySelector('.dialog-actions'));section.querySelector('#alpha-components')?.addEventListener('click',()=>this.openComponents(id));
    }
    if(field&&!field.existing&&!options.global){const button=document.createElement('button');button.type='button';button.id='node-properties';button.textContent='Редактировать собственные характеристики';button.onclick=()=>this.editProperties(id);form.insertBefore(button,form.querySelector('.dialog-actions'));}
    if(field?.existing&&actual&&!options.global){const button=document.createElement('button');button.type='button';button.id='node-refresh';button.textContent='Обновить выбранный ID после просмотра';button.onclick=this.act(async()=>{field.base=structuredClone(actual);await this.save();this.openNode(id);});form.insertBefore(button,form.querySelector('.dialog-actions'));}
  },
  removeField(id) {
    this.ctx.dialog('Убрать поле из миниграфа',`<p>${this.h(this.name(id))} · ${this.h(id)}</p><p>Из черновика будут убраны поле, его рёбра и связанные записи маршрутов/контекста. Изменения общего графа применяются только после просмотра и включения.</p>`,async()=>{const d=this.draft,edges=d.edges.filter(e=>e.from===id||e.to===id).map(e=>e.id);d.nodes=d.nodes.filter(n=>n.id!==id);d.edges=d.edges.filter(e=>!edges.includes(e.id));this.prune(edges);await this.save();},'Убрать поле');
  },
  removeDraftEdge(id) {
    this.ctx.dialog('Убрать ребро из миниграфа',`<p>${this.h(this.edgeName(id))}</p><p>Связанные контекстные пары и записи маршрутов также уберутся из черновика. Концепты останутся.</p>`,async()=>{this.draft.edges=this.draft.edges.filter(e=>e.id!==id);this.prune([id]);await this.save();},'Убрать ребро');
  },
  contextRows(edgeId) {
    const h=v=>this.h(v);return this.draft.contextEdges.filter(c=>!edgeId||c.from===edgeId||c.to===edgeId).map(c=>`<div class="context-row"><p>${h(this.edgeName(c.from))}<br>→ ${h(this.edgeName(c.to))}<br><code>${h(c.id)}</code></p><button type="button" data-def-context-reverse="${h(c.id)}">Развернуть</button><button type="button" data-def-context-remove="${h(c.id)}">Удалить</button></div>`).join('')||'<p>Контекстных пар нет.</p>';
  },
  bindContexts(reopen) {
    const form=document.querySelector('#modal-form');form.querySelectorAll('[data-def-context-remove]').forEach(b=>b.onclick=this.act(async()=>{this.draft.contextEdges=this.draft.contextEdges.filter(c=>c.id!==b.dataset.defContextRemove);await this.save();reopen();}));
    form.querySelectorAll('[data-def-context-reverse]').forEach(b=>b.onclick=this.act(async()=>{const c=this.draft.contextEdges.find(c=>c.id===b.dataset.defContextReverse);if(this.draft.contextEdges.some(v=>v.from===c.to&&v.to===c.from))throw Error('Обратная пара уже записана.');[c.from,c.to]=[c.to,c.from];await this.save();reopen();}));
  },
  openContext(id) {
    const c=this.draft.contextEdges.find(v=>v.id===id),h=v=>this.h(v);if(!c)return;
    this.selectedObject={kind:'context',id};
    this.ctx.dialog('Направленная контекстная связь',`<p><code>${h(c.id)}</code></p><p>${h(this.edgeName(c.from))}<br>→ ${h(this.edgeName(c.to))}</p><p>Связывает ID двух обычных рёбер. Изменения общего графа требуют просмотра и включения.</p><div class="actions"><button type="button" data-def-context-reverse="${h(c.id)}">Развернуть</button><button type="button" data-def-context-remove="${h(c.id)}">Удалить</button></div>`);
    this.bindContexts(()=>this.draft.contextEdges.some(v=>v.id===id)?this.openContext(id):this.openRoutes());
  },
  openDraftEdge(id) {
    const e=this.draft.edges.find(e=>e.id===id),h=v=>this.h(v);if(!e)return;
    this.selectedObject={kind:'edge',id};
    if(e.role==='component'){this.ctx.dialog('Обязательный компонент α',`<p>${h(this.edgeName(id))}</p><p>Структурная компонентность, не обычное отношение и не маршрут.</p><button type="button" id="component-remove">Убрать компонент</button>`);document.querySelector('#component-remove').onclick=()=>this.removeDraftEdge(id);return;}
    this.ctx.dialog('Обычное ребро и контекст',`<p>${h(this.edgeName(id))}</p><p>${e.existing?'Повторно выбранный ID':'Ребро этого черновика'} · направление ${h(e.from)} → ${h(e.to)}</p><div class="actions"><button type="button" id="edge-route-add">＋ В маршрут</button><button type="button" id="edge-context-pick">Контекст отсюда →</button><button type="button" id="edge-remove">Убрать ребро</button></div><h3>Направленные контекстные связи</h3>${this.contextRows(id)}`);
    document.querySelector('#edge-route-add').onclick=()=>{if(!this.route.includes(id))this.route.push(id);this.ctx.closeDialog();this.render();};document.querySelector('#edge-context-pick').onclick=()=>this.startPick('context',id);document.querySelector('#edge-remove').onclick=()=>this.removeDraftEdge(id);this.bindContexts(()=>this.openDraftEdge(id));
  },
  openRoutes() {
    this.capture();const d=this.draft,h=v=>this.h(v),edges=d.edges.filter(e=>e.role!=='component').map(e=>`<option value="${h(e.id)}">${h(this.edgeName(e.id))}</option>`).join('');
    this.ctx.dialog('Маршруты и направленный контекст',`<h3>Выбранный маршрут (${this.route.length})</h3><ol>${this.route.map(id=>`<li>${h(this.edgeName(id))}</li>`).join('')}</ol><div class="actions"><button type="button" id="routes-confirm">Просмотреть и подтвердить</button><button type="button" id="routes-clear">Очистить выбор</button></div><h3>Записанные маршруты (${d.routes.length})</h3>${d.routes.map(r=>`<p>${r.edgeIds.map(id=>h(this.edgeName(id))).join('<br>')}<button type="button" data-def-remove-route="${h(r.id)}">Удалить запись маршрута</button></p>`).join('')}<p>Удаление записи маршрута не удаляет его контекстные пары.</p><h3>Добавить контекстную пару</h3><label>От обычного ребра<select id="def-context-from">${edges}</select></label><label>К обычному ребру<select id="def-context-to">${edges}</select></label><button type="button" id="def-context-add">Добавить контекст →</button><h3>Все контекстные пары</h3>${this.contextRows()}`);
    document.querySelector('#routes-confirm').onclick=this.act(()=>this.confirmRoute());document.querySelector('#routes-clear').onclick=()=>{this.route=[];this.render();this.openRoutes();};
    document.querySelectorAll('[data-def-remove-route]').forEach(b=>b.onclick=this.act(async()=>{d.routes=d.routes.filter(r=>r.id!==b.dataset.defRemoveRoute);await this.save();this.openRoutes();}));
    document.querySelector('#def-context-add').onclick=this.act(async()=>{this.addContext(document.querySelector('#def-context-from').value,document.querySelector('#def-context-to').value);await this.save();this.openRoutes();});this.bindContexts(()=>this.openRoutes());
  }
});

Object.assign(DefinitionBuilder.prototype,{
  structureText(id,global=false) {
    const nodes=new Map(this.canvas().nodes.map(n=>[n.id,n])),edges=new Map(this.canvas().edges.map(e=>[e.id,e]));
    for(const n of global?[]:this.draft.nodes)nodes.set(n.id,{...n.base,...n});
    // Replace owned published edges with the working draft, retaining other IDs.
    for(const [key,e] of edges)if(!global&&e.definitionId===this.draft.id)edges.delete(key);
    for(const e of global?[]:this.draft.edges)edges.set(e.id,e);
    const captions=this.captions(global),rows=[],stack=[{id,depth:0,path:new Set()}];
    while(stack.length&&rows.length<200){const v=stack.pop(),n=nodes.get(v.id),alpha=n?.structure==='alpha';rows.push('  '.repeat(v.depth)+(alpha?'α ':'')+captions.label(v.id)+' ['+v.id+']');if(v.path.has(v.id)){rows.push('  '.repeat(v.depth+1)+'Цикл');continue;}if(v.depth>=20){rows.push('  '.repeat(v.depth+1)+'Предел показа 20 уровней');continue;}const path=new Set([...v.path,v.id]);const children=[...edges.values()].filter(e=>e.role==='component'&&e.from===v.id);for(const e of children.reverse())stack.push({id:e.to,depth:v.depth+1,path});}
    if(stack.length)rows.push('Показ ограничен 200 строками; полный состав хранится в графе.');return rows.join('\n');
  },
  openComponents(id) {
    const field=this.draft.nodes.find(n=>n.id===id);if(!field||field.existing||field.structure!=='alpha')throw Error('Редактируйте α в её исходном определении.');
    const h=v=>this.h(v),edges=this.draft.edges.filter(e=>e.role==='component'&&e.from===id);
    this.ctx.dialog('Обязательные компоненты α',`<p>α <code>${h(id)}</code>. Выберите прямые компоненты; вложенная α сохраняет собственный ID и состав. Пустой состав можно сохранить в черновике, но нельзя опубликовать.</p>${this.draft.nodes.filter(n=>n.id!==id).map(n=>`<label class="checkbox"><input type="checkbox" name="component" value="${h(n.id)}" ${edges.some(e=>e.to===n.id)?'checked':''}>${h(this.name(n.id))} · ${h(n.id)}</label>`).join('')}<p>Другие ID сначала добавьте через «Добавить поле».</p>`,async f=>{const targets=new Set(f.getAll('component'));const removed=edges.filter(e=>!targets.has(e.to)).map(e=>e.id);this.draft.edges=this.draft.edges.filter(e=>!removed.includes(e.id));for(const target of targets)if(!edges.some(e=>e.to===target))this.draft.edges.push({id:crypto.randomUUID(),from:id,to:target,role:'component',existing:false});await this.save();},'Сохранить состав');
  },
  editProperties(id) {
    const n=this.draft.nodes.find(n=>n.id===id),h=v=>this.h(v);this.ctx.dialog('Собственные характеристики ID',`<p>${h(id)}. Не наследуются по компонентности.</p><label>Тип / характеристика<input name="kind" maxlength="1000" value="${h(n.kind)}"></label><label>Примечание<textarea name="notes" maxlength="50000">${h(n.notes)}</textarea></label>`,async f=>{n.kind=f.get('kind');n.notes=f.get('notes');await this.save();},'Сохранить характеристики');
  }
});
