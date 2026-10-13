/* K003r GUI on new isolated data; old K003 and K001+K002 must survive unchanged. */
const {chromium}=require('playwright'),{spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),stamp=Date.now(),output=path.join(root,'test-output',`nut-revision-${stamp}`);
const db=path.join(root,'local-data','nut-k003-revision',`browser-${stamp}`,'workspace.sqlite3');
const port=18000+stamp%20000,url=`http://127.0.0.1:${port}`;
const report={date:new Date().toISOString(),node:process.version,scenarios:[],errors:[]};let server,browser,page;
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function start(){server=spawn('python',['-m','app.server','--no-browser','--port',String(port),'--db',db],{cwd:root,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});let log='';server.stdout.on('data',c=>log+=c);server.stderr.on('data',c=>log+=c);for(let i=0;i<100;i++){if(log.includes('http://'))return;if(server.exitCode!==null)throw Error(log);await pause(100);}throw Error(log);}
async function stop(){if(server?.exitCode===null)await new Promise(r=>{server.once('exit',r);server.kill();});}
async function saved(){await page.waitForFunction(()=>!document.body.classList.contains('busy'));await page.locator('#save-status').filter({hasText:'Сохранено'}).waitFor();}
async function snapshot(){return await (await fetch(url+'/api/state')).json();}
async function selectStudy(id){if(!await page.locator('#studies').isVisible())await page.locator('#toggle-studies').click();await page.locator(`[data-study="${id}"]`).click();await saved();}
async function submit(name){await page.locator('#modal-form').getByRole('button',{name,exact:true}).click();await page.locator('#dialog').waitFor({state:'hidden'});await saved();}
async function stage(file){await page.locator('[data-view="exchange"]').click();await page.locator('#import-file').setInputFiles(file);await page.waitForFunction(()=>document.querySelector('#import-text').value.length>0);await page.locator('#stage-import').click();await submit('Добавить в очередь');await page.waitForFunction(()=>!document.querySelector('#select-proposals').disabled);}
(async()=>{
  await fs.mkdir(output,{recursive:true});
  const file=path.join(root,'data/experiments/nut/nut-revised.json'),doc=JSON.parse(await fs.readFile(file,'utf8')),study=doc.state.studies[0],sid=study.id;
  const audit=JSON.parse(await fs.readFile(path.join(root,'data/experiments/nut/revision-audit.json'),'utf8'));
  const setup=spawnSync('python',['-c',`
import json,sys
from pathlib import Path
from app.store import Store
from scripts.verify_nut import accept
s=Store(Path(sys.argv[1]))
for file in ['data/experiments/nut/nut.json','data/experiments/accumulation/k001-k002-workspace.json']:
 accept(s,json.loads(Path(file).read_text(encoding='utf-8')))
`,db],{cwd:root,encoding:'utf8',windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});assert.equal(setup.status,0,setup.stderr);
  await start();browser=await chromium.launch({channel:'chrome',headless:true});report.browser=browser.version();
  page=await browser.newPage({viewport:{width:1600,height:1100}});page.on('pageerror',e=>report.errors.push(e.message));
  await page.goto(url);await saved();const original=(await snapshot()).state.studies;
  await stage(file);assert.deepEqual((await snapshot()).state.studies,original);
  report.importCandidates=(await snapshot()).state.proposals.filter(p=>p.status==='pending').length;assert.equal(report.importCandidates,92);
  await page.locator('#select-proposals').click();await page.locator('#accept-proposals').click();await submit('Принять');
  assert.deepEqual((await snapshot()).state.studies.find(s=>s.id===sid),study);
  report.scenarios.push('GUI preview / 92 candidates / atomic separate import preserves the entire revised study');
  await selectStudy(sid);await page.locator('#fit-graph').click();
  assert.equal(await page.locator('#graph [data-graph-node]').count(),45);assert.equal(await page.locator('#graph [data-graph-edge]').count(),45);
  const titles=await page.locator('#graph [data-graph-node] title').allTextContents();assert(titles.every(t=>/^[а-яё]+\n$/.test(t)));
  assert((await page.locator('#graph .edge-label').allTextContents()).every(t=>t===''));
  await page.screenshot({path:path.join(output,'full.png'),fullPage:true});
  report.scenarios.push('all 45 single-word conceptual entries visible, 45 arrows, no hidden note descriptions');
  if(!await page.locator('#node-list').isVisible())await page.locator('#toggle-elements').click();
  await page.locator('#graph-mode').selectOption('neighborhood');await page.locator('#graph-depth').fill('2');await page.locator('#graph-depth').dispatchEvent('change');
  await page.locator('#center-root').click();await page.locator('#fit-graph').click();await page.screenshot({path:path.join(output,'root.png'),fullPage:true});
  await page.locator(`#node-list [data-node="${audit.nodeIds['контакт']}"]`).click();await page.locator('#graph-depth').fill('1');await page.locator('#graph-depth').dispatchEvent('change');
  await page.locator('#fit-graph').click();assert.equal(await page.locator('#graph [data-graph-node]').count(),4);
  const visible=await page.locator('#graph [data-graph-node]').evaluateAll(gs=>gs.map(g=>g.dataset.graphNode));
  assert.deepEqual(new Set(visible),new Set(['контакт','резьба','опора','трение'].map(n=>audit.nodeIds[n])));
  await page.locator('#quick-edit').click();assert.equal(await page.locator('#node-form [name="notes"]').inputValue(),'');assert.equal(await page.locator('#node-form [name="label"]').inputValue(),'контакт');
  await page.locator('#fit-graph').click();
  await page.screenshot({path:path.join(output,'contact.png'),fullPage:true});
  report.scenarios.push('local neighborhood shares contact / friction without context-specific duplicates, notes field empty');
  const promise=page.waitForEvent('download');await page.locator('#export-study').click();const download=await promise;const exported=path.join(output,'export.json');await download.saveAs(exported);
  assert.deepEqual(JSON.parse(await fs.readFile(exported,'utf8')).state.studies[0],study);
  await stage(file);assert.equal((await snapshot()).state.proposals.filter(p=>p.status==='pending').length,0);
  report.scenarios.push('real complete GUI export exactly equal; repeated import creates no candidates');
  await selectStudy(sid);await page.locator('#center-root').click();await page.locator('#quick-edit').click();const before=await snapshot();
  await page.locator('#node-form [name="label"]').fill('проба');await page.locator('#node-form button[type="submit"]').click();await saved();
  await page.locator('[data-view="history"]').click();await page.locator(`[data-restore="${before.revision}"]`).click();await submit('Восстановить');assert.deepEqual((await snapshot()).state,before.state);
  report.scenarios.push('GUI history restores exact complete pre-edit workspace');
  await stop();await start();await page.reload();await saved();await selectStudy(sid);
  const final=(await snapshot()).state;assert.deepEqual(final.studies.find(s=>s.id===sid),study);assert(original.every(s=>final.studies.some(x=>x.id===s.id&&JSON.stringify(s)===JSON.stringify(x))));
  assert(final.studies.filter(s=>s.accumulation).every(s=>s.accumulation.sources.length===2));assert.deepEqual(final.matches,[]);assert.deepEqual(report.errors,[]);
  report.scenarios.push('new server / reload: historical K003 and two-source canvas unchanged, no revised accumulation or identity decisions');
})().catch(async e=>{report.failure=e.stack;process.exitCode=1;await page?.screenshot({path:path.join(output,'failure.png'),fullPage:true});}).finally(async()=>{
  await fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2)+'\n');await browser?.close();await stop();console.log(JSON.stringify({output,scenarios:report.scenarios,failure:report.failure}));
});
