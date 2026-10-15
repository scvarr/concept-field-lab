/* Reproducible operator workflow through real Chrome forms; isolated SQLite only. */
const {chromium}=require('playwright'),{spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),stamp=Date.now(),out=path.join(root,'test-output',`graph-editor-${stamp}`),port=52100+stamp%3000,url=`http://127.0.0.1:${port}`;
const report={date:new Date().toISOString(),node:process.version,scenarios:[],negative:[],errors:[],scope:'Синтетические операторские структуры; семантический анализ не реализуется и не проверяется'};
let server,browser,page,second;const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function start(db){server=spawn('python',['-m','app.server','--no-browser','--port',String(port),'--db',db],{cwd:root,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});let log='';server.stdout.on('data',c=>log+=c);server.stderr.on('data',c=>log+=c);for(let i=0;i<100;i++){if(log.includes('http://'))return;if(server.exitCode!==null)throw Error(log);await pause(100);}throw Error(log);}
async function stop(){if(server?.exitCode===null)await new Promise(r=>{server.once('exit',r);server.kill();});}
async function state(){return (await(await fetch(url+'/api/state')).json()).state;}
const helpers=()=>require('./canvas-browser-helpers.cjs')(page);
async function click(s){await helpers().click(s);}
async function submit(text){await helpers().submit(text);}
async function form(text){await page.locator('#modal-form').getByRole('button',{name:text,exact:true}).click();await helpers().saved();}
async function apply(){await page.locator('#modal-form [name=confirmed]').check();await submit('Применить изменения');}
async function exact(id){await click('#graph-editor');await page.locator('#edit-exact-id').fill(id);await click('#edit-exact');}
async function editNotes(id,text){await exact(id);await page.locator('[name=notes]').fill(text);await form('Предпросмотр');await apply();}
async function usePart(){await click('#go-graph');await page.locator('#graph-search').fill('part');await click('[data-global-node="part"]');}
async function importFile(file){await click('#workspace-tools');await page.locator('#global-import-file').setInputFiles(file);await click('#global-import-preview');await page.locator('[name=confirmed]').check();await submit('Импортировать');}
async function exportFile(file){await click('#workspace-tools');const promise=page.waitForEvent('download');await click('#global-export');await(await promise).saveAs(file);await click('#modal-close');}
async function expectError(text,before){await page.locator('#toast.error').filter({hasText:text}).waitFor();if(before)assert.deepEqual(await state(),before);report.negative.push(text);}
async function addExisting(id){await click('#def-search-open');await page.locator('#def-search').fill(id);await page.locator(`[data-def-use="${id}"]`).click();await helpers().saved();}
(async()=>{
  await fs.mkdir(out,{recursive:true});const fixture=path.join(out,'fixture.json'),db=path.join(out,'workspace.sqlite3');
  const setup=spawnSync('python',['-m','scripts.unified_editor_fixture',path.join(out,'fixture.sqlite3'),fixture],{cwd:root,windowsHide:true,encoding:'utf8',env:{...process.env,PYTHONUTF8:'1'}});assert.equal(setup.status,0,setup.stderr);
  await start(db);browser=await chromium.launch({channel:'chrome',headless:true});report.browser=browser.version();
  page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>report.errors.push(e.message));
  await page.route('**/api/definitions?*',r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({lemma:'',senses:[],status:'unavailable',message:'В технической проверке используется ручной ввод.'})}));
  await page.goto(url+'/?compat=m018');await helpers().saved();await importFile(fixture);const baseline=await state();assert.equal(Object.keys(baseline.definitionPublications).length,4);
  report.scenarios.push('Через GUI импортированы четыре опубликованных определения: винт и гайка используют общий ID детали, компоненты α и межопределительный контекст рёбер.');
  // Build the replacement structure at the existing part ID in the mini graph.
  await usePart();await page.locator('#graph-depth').fill('0');await click('#graph-editor');await click('#edit-choose-region');for(const box of await page.locator('[name=region-node]').all())await box.setChecked((await box.getAttribute('value'))==='part');await page.locator('#region-search').fill('part');await submit('Открыть область');const regionId=(await page.locator('#def-open').inputValue());
  await addExisting('mechanism');await addExisting('elementary');await click('#def-fit');
  await helpers().connect('part','mechanism');await helpers().connect('part','elementary');
  await helpers().openNode('part');await click('#node-properties');await page.locator('[name=notes]').fill('Подготовлено в области');await submit('Сохранить характеристики');
  assert.equal((await state()).edges.length,baseline.edges.length);await click('#def-preview');assert((await page.locator('#dialog').innerText()).includes('definition-part'));await page.locator('[name=confirmed]').check();await submit('Применить область');
  let s=await state();assert.equal(s.edges.length,baseline.edges.length+2);assert.equal(s.nodes.find(n=>n.id==='part').notes,'Подготовлено в области');const structureEdges=s.edges.filter(e=>e.from==='part').map(e=>e.id);
  report.scenarios.push('Область сохраняет существующий ID части; два отношения и характеристики общего узла применены из миниграфа одной транзакцией.');
  await click('#go-graph');await editNotes('part','Из общего графа');await click('#go-builder');await helpers().openNode('part');assert((await page.locator('#dialog').innerText()).includes('Из общего графа'));await click('#modal-close');
  assert.equal((await state()).definitionDrafts.find(d=>d.id===regionId).nodes.find(n=>n.id==='part').notes,'Из общего графа');
  report.scenarios.push('Прямая общая правка обновляет чистый миниграф; оба представления показывают один канонический узел.');
  // Selective redirect first; no other uses or designation may change.
  await click('#go-graph');await click('#graph-editor');await page.locator('#edit-object').selectOption('detail');await click('#edit-uses');
  assert((await page.locator('#dialog').innerText()).includes('Винт'));assert((await page.locator('#dialog').innerText()).includes('Гайка'));
  await page.locator('[name=target]').selectOption('part');await page.locator('[name=use][value="screw-detail|to"]').check();await form('Предпросмотр преобразования');
  await page.locator('[name=confirmed]').waitFor();await page.screenshot({path:path.join(out,'selective-preview.png')});await apply();
  s=await state();assert.equal(s.edges.find(e=>e.id==='screw-detail').to,'part');assert.equal(s.edges.find(e=>e.id==='nut-detail').to,'detail');assert.equal(s.designations.find(d=>d.id==='word-detail').target,'detail');assert.deepEqual(s.contextEdges,baseline.contextEdges);
  report.scenarios.push('Выборочное перенаправление меняет ровно один конец ребра; гайка, состав α, обозначения и контекстные ID сохранены.');
  // The attempted delete must reject while dependencies remain, without changing anything.
  await exact('detail');const beforeReject=await state();await click('#edit-delete');await form('Предпросмотр удаления');await expectError('два концептуальных ID',beforeReject);await click('#modal-cancel');
  // Complete the remaining redirect + designation rebind + direct definition uses + source delete.
  await click('#graph-editor');await page.locator('#edit-object').selectOption('detail');await click('#edit-uses');await page.locator('[name=target]').selectOption('part');
  for(const input of await page.locator('[name=use],[name=definition],[name=designation]').all())await input.check();await page.locator('[name=deleteSource]').check();
  await form('Предпросмотр преобразования');await page.locator('[name=confirmed]').waitFor();const previewText=await page.locator('#dialog').innerText();for(const word of ['screw-detail-component','nut-detail-component','context-cross','word-detail','definition-screw','definition-nut'])assert(previewText.includes(word),word);
  await page.screenshot({path:path.join(out,'conversion-preview.png')});await apply();s=await state();await fs.writeFile(path.join(out,'conversion.json'),JSON.stringify(s,null,2));
  assert(!s.nodes.some(n=>n.id==='detail'));assert.equal(s.designations.find(d=>d.id==='word-detail').target,'part');assert.deepEqual(s.contextEdges,baseline.contextEdges);assert.deepEqual(s.edges.map(e=>e.id).sort(),[...baseline.edges.map(e=>e.id),...structureEdges].sort());
  assert.deepEqual(s.edges.filter(e=>e.role==='component').map(e=>[e.id,e.to]).sort(),[['nut-detail-component','part'],['screw-detail-component','part']]);
  for(const p of Object.values(s.definitionPublications))assert(!p.nodeIds.includes('detail'));
  await usePart();await page.screenshot({path:path.join(out,'converted-graph.png')});report.scenarios.push('Полное преобразование детали в структуру существующей части: выбранные использования и обозначение перенаправлены, исходник удалён, ID отношений, компонентов и контекста сохранены; лишних связей нет.');
  // Ordinary and context edit/create/delete; negative dependency and duplicate pair cases.
  await exact('screw-detail');await page.locator('[name=type]').fill('Проверка общего отношения');await form('Предпросмотр');await apply();
  await exact('screw-detail');const beforeEdgeReject=await state();await click('#edit-delete');await expectError('Контекст полотна',beforeEdgeReject);await click('#modal-cancel');
  await exact('context-cross');await page.locator('[name=from]').selectOption('nut-detail');await page.locator('[name=to]').selectOption('screw-detail');await form('Предпросмотр');await apply();
  assert.equal((await state()).contextEdges.find(c=>c.id==='context-cross').from,'nut-detail');
  await exact('context-cross');await click('#edit-delete');await apply();assert(!(await state()).contextEdges.some(c=>c.id==='context-cross'));
  await click('#graph-editor');await click('#edit-create-context');await page.locator('[name=from]').selectOption('screw-detail');await page.locator('[name=to]').selectOption('nut-detail');await form('Предпросмотр');await apply();
  await click('#graph-editor');await click('#edit-create-context');await page.locator('[name=from]').selectOption('screw-detail');await page.locator('[name=to]').selectOption('nut-detail');const beforeDuplicate=await state();await form('Предпросмотр');await expectError('Контекст полотна',beforeDuplicate);await click('#modal-cancel');
  report.scenarios.push('Общее отношение редактируется с прежним ID; контекст разворачивается, удаляется и создаётся; удаление используемого ребра и повтор пары отклонены атомарно.');
  await click('#graph-editor');await click('#edit-create-edge');await page.locator('[name=from]').selectOption('mechanism');await page.locator('[name=to]').selectOption('elementary');await form('Предпросмотр');await apply();
  const directEdge=(await state()).edges.find(e=>e.from==='mechanism'&&e.to==='elementary');assert(directEdge);
  await exact(directEdge.id);await page.locator('[name=from]').selectOption('elementary');await page.locator('[name=to]').selectOption('mechanism');await form('Предпросмотр');await apply();assert.equal((await state()).edges.find(e=>e.id===directEdge.id).from,'elementary');
  await exact(directEdge.id);await click('#edit-delete');await apply();assert(!(await state()).edges.some(e=>e.id===directEdge.id));
  report.scenarios.push('Создание общего отношения, изменение концов и удаление проходят через preview; при правке ID сохраняется.');
  const beforeTemporary=await state();await click('#graph-editor');await click('#edit-create-node');await page.locator('[name=designation]').fill('Временный концепт');await form('Предпросмотр');await apply();
  const temporaryConcept=(await state()).nodes.find(n=>!beforeTemporary.nodes.some(v=>v.id===n.id));assert(temporaryConcept);
  await click('#graph-editor');await click('#edit-create-edge');await page.locator('[name=from]').selectOption('part');await page.locator('[name=to]').selectOption(temporaryConcept.id);await form('Предпросмотр');await apply();
  const temporaryRelation=(await state()).edges.find(e=>e.to===temporaryConcept.id);await click('#graph-editor');await click('#edit-create-context');await page.locator('[name=from]').selectOption(temporaryRelation.id);await page.locator('[name=to]').selectOption('screw-detail');await form('Предпросмотр');await apply();
  await exact(temporaryConcept.id);await click('#edit-delete');await click('#delete-select-all');await form('Предпросмотр удаления');await apply();
  const afterTemporary=await state();for(const key of ['nodes','edges','contextEdges','designations'])assert.deepEqual(afterTemporary[key],beforeTemporary[key]);
  report.scenarios.push('Общий концепт, его обозначение, отношение и контекстная пара удалены одной транзакцией после явного выбора зависимостей; остальные объекты совпали точно.');


  // Create alpha directly with a reused component, update membership, then delete it safely.
  await click('#graph-editor');await click('#edit-create-node');await page.locator('[name=structure]').selectOption('alpha');const beforeEmpty=await state();await form('Предпросмотр');await expectError('хотя бы один',beforeEmpty);
  await page.locator('[name=component][value=part]').check();await form('Предпросмотр');await apply();s=await state();const temporary=s.nodes.find(n=>!baseline.nodes.some(v=>v.id===n.id));assert(temporary?.structure==='alpha');
  await exact(temporary.id);await page.locator('[name=structure]').selectOption('concept');await page.locator('[name=component][value=part]').uncheck();await form('Предпросмотр');await apply();await exact(temporary.id);await click('#edit-delete');await apply();
  report.scenarios.push('Безымянная α создаётся с существующим ID компонента; пустая α отклонена; α преобразуется в концепт и удаляется после явного просмотра.');
  // Keep a dirty mini graph intact when a second browser tab edits a shared object.
  await usePart();await page.locator('#graph-depth').fill('0');await click('#graph-region');const dirtyId=await page.locator('#def-open').inputValue();await helpers().openNode('part');await click('#node-properties');await page.locator('[name=notes]').fill('Незавершённая локальная правка');await submit('Сохранить характеристики');
  second=await browser.newPage({viewport:{width:1440,height:1000}});second.on('pageerror',e=>report.errors.push(e.message));await second.goto(url);const first=page;page=second;await helpers().saved();await click('#go-graph');await editNotes('part','Более свежая общая правка');page=first;await page.reload();await helpers().saved();
  s=await state();const dirty=s.definitionDrafts.find(d=>d.id===dirtyId);assert.equal(dirty.nodes.find(n=>n.id==='part').notes,'Незавершённая локальная правка');assert(dirty.graphStale);await click('#def-preview');await expectError('Общий граф изменён');await page.screenshot({path:path.join(out,'stale-draft.png')});
  report.scenarios.push('Вторая вкладка меняет общий узел; незавершённый миниграф сохранён и после reload не может перезаписать свежие данные.');
  // Preview itself must become invalid if another tab writes after it was shown.
  await click('#go-graph');await exact('part');await page.locator('[name=notes]').fill('Устаревший preview');await form('Предпросмотр');page=second;await editNotes('part','После preview');page=first;const beforeStale=await state();await page.locator('[name=confirmed]').check();await form('Применить изменения');await expectError('другой вкладке',beforeStale);await click('#modal-cancel');await page.reload();await helpers().saved();
  report.scenarios.push('Preview, устаревший после транзакции другой вкладки, отклонён без записи состояния и истории.');
  await click('#go-builder');await page.locator('#def-open').selectOption(regionId);await helpers().saved();await click('#def-search-open');await click('#def-add-alpha');const unfinished=(await state()).definitionDrafts.find(d=>d.id===regionId),unpublished=unfinished.nodes.find(n=>!(s.nodes.some(v=>v.id===n.id)));assert(unpublished);assert(!(await state()).nodes.some(n=>n.id===unpublished.id));await click('#def-preview');await expectError('хотя бы один');
  report.scenarios.push('Незавершённая α остаётся в черновике и не попадает в постоянный граф.');
  // Full history, restart and import roundtrip via GUI.
  await click('#go-graph');const file=path.join(out,'permanent.json');await exportFile(file);const document=JSON.parse(await fs.readFile(file,'utf8'));const canonical=document.state;
  await stop();await start(db);await page.reload();await helpers().saved();assert.deepEqual(await state(),canonical);
  await stop();await start(path.join(out,'import.sqlite3'));await page.reload();await helpers().saved();await importFile(file);assert.deepEqual(await state(),canonical);
  const reexport=await(await fetch(url+'/api/export')).json();assert(reexport.importedHistory.some(d=>JSON.stringify(d.history)===JSON.stringify(document.history)));await fs.writeFile(path.join(out,'reexport.json'),JSON.stringify(reexport,null,2));
  await click('#workspace-tools');await page.locator('#dialog details').filter({has:page.locator('[data-global-restore]')}).locator('summary').click();await click('[data-global-restore="0"]');await page.locator('[name=confirmed]').check();await submit('Восстановить');assert.equal((await state()).nodes.length,0);assert((await(await fetch(url+'/api/history')).json()).length>=3);
  report.scenarios.push('GUI экспортирует полную историю и защищённые черновики; перезапуск процесса и GUI импорт сохраняют точное состояние и архив; восстановление через GUI создаёт новую версию истории.');
  await importFile(file);await click('#go-graph');for(const width of [600,360]){await page.setViewportSize({width,height:900});await click('#graph-fit');assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:path.join(out,`viewport-${width}.png`),fullPage:true});}
  assert.deepEqual(report.errors,[]);report.ok=true;report.finalCounts={nodes:canonical.nodes.length,edges:canonical.edges.length,contexts:canonical.contextEdges.length,drafts:canonical.definitionDrafts.length};
})().catch(e=>{report.failure=e.stack;process.exitCode=1;}).finally(async()=>{if(page)await page.screenshot({path:path.join(out,'last.png'),fullPage:true}).catch(()=>{});if(browser)await browser.close();await stop();await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({output:out,...report},null,2));});
