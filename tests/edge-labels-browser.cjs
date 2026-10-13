/* Acceptance check across real UI surfaces on a new disposable database. */
const {chromium}=require('playwright');
const {spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),stamp=Date.now();
const output=path.join(root,'test-output',`edge-labels-${stamp}`),db=path.join(output,'workspace.sqlite3');
const port=18000+stamp%20000,url=`http://127.0.0.1:${port}`;
const report={date:new Date().toISOString(),node:process.version,scenarios:[],surfaces:[],errors:[]};
let server,browser,page;
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function saved(){await page.waitForFunction(()=>!document.body.classList.contains('busy'));await page.locator('#save-status').filter({hasText:'Сохранено'}).waitFor();}
async function state(){return (await (await fetch(url+'/api/state')).json()).state;}
async function closeDialog(){await page.locator('#modal-cancel').click();}
async function selectStudy(id){if(!await page.locator('#studies').isVisible())await page.locator('#toggle-studies').click();await page.locator(`[data-study="${id}"]`).click();await saved();}
async function inspect(host){
  await page.locator(`${host} [data-graph-edge]`).first().waitFor({state:'attached'});assert(await page.locator(host).first().isVisible());
  const edges=await page.locator(`${host} [data-graph-edge]`).evaluateAll(gs=>gs.map(g=>({
    id:g.dataset.graphEdge,label:g.querySelector('.edge-label').textContent,aria:g.getAttribute('aria-label'),
    title:g.querySelector('title').textContent,tab:g.getAttribute('tabindex'),
    arrow:g.querySelector('.edge').getAttribute('marker-end'),classes:g.querySelector('.edge').getAttribute('class'),
    dash:getComputedStyle(g.querySelector('.edge')).strokeDasharray,color:getComputedStyle(g.querySelector('.edge')).stroke
  })));
  assert(edges.length);for(const e of edges){assert.equal(e.label,'');assert(e.title);assert(e.aria);assert.equal(e.tab,'0');if(!e.classes.includes('candidate-edge'))assert.match(e.arrow,/url\(#arrow-/);else{assert.equal(e.arrow,'');assert.notEqual(e.dash,'none');}}
  report.surfaces.push({host,edges});return edges;
}
(async()=>{
  await fs.mkdir(output,{recursive:true});
  const setup=spawnSync('python',['-c',`
import json,sys
from pathlib import Path
from app.store import Store
from scripts.accumulation_fixture import act,accept,synthetic
s=Store(Path(sys.argv[1]));a=synthetic(s,'Источник A');b=synthetic(s,'Источник B')
alpha=act(s,'add_node',studyId=a['studyId'],label='',structure='combination',notes='Синтетическая alpha')['nodeId']
act(s,'add_edge',studyId=a['studyId'],**{'from':alpha,'to':a['shared'],'role':'component','componentRole':'тестовая грань','type':'включение','notes':'Метаданные не должны исчезнуть'})
edge=next(x for x in s.read()['state']['studies'] if x['id']==a['studyId'])['edges'][-1]['id']
act(s,'add_edge',studyId=a['studyId'],**{'from':a['rootId'],'to':alpha,'type':'состав','notes':'Синтетическое раскрытие'})
canvas=act(s,'create_accumulation',title='UX — подписи',sourceStudyIds=[a['studyId'],b['studyId']])['studyId']
doc=json.loads(Path('data/experiments/accumulation/k001-k002-workspace.json').read_text(encoding='utf-8'));accept(s,doc)
Path(sys.argv[2]).write_text(json.dumps({'a':a,'b':b,'alpha':alpha,'edge':edge,'canvas':canvas,'actual':doc['state']['studies'][0]['id']}),encoding='utf-8')
`,db,path.join(output,'manifest.json')],{cwd:root,encoding:'utf8',windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});
  assert.equal(setup.status,0,setup.stderr);
  const fixture=JSON.parse(await fs.readFile(path.join(output,'manifest.json'),'utf8'));
  server=spawn('python',['-m','app.server','--legacy','--no-browser','--port',String(port),'--db',db],{cwd:root,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});
  let log='';server.stdout.on('data',c=>log+=c);server.stderr.on('data',c=>log+=c);
  for(let i=0;i<100;i++){if(log.includes('http://'))break;if(server.exitCode!==null)throw Error(log);await pause(100);}
  browser=await chromium.launch({channel:'chrome',headless:true});report.browser=browser.version();
  page=await browser.newPage({viewport:{width:1600,height:1100}});page.on('pageerror',e=>report.errors.push(e.message));
  await page.goto(url);await saved();const baseline=await state();
  await selectStudy(fixture.a.studyId);
  const editEdges=await inspect('#graph');assert(editEdges.some(e=>e.classes.includes('component-edge')&&e.dash!=='none'));
  const edge=page.locator(`#graph [data-graph-edge="${fixture.edge}"]`);await edge.focus();await edge.press('Enter');
  await page.locator('#modal-form').waitFor();assert.equal(await page.locator('#modal-form [name="type"]').inputValue(),'включение');
  assert.equal(await page.locator('#modal-form [name="componentRole"]').inputValue(),'тестовая грань');
  assert.equal(await page.locator('#modal-form [name="notes"]').inputValue(),'Метаданные не должны исчезнуть');
  // Saving the same metadata proves edit access; no conceptual field is changed.
  await page.locator('#modal-form button[type="submit"]').click();await saved();await inspect('#graph');
  report.scenarios.push('editor: arrows, component dash, tooltip/ARIA and keyboard editing preserve metadata');
  await page.screenshot({path:path.join(output,'editor.png'),fullPage:true});
  await page.locator('[data-view="compare"]').click();
  await page.locator('#compare-left').selectOption(fixture.a.studyId);await page.locator('#compare-right').selectOption(fixture.b.studyId);
  await inspect('#compare-left-graph');await inspect('#compare-right-graph');
  report.scenarios.push('comparison: both independent views have unlabelled directed edges');
  await page.screenshot({path:path.join(output,'comparison.png'),fullPage:true});
  await page.locator('[data-view="accumulation"]').click();await page.locator(`[data-open-accum="${fixture.canvas}"]`).click();
  await page.locator('#accum-index-count').filter({hasText:'нерешённых пар'}).waitFor({state:'attached'});
  let accumulated=await inspect('#accum-graph');assert(new Set(accumulated.filter(e=>!e.classes.includes('candidate-edge')).map(e=>e.color)).size===2);
  assert(accumulated.some(e=>e.classes.includes('component-edge')));assert(accumulated.some(e=>e.classes.includes('candidate-edge')));
  const content=page.locator('#accum-graph [data-graph-edge]:not(.visual-candidate)').first();await content.focus();await content.press('Enter');
  await page.locator('#dialog').waitFor();assert((await page.locator('#dialog').innerText()).includes('Исходный ID'));await closeDialog();
  const candidate=page.locator('#accum-graph .visual-candidate').first();await candidate.focus();await candidate.press('Enter');
  await page.locator('#dialog').waitFor();assert((await page.locator('#dialog').innerText()).includes('Оставить неопределённым'));await closeDialog();
  await page.locator('#accum-open-inspector').click();await inspect('.accum-window-graph');
  await page.locator('.accum-inspector [data-mode]').selectOption('text');
  assert((await page.locator('.accum-window-text').innerText()).includes('ID'));await page.locator('.accum-inspector [data-close]').click();
  report.scenarios.push('accumulation and inspector: origins, alpha, auxiliary candidates, metadata and decision dialog remain distinct');
  await page.screenshot({path:path.join(output,'accumulation.png'),fullPage:true});
  await selectStudy(fixture.actual);await page.locator('[data-view="accumulation"]').click();
  await inspect('#accum-graph');await page.screenshot({path:path.join(output,'k001-k002.png'),fullPage:true});
  report.scenarios.push('existing K001+K002 portable canvas displayed without semantic edits');
  await pause(500);await page.reload();await saved();await selectStudy(fixture.actual);await page.locator('[data-view="accumulation"]').click();await inspect('#accum-graph');
  const studyContent=studies=>studies.map(s=>{s=structuredClone(s);if(s.accumulation)delete s.accumulation.camera;return s;});
  assert.deepEqual(studyContent((await state()).studies),studyContent(baseline.studies));assert.deepEqual((await state()).matches,baseline.matches);
  report.scenarios.push('reload: study content, all edge fields, origins and matches equal baseline; camera is view state');assert.deepEqual(report.errors,[]);
})().catch(async e=>{report.failure=e.stack;process.exitCode=1;await page?.screenshot({path:path.join(output,'failure.png'),fullPage:true});}).finally(async()=>{
  await fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2)+'\n');
  await browser?.close();if(server?.exitCode===null)await new Promise(r=>{server.once('exit',r);server.kill();});
  console.log(JSON.stringify({output,scenarios:report.scenarios,failure:report.failure}));
});
