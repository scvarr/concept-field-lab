'use strict';
window.CanvasLayoutControls=class {
  constructor(workbench,host) {
    this.w=workbench;this.host=host;this.selected=new Set();this.studyId=workbench.study().id;
    host.innerHTML=`<details id="layout-panel"><summary>Раскладка узлов</summary><div class="layout-controls">
      <label>Способ<select id="layout-algorithm"><option value="force">Силовой</option><option value="hierarchical">Иерархический →</option><option value="radial">Радиальный от выбранного</option><option value="clusters">Кластеры исходных графов</option></select></label>
      <label>Область<select id="layout-scope"><option value="all">Всё полотно, включая скрытые узлы</option><option value="selected">Выбранные узлы</option><option value="source">Исходный граф целиком</option></select></label>
      <label>Исходник<select id="layout-source"></select></label><label>Зазор между узлами<input id="layout-spacing" type="number" min="20" max="400" step="1" value="32"></label>
      <label class="checkbox"><input id="layout-crossings" type="checkbox" checked>Уменьшать пересечения (эвристика)</label>
      <label class="checkbox"><input id="layout-auxiliary" type="checkbox">Учитывать словарные совпадения в геометрии</label></div>
      <p>Ctrl / Shift + щелчок добавляет узел к выбору. Источник и группа выбираются полностью, включая скрытые узлы. Радиальный центр — текущий узел. Снижение пересечений эвристическое.</p>
      <div class="actions"><button id="layout-pick">Добавить текущий узел</button><button id="layout-group">Выбрать группу индекса</button><button id="layout-clear">Очистить выбор</button><button id="layout-pin">Закрепить выбор</button><button id="layout-unpin">Открепить выбор</button></div>
      <p id="layout-selection"></p><div class="actions"><button id="layout-preview" class="primary">Рассчитать предпросмотр</button><button id="layout-fit">Показать результат целиком</button><button id="layout-apply" disabled>Применить</button><button id="layout-cancel" disabled>Отменить</button><button id="layout-undo">Предыдущее расположение</button></div>
      <p id="layout-status" role="status" aria-live="polite">Раскладка запускается только кнопкой.</p></details>`;
    const bind=(id,fn)=>this.el(id).onclick=this.w.ctx.run(fn);
    bind('layout-preview',()=>this.start());bind('layout-apply',()=>this.apply());bind('layout-cancel',()=>this.cancel());
    bind('layout-fit',()=>this.w.fitCanvas());
    bind('layout-pick',()=>this.toggle(this.w.settings().focus,true));bind('layout-clear',()=>{this.selected.clear();this.refresh();this.w.renderCanvas();});
    bind('layout-group',()=>{const g=this.w.index?.groups.find(g=>g.key===this.w.settings().groupKey);if(!g)throw Error('Выберите группу в индексе.');g.nodeIds.forEach(id=>this.selected.add(id));this.el('layout-scope').value='selected';this.refresh();this.w.renderCanvas();});
    bind('layout-pin',()=>this.pin(true));bind('layout-unpin',()=>this.pin(false));
    bind('layout-undo',async()=>{if(this.active())return;await this.w.ctx.mutate('layout_restore',{studyId:this.studyId});this.status('Предыдущее расположение восстановлено одной записью истории.');});
    this.refresh();
  }
  el(id){return this.host.querySelector('#'+id);}
  active(){return !!(this.worker||this.preview);}
  status(text){this.el('layout-status').textContent=text;}
  fingerprint(){const s=this.w.study();return JSON.stringify([s.id,s.nodes,s.edges,s.designations,s.accumulation.sources.map(s=>s.studyId)]);}
  toggle(id,additive=false){if(this.active())return;if(!additive)this.selected.clear();if(this.selected.has(id)&&additive)this.selected.delete(id);else this.selected.add(id);this.refresh();}
  refresh() {
    const s=this.w.study();if(s?.id!==this.studyId)return;
    if(this.active()&&this.signature!==this.fingerprint())this.cancel('Граф изменился: предпросмотр отменён.');
    const ids=new Set(s.nodes.map(n=>n.id));this.selected=new Set([...this.selected].filter(id=>ids.has(id)));
    const source=this.el('layout-source'),value=source.value;source.innerHTML=s.accumulation.sources.map(s=>`<option value="${this.w.html(s.studyId)}">${this.w.html(s.snapshot.title)}</option>`).join('');if([...source.options].some(o=>o.value===value))source.value=value;
    this.el('layout-selection').textContent=`Выбрано ${this.selected.size} узлов · закреплено ${s.nodes.filter(n=>n.layoutPinned).length} на полном полотне.`;
    this.el('layout-preview').disabled=this.active();this.el('layout-apply').disabled=!this.preview;this.el('layout-cancel').disabled=!this.active();this.el('layout-undo').disabled=this.active()||!s.accumulation.lastLayout;
    for(const id of ['layout-pick','layout-group','layout-clear','layout-pin','layout-unpin','layout-algorithm','layout-scope','layout-source','layout-spacing','layout-crossings','layout-auxiliary'])this.el(id).disabled=this.active();
  }
  async pin(pinned){if(this.active())return;if(!this.selected.size)throw Error('Выберите узлы для закрепления.');await this.w.ctx.mutate('layout_pin',{studyId:this.studyId,nodeIds:[...this.selected],pinned});this.refresh();}
  start() {
    if(this.active()||this.w.ctx.busy())throw Error('Дождитесь завершения текущей операции.');
    const s=this.w.study(),scope=this.el('layout-scope').value,source=this.el('layout-source').value;
    const targetIds=scope==='all'?s.nodes.map(n=>n.id):scope==='source'?s.nodes.filter(n=>n.origins.some(o=>o.studyId===source)).map(n=>n.id):[...this.selected];
    if(!targetIds.length)throw Error('Выберите узлы для раскладки.');
    const spacing=Number(this.el('layout-spacing').value);if(!Number.isInteger(spacing)||spacing<20||spacing>400)throw Error('Зазор — целое число от 20 до 400.');
    const nodes=s.nodes.map(n=>({id:n.id,x:n.x,y:n.y,pinned:!!n.layoutPinned,sources:[...new Set(n.origins.map(o=>o.studyId))]}));
    const edges=s.edges.map(e=>({from:e.from,to:e.to}));let auxiliaryCount=0;
    if(this.el('layout-auxiliary').checked) {
      // Derive a complete sparse star for each dictionary group, independently
      // of the visual candidate limit and technical-label index filters.
      const groups=new Map();for(const d of s.designations||[]){const term=d.text.trim().replace(/\s+/g,' ').toLocaleLowerCase('ru');if(!groups.has(term))groups.set(term,new Set());groups.get(term).add(d.target);}
      for(const ids of groups.values()){const list=[...ids];for(let i=1;i<list.length;i++){edges.push({from:list[0],to:list[i]});auxiliaryCount++;}}
    }
    this.algorithm=this.el('layout-algorithm').value;this.signature=this.fingerprint();
    const worker=new Worker('/layout-worker.js');this.worker=worker;this.refresh();this.status(`Расчёт: ${nodes.length} узлов / ${s.edges.length} рёбер, ${auxiliaryCount} словарных пружин…`);
    const stop=()=>{worker.terminate();clearTimeout(this.timeout);if(this.worker===worker)this.worker=null;};
    worker.onmessage=e=>{
      if(this.worker!==worker)return;
      if(e.data.percent!==undefined){this.status(`Расчёт ${e.data.percent}% · полных узлов ${nodes.length}, словарных пружин ${auxiliaryCount}. Камеру можно перемещать.`);return;}
      stop();
      if(e.data.error){this.status('Раскладка не построена: '+e.data.error);this.refresh();return;}
      if(this.signature!==this.fingerprint()){this.cancel('Граф изменился: результат отброшен.');return;}
      this.preview=e.data.result;this.w.renderCanvas();this.refresh();
      this.status(`Предпросмотр: ${this.preview.moved} узлов, расчёт ${(this.preview.elapsedMs/1000).toFixed(3)} с; словарных пружин ${auxiliaryCount}. Координаты ещё не сохранены. Примените или отмените.`);
    };
    worker.onerror=()=>{stop();this.status('Ошибка загрузки / расчёта раскладки.');this.refresh();};
    this.timeout=setTimeout(()=>{stop();this.status('Расчёт остановлен по пределу 30 секунд. Выберите меньшую область или другой способ.');this.refresh();},30000);
    worker.postMessage({nodes,edges,targetIds,algorithm:this.algorithm,spacing,reduceCrossings:this.el('layout-crossings').checked,rootId:this.w.settings().focus});
  }
  cancel(message='Раскладка отменена; сохранённые координаты восстановлены.') {
    this.worker?.terminate();this.worker=null;clearTimeout(this.timeout);this.preview=null;this.refresh();this.w.renderCanvas();this.status(message);
  }
  async apply() {
    if(!this.preview||this.w.ctx.busy())return;
    if(this.signature!==this.fingerprint()){this.cancel('Граф изменился: повторите расчёт.');return;}
    const preview=this.preview;
    try {await this.w.ctx.mutate('layout_positions',{studyId:this.studyId,positions:preview.positions,algorithm:this.algorithm});this.preview=null;this.refresh();this.w.renderCanvas();this.status(`Сохранено ${preview.moved} координат одной записью истории.`);}
    catch(error){this.status('Не удалось применить: '+error.message);throw error;}
  }
  dispose(){this.worker?.terminate();clearTimeout(this.timeout);this.worker=null;this.preview=null;}
};
