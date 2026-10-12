/* K003 GUI exchange and recovery; a new isolated DB, never the user's workspace. */
const {chromium}=require('playwright'),{spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),stamp=Date.now(),output=path.join(root,'test-output',`nut-${stamp}`);
const db=path.join(root,'local-data','nut-k003',`browser-${stamp}`,'workspace.sqlite3');
const port=18000+stamp%20000,url=`http://127.0.0.1:${port}`;
const report={date:new Date().toISOString(),node:process.version,scenarios:[],errors:[]};let server,browser,page;
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function start(){
  server=spawn('python',['-m','app.server','--no-browser','--port',String(port),'--db',db],{cwd:root,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});
  let log='';server.stdout.on('data',c=>log+=c);server.stderr.on('data',c=>log+=c);
  for(let i=0;i<100;i++){if(log.includes('http://'))return;if(server.exitCode!==null)throw Error(log);await pause(100);}throw Error(log);
}
async function stop(){if(server?.exitCode===null)await new Promise(r=>{server.once('exit',r);server.kill();});}
async function saved(){await page.waitForFunction(()=>!document.body.classList.contains('busy'));await page.locator('#save-status').filter({hasText:'Сохранено'}).waitFor();}
async function snapshot(){return await (await fetch(url+'/api/state')).json();}
async function selectStudy(id){if(!await page.locator('#studies').isVisible())await page.locator('#toggle-studies').click();await page.locator(`[data-study="${id}"]`).click();await saved();}
async function submit(name){await page.locator('#modal-form').getByRole('button',{name,exact:true}).click();await page.locator('#dialog').waitFor({state:'hidden'});await saved();}
async function stage(file){await page.locator('[data-view="exchange"]').click();await page.locator('#import-file').setInputFiles(file);await page.waitForFunction(()=>document.querySelector('#import-text').value.length>0);await page.locator('#stage-import').click();await submit('Добавить в очередь');await page.waitForFunction(()=>!document.querySelector('#select-proposals').disabled);}
(async()=>{
  await fs.mkdir(output,{recursive:true});
  const file=path.join(root,'data/experiments/nut/nut.json'),doc=JSON.parse(await fs.readFile(file,'utf8')),study=doc.state.studies[0],sid=study.id;
  const alpha=study.nodes.find(n=>n.structure==='combination');
  // Existing portable canvas is loaded solely to check preservation after K003 is already built.
  const setup=spawnSync('python',['-c',`
import json,sys
from pathlib import Path
from app.store import Store
from scripts.verify_nut import accept
s=Store(Path(sys.argv[1]));accept(s,json.loads(Path('data/experiments/accumulation/k001-k002-workspace.json').read_text(encoding='utf-8')))
`,db],{cwd:root,encoding:'utf8',windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});assert.equal(setup.status,0,setup.stderr);
  await start();browser=await chromium.launch({channel:'chrome',headless:true});report.browser=browser.version();
  page=await browser.newPage({viewport:{width:1600,height:1100}});page.on('pageerror',e=>report.errors.push(e.message));
  await page.goto(url);await saved();const initial=(await snapshot()).state.studies;
  await stage(file);assert.deepEqual((await snapshot()).state.studies,initial);
  const pending=(await snapshot()).state.proposals.filter(p=>p.status==='pending');report.importCandidates=pending.length;
  await page.locator('#select-proposals').click();await page.locator('#accept-proposals').click();await submit('Принять');
  assert.deepEqual((await snapshot()).state.studies.find(s=>s.id===sid),study);
  report.scenarios.push('GUI file import -> preview -> staged candidates -> atomic acceptance, exact graph');
  await selectStudy(sid);await page.locator('#fit-graph').click();await page.screenshot({path:path.join(output,'full.png'),fullPage:true});
  const graph=await page.locator('#graph [data-graph-edge]').evaluateAll(gs=>gs.map(g=>({label:g.querySelector('.edge-label').textContent,arrow:g.querySelector('.edge').getAttribute('marker-end'),class:g.querySelector('.edge').getAttribute('class')})));
  assert.equal(graph.length,41);assert(graph.every(e=>e.label===''&&e.arrow));assert.equal(graph.filter(e=>e.class.includes('component-edge')).length,6);
  if(!await page.locator('#node-list').isVisible())await page.locator('#toggle-elements').click();
  await page.locator(`#node-list [data-node="${alpha.id}"]`).click();
  assert.equal(await page.locator('#graph [data-graph-node]').count(),7);assert.equal(await page.locator('#graph .component-edge').count(),6);
  await page.locator('#quick-edit').click();assert((await page.locator('#inspector').innerText()).includes('геометрия резьбового сопряжения'));
  await page.locator('#fit-graph').click();
  await page.screenshot({path:path.join(output,'alpha.png'),fullPage:true});
  report.scenarios.push('complete 42/41 graph and alpha with six components, vocabulary and unlabelled arrows accessible');
  await selectStudy(sid);await page.locator('#center-root').click();
  const downloadPromise=page.waitForEvent('download');await page.locator('#export-study').click();const download=await downloadPromise,exported=path.join(output,'export.json');await download.saveAs(exported);
  const downloaded=JSON.parse(await fs.readFile(exported,'utf8'));assert.deepEqual(downloaded.state.studies[0],study);
  report.scenarios.push('real GUI download exports the exact complete study with ID, vocabulary, metadata and history');
  await stage(file);assert.equal((await snapshot()).state.proposals.filter(p=>p.status==='pending').length,0);
  report.scenarios.push('repeated GUI import: zero pending candidates, no duplicate graph');
  await selectStudy(sid);await page.locator('#center-root').click();await page.locator('#quick-edit').click();
  const accepted=await snapshot();await page.locator('#node-form [name="notes"]').fill('Изолированная проба восстановления K003');
  await page.locator('#node-form button[type="submit"]').click();await saved();
  assert.notDeepEqual((await snapshot()).state.studies.find(s=>s.id===sid),study);
  await page.locator('[data-view="history"]').click();await page.locator(`[data-restore="${accepted.revision}"]`).click();await submit('Восстановить');
  assert.deepEqual((await snapshot()).state,accepted.state);
  report.scenarios.push('GUI history restore exactly recovers all pre-edit workspace content');
  await stop();await start();await page.reload();await saved();await selectStudy(sid);
  const final=await snapshot();assert.deepEqual(final.state.studies.find(s=>s.id===sid),study);assert(initial.every(s=>final.state.studies.some(x=>x.id===s.id&&JSON.stringify(x)===JSON.stringify(s))));
  assert(final.state.studies.filter(s=>s.accumulation).every(s=>s.accumulation.sources.length===2));assert.deepEqual(final.state.matches,[]);
  report.scenarios.push('new server + reload: K003 persists independently; existing two-source canvas unchanged, no K003 accumulation or identities');
  assert.deepEqual(report.errors,[]);
})().catch(async e=>{report.failure=e.stack;process.exitCode=1;await page?.screenshot({path:path.join(output,'failure.png'),fullPage:true});}).finally(async()=>{
  await fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2)+'\n');await browser?.close();await stop();console.log(JSON.stringify({output,scenarios:report.scenarios,failure:report.failure}));
});
