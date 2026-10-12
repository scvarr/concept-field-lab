'use strict';

// UI-only candidates and independent inspection windows. Knowledge mutations
// go through the same transactional Store API as the existing editor.
window.AccumulationWorkbench = class {
  constructor(context) {
    this.ctx = context;
    this.host = document.querySelector('#accumulation');
    this.windows = new Map();
    this.request = 0;
    this.nextWindow = 0;
    this.palette = ['#2563eb','#d97706','#16a34a','#be185d','#7c3aed','#0891b2','#9a3412','#4d7c0f'];
  }
  html(value) { return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
  name(n) { return n?.label || `α · ${n?.id?.slice(0,8)||'?'}`; }
  study() { return this.ctx.study(); }
  settings() {
    const ui=this.ctx.ui();ui.accumulations ||= {};
    return ui.accumulations[this.study().id] ||= {basis:'designation',status:'all',query:'',sources:[],indexOpen:false,focus:this.study().rootId,routeSource:'all',showCandidates:true,windows:[]};
  }
  save() { this.ctx.saveUI(); }
  source(sid) { return this.study().accumulation.sources.find(s=>s.studyId===sid); }
  color(sid) { return this.palette[this.study().accumulation.sources.findIndex(s=>s.studyId===sid)%this.palette.length]||'#64748b'; }
  refs(id) { return (this.study().nodes.find(n=>n.id===id)?.origins||[]).map(o=>JSON.stringify([o.studyId,o.nodeId])); }
  fromRef(ref) { const [sid,nid]=JSON.parse(ref);return {source:this.source(sid),node:this.source(sid)?.snapshot.nodes.find(n=>n.id===nid),sid,nid}; }
  currentId(ref) { return this.study().nodes.find(n=>(n.origins||[]).some(o=>JSON.stringify([o.studyId,o.nodeId])===ref))?.id; }
  node(id) { return this.study().nodes.find(n=>n.id===id); }
  endpointLabel(snapshot,id) { return this.name(snapshot.nodes.find(n=>n.id===id)); }
  edgeName(e) { return e.role==='component'?`компонент${e.componentRole?' · '+e.componentRole:''}`:e.type||'связь без типа'; }

  async render() {
    const s=this.study();
    if(!s?.accumulation) {
      this.host.innerHTML=`<div class="accum-intro"><h2>Одно полотно для независимых графов</h2><p>Добавьте исходные исследования. Совпадения слов останутся кандидатами до вашего решения.</p><button id="accum-create" class="primary">Создать полотно</button>${this.ctx.state().studies.filter(s=>s.accumulation&&!s.archived).map(s=>`<button data-open-accum="${this.html(s.id)}">${this.html(s.title)}</button>`).join('')}</div>`;
      this.host.querySelector('#accum-create').onclick=()=>this.create();
      this.host.querySelectorAll('[data-open-accum]').forEach(b=>b.onclick=()=>this.ctx.activate(b.dataset.openAccum));
      for(const w of this.windows.values())w.el.hidden=true;
      return;
    }
    const prefs=this.settings();
    if(prefs.focusRef)prefs.focus=this.currentId(prefs.focusRef)||s.rootId;
    if(!this.node(prefs.focus))prefs.focus=s.rootId;
    if(this.mounted!==s.id) { this.mount();this.mounted=s.id; }
    this.host.querySelector('#accum-title').textContent=s.title;
    this.host.querySelector('#accum-source-count').textContent=`${s.accumulation.sources.length} исходных графов · ${s.nodes.length} узлов · ${s.edges.length} содержательных рёбер`;
    this.host.querySelector('#accum-legend').innerHTML=s.accumulation.sources.map((source,i)=>`<span style="--source-color:${this.palette[i%this.palette.length]}">${this.html(source.snapshot.title)}</span>`).join('');
    const sourceOptions=s.accumulation.sources.map(source=>`<option value="${this.html(source.studyId)}">${this.html(source.snapshot.title)}</option>`).join('');
    const filter=this.host.querySelector('#accum-index-sources');filter.innerHTML=sourceOptions;for(const option of filter.options)option.selected=prefs.sources.includes(option.value);
    const route=this.host.querySelector('#accum-route');route.innerHTML=`<option value="all">Все источники · раздельные рёбра</option>${sourceOptions}`;route.value=prefs.routeSource;
    this.host.querySelector('#accum-roots').innerHTML=s.accumulation.sources.map(source=>{
      const ref=JSON.stringify([source.studyId,source.snapshot.rootId]);return `<option value="${this.html(this.currentId(ref))}">${this.html(source.snapshot.title)}</option>`;
    }).join('');
    this.host.querySelector('#accum-basis').value=prefs.basis;this.host.querySelector('#accum-index-status').value=prefs.status;
    this.host.querySelector('#accum-index-query').value=prefs.query;this.host.querySelector('#accum-show-candidates').checked=prefs.showCandidates;
    this.toggleIndex(false);this.renderNode();this.renderCanvas();this.renderHistory();
    await this.refreshIndex();
    await this.refreshWindows();
  }
  mount() {
    const old=this.host.querySelector('#accum-graph')?.graphView;old?.observer.disconnect();
    this.host.innerHTML=`
      <div class="accum-toolbar"><strong id="accum-title"></strong><button id="accum-create">Новое полотно</button><button id="accum-add-source">Добавить граф</button><button id="accum-export">Экспорт полотна ↓</button><span id="accum-source-count"></span></div>
      <div id="accum-legend" class="accum-legend"></div>
      <div class="accum-controls"><button id="accum-toggle-index">Индекс совпадений</button><label>Рёбра <select id="accum-route"></select></label><label class="checkbox"><input type="checkbox" id="accum-show-candidates">Вспомогательные кандидаты</label><button id="accum-fit">Вписать полотно</button><button id="accum-center">К выбранному</button><button id="accum-back">Вернуть участок</button><button id="accum-zoom-out" aria-label="Уменьшить полотно">−</button><button id="accum-zoom-reset">100%</button><button id="accum-zoom-in" aria-label="Увеличить полотно">＋</button><label>Корень источника <select id="accum-roots"></select></label><button id="accum-go-root">Перейти к корню</button></div>
      <div class="accum-layout">
        <aside id="accum-index" class="accum-index" hidden><h3>Индекс совпадений</h3><label>Источник обозначений<select id="accum-basis"><option value="designation">Словарные обозначения</option><option value="label">Технические названия</option><option value="both">Оба · раздельные группы</option></select></label><input type="search" id="accum-index-query" aria-label="Поиск совпадений" placeholder="Обозначение…"><label>Исходные графы индекса<select id="accum-index-sources" multiple size="3"></select></label><small>Без выбора — все исходники.</small><label>Статус решений<select id="accum-index-status"><option value="all">Все решения</option><option value="pending">Не определены</option><option value="confirmed">Объединены</option><option value="rejected">Различны</option></select></label><p id="accum-index-count"></p><div id="accum-index-groups"></div><div id="accum-group-details"></div></aside>
        <div class="accum-canvas"><div id="accum-graph" class="graph" aria-label="Накопительное полотно"></div><p id="accum-graph-caption"></p><div id="accum-selection" class="accum-selection"></div></div>
      </div>
      <div id="accum-pair" class="accum-pair"></div><details id="accum-history"><summary>История решений оператора</summary><div id="accum-history-content"></div></details>
      <div id="accum-node-details"></div><div id="accum-dock" class="accum-dock"></div>`;
    const bind=(id,fn)=>this.host.querySelector('#'+id).onclick=fn;
    bind('accum-create',()=>this.create());bind('accum-add-source',()=>this.addSource());
    bind('accum-export',()=>this.ctx.run(async()=>{await this.persistCamera();await this.persistCamera();await this.ctx.download(`/api/graph-export?study=${encodeURIComponent(this.study().id)}`,'concept-field-accumulation.json');})());
    bind('accum-toggle-index',()=>this.toggleIndex());
    bind('accum-fit',()=>this.graph()?.fit());bind('accum-center',()=>this.graph()?.center(this.settings().focus));bind('accum-back',()=>this.graph()?.back());
    bind('accum-zoom-out',()=>this.graph()?.zoom(1/1.2));bind('accum-zoom-in',()=>this.graph()?.zoom(1.2));bind('accum-zoom-reset',()=>{const g=this.graph();if(g)g.zoom(1/g.camera.scale);});
    bind('accum-go-root',()=>this.select(this.host.querySelector('#accum-roots').value,true));
    this.host.querySelector('#accum-route').onchange=e=>{this.settings().routeSource=e.target.value;this.renderCanvas();this.save();};
    this.host.querySelector('#accum-show-candidates').onchange=e=>{this.settings().showCandidates=e.target.checked;this.renderCanvas();this.save();};
    this.host.querySelector('#accum-basis').onchange=e=>{this.settings().basis=e.target.value;this.settings().groupKey=null;this.refreshIndex();this.save();};
    this.host.querySelector('#accum-index-status').onchange=e=>{this.settings().status=e.target.value;this.refreshIndex();this.save();};
    this.host.querySelector('#accum-index-sources').onchange=e=>{this.settings().sources=[...e.target.selectedOptions].map(o=>o.value);this.refreshIndex();this.save();};
    this.host.querySelector('#accum-index-query').oninput=e=>{this.settings().query=e.target.value;clearTimeout(this.searchTimer);this.searchTimer=setTimeout(()=>this.refreshIndex(),180);this.save();};
  }
  graph() { return this.host.querySelector('#accum-graph')?.graphView; }
  toggleIndex(toggle=true) {
    const prefs=this.settings();if(toggle)prefs.indexOpen=!prefs.indexOpen;
    this.host.querySelector('#accum-index').hidden=!prefs.indexOpen;this.host.querySelector('.accum-layout').classList.toggle('index-open',prefs.indexOpen);
    this.host.querySelector('#accum-toggle-index').setAttribute('aria-expanded',prefs.indexOpen);if(toggle)this.save();
  }
  async refreshIndex() {
    const s=this.study();if(!s?.accumulation)return;
    const seq=++this.request,prefs=this.settings(),query=new URLSearchParams({study:s.id,basis:prefs.basis,status:prefs.status,q:prefs.query});
    prefs.sources.forEach(id=>query.append('source',id));
    try {
      const data=await this.ctx.api('/api/accumulation-index?'+query);
      if(seq!==this.request||this.study()?.id!==s.id)return;
      this.index=data;this.indexStudy=s.id;this.indexPage ||= 0;this.indexPage=Math.min(this.indexPage,Math.max(0,Math.ceil(data.groups.length/50)-1));
      this.renderIndex();this.renderCanvas();this.renderPair();
    } catch(error) { this.ctx.toast(error.message,true); }
  }
  renderIndex() {
    const data=this.index,prefs=this.settings();if(!data)return;
    this.host.querySelector('#accum-index-count').textContent=`${data.groups.length} групп · ${data.candidates.length}${data.candidatesTruncated?' показанных из большего числа':''} нерешённых пар. Счётчики групп полные.`;
    const start=this.indexPage*50,rows=data.groups.slice(start,start+50),host=this.host.querySelector('#accum-index-groups');
    host.innerHTML=`<div class="pagination"><button id="accum-index-prev" ${start?'':'disabled'}>←</button><span>${data.groups.length?start+1:0}–${Math.min(start+50,data.groups.length)} из ${data.groups.length}</span><button id="accum-index-next" ${start+50<data.groups.length?'':'disabled'}>→</button></div>`+rows.map(g=>`<button class="accum-group ${prefs.groupKey===g.key?'active':''}" data-index-key="${this.html(g.key)}"><strong>${this.html(g.term)}</strong><small>${g.basis==='designation'?'словарь':'техническое название'} · ${g.nodes} узлов / ${g.representations} исходных представлений · ${g.sources} графов</small><small>Не определены: ${g.counts.pending} · объединены: ${g.counts.confirmed} · различны: ${g.counts.rejected}</small></button>`).join('');
    host.querySelector('#accum-index-prev').onclick=()=>{this.indexPage--;this.renderIndex();};host.querySelector('#accum-index-next').onclick=()=>{this.indexPage++;this.renderIndex();};
    host.querySelectorAll('[data-index-key]').forEach(b=>b.onclick=()=>{prefs.groupKey=b.dataset.indexKey;this.groupPage=0;this.renderIndex();this.renderCanvas();this.save();});
    const group=data.groups.find(g=>g.key===prefs.groupKey),details=this.host.querySelector('#accum-group-details');
    if(!group){details.innerHTML='';return;}
    const ids=group.nodeIds,offset=(this.groupPage||0)*30;
    details.innerHTML=`<h4>${this.html(group.term)}</h4><p>Выбор группы подсвечивает совпадения. Камера сохраняется; переход — отдельная команда.</p>${ids.slice(offset,offset+30).map(id=>`<div class="accum-group-node"><span>${this.html(this.name(this.node(id)))} · ${this.html([...new Set(this.node(id).origins.map(o=>o.studyTitle))].join(' / '))} · ${this.html(id.slice(0,8))}</span><button data-go-node="${this.html(id)}">Перейти</button><button data-inspect-node="${this.html(id)}">Окружение</button></div>`).join('')}<div class="pagination"><button id="accum-group-prev" ${offset?'':'disabled'}>←</button><span>${offset+1}–${Math.min(offset+30,ids.length)} из ${ids.length}</span><button id="accum-group-next" ${offset+30<ids.length?'':'disabled'}>→</button></div>`;
    details.querySelectorAll('[data-go-node]').forEach(b=>b.onclick=()=>this.select(b.dataset.goNode,true));details.querySelectorAll('[data-inspect-node]').forEach(b=>b.onclick=()=>this.openInspector(b.dataset.inspectNode));
    details.querySelector('#accum-group-prev').onclick=()=>{this.groupPage--;this.renderIndex();};details.querySelector('#accum-group-next').onclick=()=>{this.groupPage++;this.renderIndex();};
  }
  decoratedEdges(edges) {
    return edges.map(e=>({...e,color:this.color(e.accumulationSourceId),displayTitle:`${this.source(e.accumulationSourceId)?.snapshot.title||'?'} · ${this.edgeName(e)}`}));
  }
  renderCanvas() {
    const s=this.study();if(!s?.accumulation)return;
    const prefs=this.settings(),host=this.host.querySelector('#accum-graph');if(!host)return;
    const key=host.id+':'+s.id;
    if(host.graphKey!==key||!host.graphView) {
      host.graphView?.observer.disconnect();host.graphKey=key;
      host.graphView=new GraphView(host,{canInteract:id=>!id||!this.ctx.busy(),select:id=>this.select(id),editNode:id=>this.openInspector(id),editEdge:id=>this.openEdge(id),
        savePosition:(id,p)=>this.ctx.mutate('position',{studyId:s.id,nodeId:id,...p}),error:e=>this.ctx.toast(e.message,true),
        changed:snapshot=>{this.ctx.ui().graphs[key]=snapshot;this.save();this.queueCamera(s.id,snapshot.camera);},
        cameraChanged:c=>{this.host.querySelector('#accum-zoom-reset').textContent=Math.round(c.scale*100)+'%';}});
      const saved=this.ctx.ui().graphs[key];host.graphView.restore(saved||{camera:s.accumulation.camera});
    }
    let nodes=s.nodes.slice(0,1000);
    if(!nodes.some(n=>n.id===prefs.focus)){nodes=nodes.slice(0,999);nodes.push(this.node(prefs.focus));}
    const visible=new Set(nodes.map(n=>n.id)),group=this.indexStudy===s.id?this.index?.groups.find(g=>g.key===prefs.groupKey):null;
    const highlighted=new Set(group?.nodeIds||[]),markings=new Map(nodes.map(n=>[n.id,`${n.origins.length>1?'merged-node':''} ${highlighted.has(n.id)?'index-highlight':''}`]));
    const originalEdges=s.edges.filter(e=>(prefs.routeSource==='all'||e.accumulationSourceId===prefs.routeSource)&&visible.has(e.from)&&visible.has(e.to));
    const auxiliary=this.indexStudy===s.id&&prefs.showCandidates?this.index.candidates.filter(e=>visible.has(e.from)&&visible.has(e.to)).map(e=>({...e,color:'#a21caf',highlight:e.evidence.some(x=>x.indexKey===prefs.groupKey),displayTitle:`Кандидат · ${e.evidence.map(x=>(x.basis==='designation'?'словарь':'название')+': '+x.term).join('; ')}`,notes:'Вспомогательная визуальная связь; не отношение концептуального графа.'})):[];
    const contentBudget=Math.min(originalEdges.length,2800),candidateBudget=3000-contentBudget;
    const edges=[...this.decoratedEdges(originalEdges.slice(0,contentBudget)),...auxiliary.slice(0,candidateBudget)];
    host.graphView.update(s,{nodes:nodes.map(n=>({...n,badge:n.origins.length>1?`${n.origins.length} исходных представлений`:n.kind})),edges},prefs.focus,markings);
    this.host.querySelector('#accum-graph-caption').textContent=`Показано ${nodes.length} из ${s.nodes.length} узлов, ${contentBudget} из ${originalEdges.length} доступных содержательных рёбер, ${Math.min(auxiliary.length,candidateBudget)} вспомогательных. ${s.nodes.length>nodes.length||contentBudget<originalEdges.length||auxiliary.length>candidateBudget||this.index?.candidatesTruncated?'Показ неполный: используйте индекс и независимые инспекторы. ':''}${group?`Подсвечено ${nodes.filter(n=>highlighted.has(n.id)).length} из ${group.nodes} узлов группы. `:''}Цвет различает исходник; общий показ не подтверждает смешанный маршрут.`;
  }
  queueCamera(sid,camera) {
    if(!camera||this.study()?.id!==sid)return;
    if(JSON.stringify(camera)===JSON.stringify(this.study().accumulation.camera)){if(this.pendingCamera?.sid===sid){this.pendingCamera=null;clearTimeout(this.cameraTimer);}return;}
    this.pendingCamera={sid,camera:{...camera}};clearTimeout(this.cameraTimer);
    this.cameraTimer=setTimeout(()=>this.persistCamera().catch(()=>{}),500);
  }
  async persistCamera() {
    if(this.cameraWrite){await this.cameraWrite;return;}
    const value=this.pendingCamera;if(!value)return;this.pendingCamera=null;clearTimeout(this.cameraTimer);
    this.cameraWrite=(async()=>{let attempts=0;while(this.ctx.busy()){if(++attempts>100)throw new Error('Дождитесь завершения записи перед экспортом.');await new Promise(resolve=>setTimeout(resolve,100));}await this.ctx.mutate('accumulation_camera',{studyId:value.sid,camera:value.camera});})();
    try {await this.cameraWrite;}
    catch(error){this.ctx.toast('Камера не сохранена: '+error.message,true);throw error;}
    finally{this.cameraWrite=null;if(this.pendingCamera)this.cameraTimer=setTimeout(()=>this.persistCamera().catch(()=>{}),150);}
  }
  select(id,center=false) {
    if(!this.node(id))return;
    const prefs=this.settings();prefs.focus=id;prefs.focusRef=this.refs(id)[0];this.renderCanvas();this.renderNode();this.save();if(center)this.graph()?.center(id);
  }
  renderNode() {
    const prefs=this.settings(),n=this.node(prefs.focus);if(!n)return;
    const selection=this.host.querySelector('#accum-selection');
    selection.innerHTML=`<strong>${this.html(this.name(n))}</strong><span>${n.origins.length} исходных представлений</span><button id="accum-open-inspector">Открыть окружение</button><button id="accum-originals">Исходные представления</button><button id="accum-pick-left">В пару слева</button><button id="accum-pick-right">В пару справа</button>`;
    selection.querySelector('#accum-open-inspector').onclick=()=>this.openInspector(n.id);selection.querySelector('#accum-originals').onclick=()=>this.originals(n.id);
    selection.querySelector('#accum-pick-left').onclick=()=>this.pickPair(n.id,'left');selection.querySelector('#accum-pick-right').onclick=()=>this.pickPair(n.id,'right');
    this.renderPair();
  }
  pickPair(id,side) { this.settings()[side+'Ref']=this.refs(id)[0];this.renderPair();this.save(); }
  renderPair() {
    const prefs=this.settings(),left=prefs.leftRef&&this.currentId(prefs.leftRef),right=prefs.rightRef&&this.currentId(prefs.rightRef),host=this.host.querySelector('#accum-pair');if(!host)return;
    host.innerHTML=`<span>Пара из полотна / инспекторов: ${this.html(left?this.name(this.node(left)):'не выбрано')} ↔ ${this.html(right?this.name(this.node(right)):'не выбрано')}</span><button id="accum-decide-pair" ${left&&right&&left!==right?'':'disabled'}>Решить пару</button><button id="accum-clear-pair">Очистить выбор</button>`;
    host.querySelector('#accum-decide-pair').onclick=()=>this.decisionDialog({from:left,to:right,evidence:[]});host.querySelector('#accum-clear-pair').onclick=()=>{prefs.leftRef=null;prefs.rightRef=null;this.renderPair();this.save();};
  }
  create() {
    const sources=this.ctx.state().studies.filter(s=>!s.accumulation&&!s.archived);
    this.ctx.dialog('Новое накопительное полотно',`<p>Исходники сохранятся раздельно. Добавление не подтверждает совпадения.</p><label>Название полотна<input name="title" value="Накопительное полотно" required></label>${sources.map(s=>`<label class="checkbox"><input name="source" type="checkbox" value="${this.html(s.id)}">${this.html(s.title)}</label>`).join('')}`,
      async f=>{const result=await this.ctx.mutate('create_accumulation',{title:f.get('title'),sourceStudyIds:f.getAll('source')});this.ctx.activate(result.studyId);this.graph()?.fit();},'Создать полотно');
  }
  addSource() {
    const included=new Set(this.study().accumulation.sources.map(s=>s.studyId));
    const sources=this.ctx.state().studies.filter(s=>!s.accumulation&&!s.archived&&!included.has(s.id));
    if(!sources.length)return this.ctx.toast('Сначала создайте или импортируйте независимое исследование.');
    this.ctx.dialog('Добавить независимый граф',`<p>Снимок добавится отдельным блоком. Прежние координаты, камера и решения сохраняются.</p><label>Исходное исследование<select name="sourceStudyId">${sources.map(s=>`<option value="${this.html(s.id)}">${this.html(s.title)}</option>`).join('')}</select></label>`,
      f=>this.ctx.mutate('accumulation_add_source',{studyId:this.study().id,sourceStudyId:f.get('sourceStudyId')}),'Добавить граф');
  }
  representationHtml(ref) {
    const {source,node}=this.fromRef(ref);if(!source||!node)return '';
    const edges=source.snapshot.edges.filter(e=>e.from===node.id||e.to===node.id);
    return `<h4>${this.html(source.snapshot.title)} · ${this.html(this.name(node))}</h4><p>${this.html(node.notes)}</p><small>Исходный ID ${this.html(node.id)} · ${edges.length} инцидентных рёбер</small><ul>${edges.slice(0,12).map(e=>`<li>${this.html(this.endpointLabel(source.snapshot,e.from))} → ${this.html(this.endpointLabel(source.snapshot,e.to))} · ${this.html(this.edgeName(e))}</li>`).join('')}</ul>${edges.length>12?'<p>Показаны первые 12; откройте независимый инспектор.</p>':''}<details><summary>Поля исходного представления</summary><pre>${this.html(JSON.stringify(node,null,2))}</pre></details>`;
  }
  originals(id) {
    const refs=this.refs(id);
    this.ctx.dialog('Исходные представления узла',`<label>Исходное представление<select id="accum-original-select">${refs.map(r=>{const x=this.fromRef(r);return `<option value="${this.html(r)}">${this.html(x.source.snapshot.title)} · ${this.html(this.name(x.node))} · ${this.html(x.nid.slice(0,8))}</option>`;}).join('')}</select></label><div id="accum-original-fields"></div><button type="button" id="accum-original-inspect">Открыть окружение исходника</button><h3>Рабочий словарь</h3><p>Добавленное обозначение относится к этому исходному представлению в накоплении; исходное исследование не меняется.</p><label>Новое обозначение<input name="text" required maxlength="1000"></label><label>Пояснение<textarea name="notes"></textarea></label>`,
      f=>this.ctx.mutate('accumulation_alias',{studyId:this.study().id,reference:document.querySelector('#accum-original-select').value,text:f.get('text'),notes:f.get('notes')}),'Добавить обозначение');
    const select=document.querySelector('#accum-original-select'),show=()=>{document.querySelector('#accum-original-fields').innerHTML=this.representationHtml(select.value);};select.onchange=show;show();
    document.querySelector('#accum-original-inspect').onclick=()=>{const x=this.fromRef(select.value);this.openInspector(id,x.sid);document.querySelector('#dialog').close();};
  }
  decisionDialog(pair) {
    if(!this.node(pair.from)||!this.node(pair.to)||pair.from===pair.to)return;
    const left=this.refs(pair.from),right=this.refs(pair.to);
    this.settings().leftRef=left[0];this.settings().rightRef=right[0];this.renderPair();this.save();
    const side=(refs,key)=>`<section><label>Представление ${key==='left'?'слева':'справа'}<select id="accum-pair-${key}-source">${refs.map(r=>{const x=this.fromRef(r);return `<option value="${this.html(r)}">${this.html(x.source.snapshot.title)} · ${this.html(this.name(x.node))}</option>`;}).join('')}</select></label><div id="accum-pair-${key}-fields"></div><button type="button" id="accum-pair-${key}-inspect">Независимое окружение ${key==='left'?'слева':'справа'}</button></section>`;
    this.ctx.dialog('Решение о концептах',`<p>${this.html(this.name(this.node(pair.from)))} ↔ ${this.html(this.name(this.node(pair.to)))}. Решение относится ко всем ${left.length} + ${right.length} исходным представлениям выбранной пары.</p><p>${pair.evidence?.length?this.html(pair.evidence.map(x=>`${x.basis==='designation'?'Словарь':'Техническое название'}: ${x.term}`).join('; ')):'Пара вручную выбрана из инспекторов / полотна.'}</p><div class="accum-pair-contexts">${side(left,'left')}${side(right,'right')}</div><label>Решение<select name="status"><option value="pending">Оставить неопределённым</option><option value="confirmed">Объединить как один концепт</option><option value="rejected">Подтвердить, что это разные концепты</option></select></label><label>Обоснование<textarea name="reason" rows="3"></textarea></label><p>Рёбра сохранят свои ID и источники. Противоречие прежнему отказу отклонит всю операцию. Совпадение слов не подтверждает тождество.</p>`,
      f=>this.ctx.mutate('accumulation_decide',{studyId:this.study().id,leftNode:pair.from,rightNode:pair.to,status:f.get('status'),reason:f.get('reason'),evidence:pair.evidence||[]}),'Сохранить решение');
    for(const key of ['left','right']) {const select=document.querySelector(`#accum-pair-${key}-source`);const show=()=>{document.querySelector(`#accum-pair-${key}-fields`).innerHTML=this.representationHtml(select.value);};select.onchange=show;show();document.querySelector(`#accum-pair-${key}-inspect`).onclick=()=>{this.openInspector(key==='left'?pair.from:pair.to,this.fromRef(select.value).sid);document.querySelector('#dialog').close();};}
  }
  openEdge(id) {
    const candidate=this.index?.candidates.find(e=>e.id===id);if(candidate)return this.decisionDialog(candidate);
    const edge=this.study().edges.find(e=>e.id===id);if(!edge)return;
    const source=this.source(edge.accumulationSourceId),origin=edge.origins[0].snapshot;
    this.ctx.dialog('Исходное содержательное ребро',`<p style="color:${this.color(edge.accumulationSourceId)}">${this.html(source.snapshot.title)}</p><h3>${this.html(this.endpointLabel(source.snapshot,origin.from))} → ${this.html(this.endpointLabel(source.snapshot,origin.to))}</h3><p>${this.html(this.edgeName(origin))}</p><p>${this.html(origin.notes)}</p><p>ID копии: ${this.html(edge.id)}<br>Исходный ID: ${this.html(origin.id)}</p><details><summary>Направление, тип и происхождение</summary><pre>${this.html(JSON.stringify(edge,null,2))}</pre></details>`,undefined);
  }
  renderHistory() {
    const host=this.host.querySelector('#accum-history-content');if(!host)return;
    const decisions=this.study().accumulation.decisions;
    host.innerHTML=decisions.slice().reverse().map(d=>`<article><strong>${d.status==='confirmed'?'Объединено':d.status==='rejected'?'Различны':'Не определено'}</strong> · ${this.html(new Date(d.time).toLocaleString('ru-RU'))}<p>${this.html(d.reason)}</p><small>${d.left.length} ↔ ${d.right.length} исходных представлений · ${this.html(d.id)}</small><details><summary>Исходная пара и свидетельства</summary><pre>${this.html(JSON.stringify(d,null,2))}</pre></details></article>`).join('')||'<p>Решений пока нет.</p>';
  }
  visibility(active) {
    this.active=active;
    for(const w of this.windows.values())w.el.hidden=!active||this.study()?.id!==w.props.studyId;
  }
  openInspector(id,source='all') {
    if(!this.node(id))return;
    const prefs=this.settings(),offset=(prefs.windows.length%5)*26,height=Math.min(570,innerHeight-60);
    const props={id:'acc-inspector-'+crypto.randomUUID(),studyId:this.study().id,reference:this.refs(id)[0],selectedRef:this.refs(id)[0],depth:1,source,mode:'graph',frames:[],pinned:false,
      x:Math.min(80+offset,Math.max(12,innerWidth-448)),y:Math.max(0,Math.min(120+offset,innerHeight-height-8)),width:Math.min(440,innerWidth-24),height};
    prefs.windows.push(props);this.buildWindow(props);this.renderWindow(this.windows.get(props.id));this.save();
  }
  async refreshWindows() {
    const s=this.study();if(!s?.accumulation)return;
    for(const props of this.settings().windows||[]) {
      if(!this.windows.has(props.id))this.buildWindow(props);
      const w=this.windows.get(props.id);w.el.hidden=!this.active;
      if(props.pinned)this.host.querySelector('#accum-dock').append(w.el);
      if(!w.el.hidden)await this.renderWindow(w);
    }
    for(const w of this.windows.values())if(w.props.studyId!==s.id)w.el.hidden=true;
  }
  buildWindow(props) {
    const el=document.createElement('section');el.className='accum-inspector';el.id=props.id;el.setAttribute('aria-label','Независимый инспектор окружения');
    el.innerHTML=`<header class="accum-window-handle"><strong class="accum-window-title"></strong><button data-pin title="Закрепить / открепить">Закрепить</button><button data-close aria-label="Закрыть инспектор">×</button></header>
      <div class="accum-window-controls"><label>Глубина<input data-depth type="number" min="0" step="1" aria-label="Глубина инспектора"></label><label>Источники окружения<select data-source aria-label="Источники окружения"></select></label><label>Представление<select data-mode aria-label="Представление инспектора"><option value="graph">Графическое</option><option value="text">Текстовое</option></select></label><button data-nav-back>Назад в инспекторе</button><button data-nav-selected>Окружение выбранного</button><button data-fit>Вписать окружение</button><button data-center>К выбранному</button><button data-zoom-out aria-label="Уменьшить окружение">−</button><button data-zoom-in aria-label="Увеличить окружение">＋</button><span data-zoom></span></div>
      <div id="${props.id}-graph" class="graph accum-window-graph" aria-label="Локальный подграф инспектора"></div><div class="accum-window-text" hidden></div><p class="accum-window-caption"></p><div class="accum-window-selection"></div>`;
    const w={el,props,request:0,textPage:0};this.windows.set(props.id,w);
    (props.pinned?this.host.querySelector('#accum-dock'):document.body).append(el);this.placeWindow(w);
    const handle=el.querySelector('.accum-window-handle');
    handle.onpointerdown=e=>{if(e.button!==0||props.pinned||e.target.closest('button'))return;e.preventDefault();w.drag={x:e.clientX,y:e.clientY,oldX:props.x,oldY:props.y};el.style.zIndex=String((this.zIndex=(this.zIndex||60)+1));handle.setPointerCapture(e.pointerId);};
    handle.onpointermove=e=>{if(!w.drag)return;props.x=Math.max(0,Math.min(innerWidth-90,w.drag.oldX+e.clientX-w.drag.x));props.y=Math.max(0,Math.min(innerHeight-40,w.drag.oldY+e.clientY-w.drag.y));el.style.left=props.x+'px';el.style.top=props.y+'px';};
    handle.onpointerup=e=>{if(!w.drag)return;w.drag=null;if(handle.hasPointerCapture(e.pointerId))handle.releasePointerCapture(e.pointerId);this.save();};
    handle.onpointercancel=()=>{if(w.drag){props.x=w.drag.oldX;props.y=w.drag.oldY;w.drag=null;this.placeWindow(w);}};
    el.querySelector('[data-pin]').onclick=()=>{props.pinned=!props.pinned;(props.pinned?this.host.querySelector('#accum-dock'):document.body).append(el);this.placeWindow(w);this.save();};
    el.querySelector('[data-close]').onclick=()=>{const settings=this.ctx.ui().accumulations[props.studyId];settings.windows=settings.windows.filter(x=>x.id!==props.id);w.graph?.observer.disconnect();w.resizeObserver.disconnect();el.remove();this.windows.delete(props.id);this.save();};
    const depthInput=el.querySelector('[data-depth]');
    const applyDepth=()=>{const depth=Number(depthInput.value);if(!depthInput.value||!Number.isInteger(depth)||depth<0){this.ctx.toast('Глубина — целое число от 0.',true);depthInput.value=props.depth;return;}if(depth===props.depth)return;props.depth=depth;w.textPage=0;this.renderWindow(w);this.save();};
    depthInput.onchange=applyDepth;depthInput.oninput=()=>{clearTimeout(w.depthTimer);w.depthTimer=setTimeout(applyDepth,140);};depthInput.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();clearTimeout(w.depthTimer);applyDepth();}};
    el.querySelector('[data-source]').onchange=e=>{props.source=e.target.value;w.textPage=0;this.renderWindow(w);this.save();};
    el.querySelector('[data-mode]').onchange=e=>{props.mode=e.target.value;this.renderWindowMode(w);this.save();};
    el.querySelector('[data-nav-back]').onclick=()=>{const frame=props.frames.pop();if(!frame)return;Object.assign(props,frame.props);w.restoreCamera=frame.camera;this.renderWindow(w);this.save();};
    el.querySelector('[data-nav-selected]').onclick=()=>{
      if(!props.selectedRef||props.selectedRef===props.reference)return;
      if(props.source==='all'){this.ctx.toast('Для продолжения маршрута выберите один исходный граф. Совместный показ — отдельные окружения.');return;}
      const selected=this.currentId(props.selectedRef),source=this.source(props.source);
      if(!this.node(selected)?.origins.some(o=>o.studyId===source.studyId)){this.ctx.toast('Выбранный узел не относится к выбранному источнику.');return;}
      props.frames.push({props:{reference:props.reference,selectedRef:props.selectedRef,source:props.source,depth:props.depth},camera:w.graph?.snapshot().camera});props.reference=props.selectedRef;w.textPage=0;this.renderWindow(w);this.save();
    };
    el.querySelector('[data-fit]').onclick=()=>w.graph?.fit();el.querySelector('[data-center]').onclick=()=>w.graph?.center(this.currentId(props.selectedRef));
    el.querySelector('[data-zoom-out]').onclick=()=>w.graph?.zoom(1/1.2);el.querySelector('[data-zoom-in]').onclick=()=>w.graph?.zoom(1.2);
    w.resizeObserver=new ResizeObserver(()=>{if(props.pinned||el.hidden)return;const width=Math.round(el.getBoundingClientRect().width),height=Math.round(el.getBoundingClientRect().height);if(width&&height&&(props.width!==width||props.height!==height)){props.width=width;props.height=height;this.save();}});w.resizeObserver.observe(el);
  }
  placeWindow(w) {
    const {el,props}=w;el.classList.toggle('pinned',props.pinned);el.querySelector('[data-pin]').textContent=props.pinned?'Открепить':'Закрепить';
    el.style.left=props.pinned?'':props.x+'px';el.style.top=props.pinned?'':props.y+'px';el.style.width=props.pinned?'':props.width+'px';el.style.height=props.height+'px';
  }
  async renderWindow(w) {
    if(this.study()?.id!==w.props.studyId||!this.active)return;
    const props=w.props,s=this.study(),anchor=this.currentId(props.reference);if(!anchor){w.el.querySelector('.accum-window-caption').textContent='Исходное представление отсутствует в этой версии истории.';return;}
    const selected=this.currentId(props.selectedRef)||anchor,query=new URLSearchParams({study:s.id,node:anchor,depth:String(props.depth)});if(props.source!=='all')query.append('source',props.source);
    const seq=++w.request;
    try {
      const data=await this.ctx.api('/api/accumulation-neighbourhood?'+query);
      if(seq!==w.request||this.study()?.id!==props.studyId)return;
      w.data=data;w.el.querySelector('.accum-window-title').textContent=`${this.name(this.node(anchor))} · окружение`;
      w.el.querySelector('[data-depth]').value=props.depth;
      const sourceSelect=w.el.querySelector('[data-source]');sourceSelect.innerHTML=`<option value="all">Все · независимые обходы</option>${s.accumulation.sources.map(source=>`<option value="${this.html(source.studyId)}">${this.html(source.snapshot.title)}</option>`).join('')}`;sourceSelect.value=props.source;
      w.el.querySelector('[data-mode]').value=props.mode;w.el.querySelector('[data-nav-back]').disabled=!props.frames.length;
      const host=w.el.querySelector('.accum-window-graph'),key=props.id+':'+s.id;
      if(!w.graph){w.graph=new GraphView(host,{canInteract:()=>true,
        select:id=>{props.selectedRef=this.refs(id)[0];this.renderWindowSelection(w);w.graph.update(s,w.graphData,id);this.save();},
        editNode:id=>{props.selectedRef=this.refs(id)[0];this.renderWindowSelection(w);},
        editEdge:id=>this.openEdge(id),savePosition:async()=>{},error:e=>this.ctx.toast(e.message,true),
        changed:snapshot=>{this.ctx.ui().graphs[key]=snapshot;this.save();},cameraChanged:c=>{w.el.querySelector('[data-zoom]').textContent=Math.round(c.scale*100)+'%';}});w.graph.restore(this.ctx.ui().graphs[key]);}
      // Local visual positions never edit the accumulated graph's coordinates.
      w.graphData={nodes:data.nodes.map(n=>{const clone={...n};delete clone.x;delete clone.y;return clone;}),edges:this.decoratedEdges(data.edges)};
      const layout=new Map(data.nodes.map((n,i)=>[n.id,{x:(i%4)*220,y:Math.floor(i/4)*100}]));
      w.graph.update(s,w.graphData,selected,new Map(),layout);if(w.restoreCamera){w.graph.setCamera(w.restoreCamera);w.restoreCamera=null;}
      w.el.querySelector('.accum-window-caption').textContent=`Глубина ${props.depth}: показано ${data.nodes.length} из ${data.totalNodes} узлов, ${data.edges.length} из ${data.totalEdges} рёбер. ${data.truncated?'Показ неполный (до 150 узлов / 400 рёбер); уточните источник, глубину или откройте другой узел. ':''}${data.sourceCounts.length===0?'У этого узла нет представления в выбранном источнике. ':''}${data.traversal}`;
      this.renderWindowText(w);this.renderWindowSelection(w);this.renderWindowMode(w);
    } catch(error) { this.ctx.toast(error.message,true); }
  }
  renderWindowSelection(w) {
    const selected=this.currentId(w.props.selectedRef),n=this.node(selected),host=w.el.querySelector('.accum-window-selection');
    host.innerHTML=`<strong>Выбран: ${this.html(this.name(n))}</strong><button data-window-left>В пару слева</button><button data-window-right>В пару справа</button>`;
    host.querySelector('[data-window-left]').onclick=()=>this.pickPair(selected,'left');host.querySelector('[data-window-right]').onclick=()=>this.pickPair(selected,'right');
    w.el.querySelector('[data-nav-selected]').disabled=w.props.reference===w.props.selectedRef;
  }
  renderWindowText(w) {
    const {data,el}=w,host=el.querySelector('.accum-window-text'),start=w.textPage*40;
    const choose=id=>{w.props.selectedRef=this.refs(id)[0];this.renderWindowSelection(w);w.graph.update(this.study(),w.graphData,id);this.save();};
    host.innerHTML=`<details open><summary>Узлы (${data.nodes.length} показано)</summary>${data.nodes.map(n=>`<button data-window-node="${this.html(n.id)}">${this.html(this.name(n))} · ${this.html(n.id.slice(0,8))}</button>`).join('')}</details><h4>Направления / типы / происхождение</h4>${data.edges.slice(start,start+40).map(e=>{const source=this.source(e.accumulationSourceId),original=e.origins[0].snapshot;return `<article style="border-left-color:${this.color(e.accumulationSourceId)}"><strong>${this.html(source.snapshot.title)}</strong><p><button data-window-node="${this.html(e.from)}">${this.html(this.endpointLabel(source.snapshot,original.from))}</button> → <button data-window-node="${this.html(e.to)}">${this.html(this.endpointLabel(source.snapshot,original.to))}</button> · ${this.html(this.edgeName(e))}</p><small>Исходный ID ${this.html(original.id)}<br>ID копии ${this.html(e.id)}</small><details><summary>Поля и происхождение ребра</summary><pre>${this.html(JSON.stringify(e,null,2))}</pre></details></article>`;}).join('')}<div class="pagination"><button data-text-prev ${start?'':'disabled'}>←</button><span>${data.edges.length?`${start+1}–${Math.min(start+40,data.edges.length)}`:'0'} из ${data.edges.length}</span><button data-text-next ${start+40<data.edges.length?'':'disabled'}>→</button></div>`;
    host.querySelectorAll('[data-window-node]').forEach(b=>b.onclick=()=>choose(b.dataset.windowNode));host.querySelector('[data-text-prev]').onclick=()=>{w.textPage--;this.renderWindowText(w);};host.querySelector('[data-text-next]').onclick=()=>{w.textPage++;this.renderWindowText(w);};
  }
  renderWindowMode(w) {
    w.el.querySelector('.accum-window-graph').hidden=w.props.mode!=='graph';w.el.querySelector('.accum-window-text').hidden=w.props.mode!=='text';
  }
};
