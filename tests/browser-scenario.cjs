/* Real browser scenario. All workspace writes are made through the UI. */
const { chromium } = require('playwright');
const { spawn } = require('node:child_process');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname,'..');
const url = 'http://127.0.0.1:8876';
let server, browser, page;
const errors=[];
const output = path.join(root,'test-output',`browser-${Date.now()}`);
async function start() {
  server=spawn(process.env.PYTHON || 'python',['-m','app.server','--no-browser','--port','8876','--db',path.join(output,'workspace.sqlite3')],{cwd:root,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});
  let log='';server.stdout.on('data',chunk=>log+=chunk);server.stderr.on('data',chunk=>log+=chunk);
  for(let i=0;i<100;i++){if(log.includes('http://'))return;if(server.exitCode!==null)throw Error(log);await new Promise(r=>setTimeout(r,100));}
  throw Error('Server startup timed out: '+log);
}
async function stop() {if(server&&server.exitCode===null){await new Promise(resolve=>{server.once('exit',resolve);server.kill();});}}
async function modalSubmit(label) {await page.locator('#modal-form').getByRole('button',{name:label,exact:true}).click();await page.locator('#dialog').waitFor({state:'hidden'});await page.waitForFunction(()=>!document.body.classList.contains('busy'));}
async function create(word){await page.locator('#new-study').click();await page.locator('#modal-form [name="title"]').fill(word);await modalSubmit('Создать');await page.locator('#workspace-title').filter({hasText:word}).waitFor();}
async function expand(label,kind,notes){await page.locator('#expand-node').click();await page.locator('#modal-form [name="label"]').fill(label);await page.locator('#modal-form [name="kind"]').fill(kind);await page.locator('#modal-form [name="notes"]').fill(notes);await modalSubmit('Добавить');await page.locator('#inspector h2').filter({hasText:label}).waitFor();}
async function selectPair(left,right){await page.locator('#compare-left-list input').fill(left);await page.locator('#compare-left-list [data-pair-node]').filter({hasText:left}).first().click();await page.locator('#compare-right-list input').fill(right);await page.locator('#compare-right-list [data-pair-node]').filter({hasText:right}).first().click();}
async function decide(status,reason){await page.locator(status==='confirmed'?'#confirm-pair':'#reject-pair').click();await page.locator('#modal-form [name="reason"]').fill(reason);await modalSubmit(status==='confirmed'?'Подтверждено':'Отклонено');}
async function state(){return (await (await fetch(url+'/api/state')).json()).state;}
async function importText(doc){await page.locator('[data-view="exchange"]').click();await page.locator('#import-text').fill(JSON.stringify(doc));await page.locator('#stage-import').click();await modalSubmit('Добавить в очередь');await page.locator('#proposal-summary').waitFor();}
async function acceptAll(conflicts=false){await page.locator('#select-proposals').click();await page.locator('#accept-proposals').click();if(conflicts)await page.locator('#modal-form [name="allowConflicts"]').check();await modalSubmit('Принять');}
(async()=>{
  await fs.mkdir(output,{recursive:true});await start();
  browser=await chromium.launch({channel:process.env.BROWSER_CHANNEL||'chrome',headless:true});
  const context=await browser.newContext({viewport:{width:1550,height:980},permissions:['clipboard-read','clipboard-write']});page=await context.newPage();
  page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error'&&!m.text().includes('favicon'))errors.push(m.text());});
  await page.goto(url);await page.locator('#save-status').filter({hasText:'Сохранено'}).waitFor();
  await create('камень');await expand('твёрдый','свойство','Синтетическое пояснение A');await expand('сопротивление деформации','определение','Синтетическое рекурсивное раскрытие');
  let s=await state();const a=s.studies[0],ar=a.rootId,x=a.nodes.find(n=>n.label==='твёрдый').id,y=a.nodes.find(n=>n.label==='сопротивление деформации').id;
  await page.locator('#link-node').click();await page.locator('#modal-form [name="to"]').fill(ar);await page.locator('#modal-form [name="type"]').fill('поясняется примером');await modalSubmit('Сохранить');
  await create('камня');await expand('твёрдый','свойство','Другое синтетическое пояснение B');await expand('падежная форма','интерпретация','Неподтверждённая демонстрационная интерпретация');
  s=await state();const b=s.studies[1],bx=b.nodes.find(n=>n.label==='твёрдый').id;
  assert.equal(s.matches.length,0);assert.notEqual(x,bx);
  await page.locator('[data-view="compare"]').click();await page.locator('#compare-left').selectOption(a.id);await page.locator('#compare-right').selectOption(b.id);
  await selectPair('твёрдый','твёрдый');await page.locator('#pair-details .field-diff').first().waitFor();await decide('confirmed','Только для проверки механики интерфейса');
  await selectPair('камень','камня');await decide('rejected','Формы не отождествляем автоматически');
  await page.screenshot({path:path.join(output,'comparison.png'),fullPage:true});
  const diffDownload=page.waitForEvent('download');await page.locator('#export-diff').click();const diffFile=await diffDownload;await diffFile.saveAs(path.join(output,'diff.json'));const diff=JSON.parse(await fs.readFile(path.join(output,'diff.json'),'utf8'));assert.equal(diff.aligned.length,1);assert.equal(diff.correspondences.length,2);
  await page.locator('#merge').click();await page.locator('#modal-form [name="title"]').fill('камень + камня — ручной тест');await page.locator('#modal-form [name="match"]').check();await modalSubmit('Создать объединение');
  s=await state();const merged=s.studies[2];assert.equal(merged.nodes.length,5);assert.equal(merged.edges.length,5);const common=merged.nodes.find(n=>n.origins.length===2);assert(common.notes.includes('пояснение A'));assert(common.notes.includes('пояснение B'));assert.equal(s.matches.find(m=>m.leftNode===ar).status,'rejected');
  await page.locator('#node-search').fill('твёрдый');await page.locator('#node-list [data-node]').click();await page.locator('#inspector details').first().click();await page.screenshot({path:path.join(output,'editor.png'),fullPage:true});
  // Export whole study via UI and import it again without duplicating its IDs.
  const studyDownload=page.waitForEvent('download');await page.locator('#export-study').click();const studyFile=await studyDownload;await studyFile.saveAs(path.join(output,'study.json'));const exported=JSON.parse(await fs.readFile(path.join(output,'study.json'),'utf8'));assert.equal(exported.state.studies[0].id,merged.id);assert(exported.history.length>0);
  await importText(exported);assert.equal((await state()).proposals.filter(p=>p.status==='pending').length,0);
  // Clipboard fragment and ChatGPT patch acceptance.
  await page.locator('#export-depth').fill('all');await page.locator('#copy-fragment').click();await page.waitForFunction(async()=>{try{return (await navigator.clipboard.readText()).startsWith('{');}catch{return false;}});const clip=JSON.parse(await page.evaluate(()=>navigator.clipboard.readText()));assert.equal(clip.kind,'fragment');assert.equal(clip.state.studies[0].nodes.length,5);
  const base=common,value={...base,notes:'Предложение ChatGPT; принято в ручном тесте'};
  const patch={format:'concept-field-graph',version:1,kind:'changes',changes:[{operation:'node',studyId:merged.id,base,value}]};
  await importText(patch);await page.locator('[data-inspect-proposal]').click();await page.locator('#modal-close').click();assert.equal((await state()).studies[2].nodes.find(n=>n.id===common.id).notes,common.notes);await acceptAll();assert.equal((await state()).studies[2].nodes.find(n=>n.id===common.id).notes,value.notes);
  await importText(patch);assert.equal((await state()).proposals.filter(p=>p.status==='pending').length,0);
  // Conflict inspection and explicit overwrite.
  const conflictPatch={...patch,changes:[{...patch.changes[0],value:{...base,notes:'Другая версия кандидата'}}]};await importText(conflictPatch);await page.locator('#proposals .tag.rejected').waitFor();await acceptAll(true);assert.equal((await state()).studies[2].nodes.find(n=>n.id===common.id).notes,'Другая версия кандидата');
  // Reject a proposed new node without applying it.
  const rejectedPatch={format:'concept-field-graph',version:1,kind:'changes',changes:[{operation:'node',studyId:merged.id,base:null,value:{id:'rejected-demo-node',label:'Отклонённый кандидат'}}]};await importText(rejectedPatch);await page.locator('#select-proposals').click();await page.locator('#reject-proposals').click();await modalSubmit('Отклонить');assert(!(await state()).studies[2].nodes.some(n=>n.id==='rejected-demo-node'));
  await page.locator('[data-view="history"]').click();await page.locator('.history-entry').first().waitFor();await page.screenshot({path:path.join(output,'history.png'),fullPage:true});
  const savedSnapshot=await state(),savedRevision=(await (await fetch(url+'/api/state')).json()).revision;
  await page.locator('[data-restore="1"]').click();await modalSubmit('Восстановить');assert.equal((await state()).studies.length,1);await page.locator(`[data-restore="${savedRevision}"]`).click();await modalSubmit('Восстановить');assert.deepEqual(await state(),savedSnapshot);
  const before=await state();await stop();await start();await page.reload();await page.locator('#save-status').filter({hasText:'Сохранено'}).waitFor();assert.deepEqual(await state(),before);
  // Continue after restarting a new server process.
  await page.locator(`[data-study="${merged.id}"]`).click();await page.locator('#node-search').fill('твёрдый');await page.locator('#node-list [data-node]').click();await page.locator('#node-form [name="alternatives"]').fill('Продолжение после перезапуска');await page.locator('#node-form button[type="submit"]').click();await page.waitForFunction(()=>!document.body.classList.contains('busy'));assert.equal((await state()).studies[2].nodes.find(n=>n.id===common.id).alternatives,'Продолжение после перезапуска');
  // Large graph import via file, bulk review and bounded rendering; no hand editing thousands of nodes.
  const scaleStart=Date.now();await page.locator('[data-view="exchange"]').click();await page.locator('#import-file').setInputFiles(path.join(root,'test-output','large-graph.json'));await page.waitForFunction(()=>document.querySelector('#import-text').value.length>1000000);await page.locator('#stage-import').click();await modalSubmit('Добавить в очередь');await page.locator('#proposal-summary').filter({hasText:'В очереди 15001'}).waitFor();await acceptAll();await page.locator('#proposal-summary').filter({hasText:'В очереди 0'}).waitFor();
  const large=(await state()).studies.find(s=>s.nodes.length===5000);assert(large);await page.locator(`[data-study="${large.id}"]`).click();await page.locator('#node-search').fill('Элемент 4999');await page.locator('#node-list [data-node]').click();await page.locator('#inspector h2').filter({hasText:'Элемент 4999'}).waitFor();assert(await page.locator('#graph .node').count()<=180);assert(await page.locator('#node-list .node-item').count()<=80);const largeUiSeconds=(Date.now()-scaleStart)/1000;assert(largeUiSeconds<30);await page.screenshot({path:path.join(output,'large-graph.png'),fullPage:true});
  // Unsaved text survives cancelling navigation.
  await page.locator('#node-form [name="notes"]').fill('Несохранённый черновик');page.once('dialog',d=>d.dismiss());await page.locator('[data-view="compare"]').click();assert.equal(await page.locator('#node-form [name="notes"]').inputValue(),'Несохранённый черновик');await page.locator('#node-form button[type="submit"]').click();await page.waitForFunction(()=>!document.body.classList.contains('busy'));
  await page.setViewportSize({width:1000,height:800});await page.screenshot({path:path.join(output,'narrow-editor.png'),fullPage:true});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
  assert.deepEqual(errors,[]);
  await fs.writeFile(path.join(output,'report.json'),JSON.stringify({result:'passed',browser:await browser.version(),node:process.version,scenario:'GUI: recursive creation, cycle, independent study, compare, decisions, merge, study export, duplicate import, clipboard fragment, reviewed patches, conflict, reject, history restore and return, process restart, continued editing, 5000-node file import and bulk acceptance, search and bounded graph, unsaved draft, 1000px layout',large_ui_seconds:largeUiSeconds,studies:(await state()).studies.length,pageErrors:errors},null,2));
  console.log('Browser scenario passed. Evidence: '+output);
})().catch(async e=>{if(page)await page.screenshot({path:path.join(output,'failure.png'),fullPage:true}).catch(()=>{});console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await stop();});
