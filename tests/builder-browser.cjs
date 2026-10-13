/* Isolated technical choices, not a proposed semantic decomposition of a nut. */
const {chromium}=require('playwright'),{spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),stamp=Date.now(),out=path.join(root,'test-output',`builder-${stamp}`),db=path.join(root,'local-data',`builder-${stamp}`,'workspace.sqlite3');
const port=18100+stamp%12000,url=`http://127.0.0.1:${port}`,report={date:new Date().toISOString(),node:process.version,scope:'Technical operator choices only; no semantic truth or decomposition claim',scenarios:[],errors:[]};
let server,browser,page;const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function start(){server=spawn('python',['-m','app.server','--no-browser','--port',String(port),'--db',db],{cwd:root,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});let log='';server.stdout.on('data',c=>log+=c);server.stderr.on('data',c=>log+=c);for(let i=0;i<100;i++){if(log.includes('http://'))return;if(server.exitCode!==null)throw Error(log);await pause(100);}throw Error(log);}
async function stop(){if(server?.exitCode===null)await new Promise(r=>{server.once('exit',r);server.kill();});}
async function snapshot(){return await (await fetch(url+'/api/state')).json();}
async function saved(){await page.waitForFunction(()=>!document.body.classList.contains('busy'));await page.locator('#save-status').filter({hasText:'Сохранено'}).waitFor();}
async function submit(name){await page.locator('#modal-form').getByRole('button',{name,exact:true}).click();await page.locator('#dialog').waitFor({state:'hidden'});await saved();}
async function click(id){await page.locator(id).click();await saved();}
async function search(q){await page.locator('#def-search').fill(q);await page.waitForFunction(q=>{const p=document.querySelector('#def-results');return p?.textContent.includes(q);},q);await page.waitForFunction(()=>!!document.querySelector('#def-results [data-def-word]'));}
function canvas(s){return s.studies.find(v=>v.accumulation);}
function draft(s){return canvas(s).accumulation.definitionDrafts[0];}
async function connect(a,b){await page.locator('#def-from').selectOption(a);await page.locator('#def-to').selectOption(b);await click('#def-connect');}
async function publish(){await click('#def-preview');await page.locator('#dialog').waitFor({state:'visible'});await page.locator('#modal-form [name="confirmed"]').check();assert(await page.locator('#modal-form [name="confirmed"]').isChecked());await submit('Включить на полотно');}
async function stage(file){await click('[data-view="exchange"]');await page.locator('#import-file').setInputFiles(file);await page.waitForFunction(()=>document.querySelector('#import-text').value.length>0);await click('#stage-import');await submit('Добавить в очередь');await page.waitForFunction(()=>!document.querySelector('#select-proposals').disabled);await click('#select-proposals');await click('#accept-proposals');await submit('Принять');}
(async()=>{
  await fs.mkdir(out,{recursive:true});
  const setup=spawnSync('python',['-c',`import json,sys\nfrom pathlib import Path\nfrom app.store import Store\nfrom scripts.verify_nut import accept\ns=Store(Path(sys.argv[1]))\nfor f in ['data/experiments/stone/stone.json','data/experiments/transfer/transfer.json','data/experiments/accumulation/k001-k002-workspace.json']:\n accept(s,json.loads(Path(f).read_text(encoding='utf-8')))\n`,db],{cwd:root,encoding:'utf8',windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});assert.equal(setup.status,0,setup.stderr);
  await start();browser=await chromium.launch({channel:'chrome',headless:true});report.browser=browser.version();page=await browser.newPage({viewport:{width:1600,height:1050}});page.on('pageerror',e=>report.errors.push(e.message));
  await page.goto(url);await saved();const initial=(await snapshot()).state,baseline=canvas(initial);
  await click('[data-view="builder"]');await click(`[data-def-canvas="${baseline.id}"]`);await click('#def-new');
  await page.locator('#def-title').fill('Гайка — техническая проба');await page.locator('#def-text').fill('Гайка — крепёжная деталь с внутренней резьбой.');await click('#def-save');
  const words=['гайка','крепёжный','деталь','резьба','внутренний'];
  for(const word of words){await search(word);const exact=page.locator('#def-results .definition-search-results>div').filter({has:page.locator('strong',{hasText:new RegExp('^'+word+'$')})}).filter({has:page.locator('[data-def-word]')}).first();await exact.locator('[data-def-word]').click();await saved();}
  let s=(await snapshot()).state,d=draft(s);assert.equal(d.nodes.length,5);assert.deepEqual(canvas(s).nodes,baseline.nodes);assert.deepEqual(canvas(s).edges,baseline.edges);
  report.scenarios.push('Dictionary normal noun/adjective forms and draft persistence without canvas mutation');
  // Reuse a historic canvas ID and its existing edge, without changing its source.
  const existing=baseline.edges.find(e=>e.role!=='component'),a=baseline.nodes.find(n=>n.id===existing.from),b=baseline.nodes.find(n=>n.id===existing.to);
  for(const n of [a,b]){await page.locator('#def-search').fill(n.id);await page.locator(`[data-def-use="${n.id}"]`).waitFor();await click(`[data-def-use="${n.id}"]`);}
  await connect(a.id,b.id);await page.locator('#modal-form [name="edgeId"]').selectOption(existing.id);await submit('Выбрать');
  s=(await snapshot()).state;d=draft(s);assert.equal(d.edges[0].id,existing.id);assert.equal(d.edges[0].existing,true);
  report.scenarios.push('Historic canvas node and ordinary edge IDs selected explicitly');
  const ids=d.nodes.slice(0,5).map(n=>n.id);
  for(const [a,b] of [[0,1],[1,2],[2,3],[2,4]])await connect(ids[a],ids[b]);
  d=draft((await snapshot()).state);const branchEdges=d.edges.slice(1);
  for(const e of branchEdges.slice(0,3))await click(`[data-def-route-edge="${e.id}"]`);
  await click('#def-route-confirm');await submit('Подтвердить маршрут');
  d=draft((await snapshot()).state);assert.equal(d.contextEdges.length,3);assert(!d.contextEdges.some(c=>c.from===branchEdges[3].id||c.to===branchEdges[3].id));
  // Independent branch route creates only the explicitly chosen pairs.
  for(const e of [branchEdges[0],branchEdges[1],branchEdges[3]])await click(`[data-def-route-edge="${e.id}"]`);
  await click('#def-route-confirm');await submit('Подтвердить маршрут');
  d=draft((await snapshot()).state);assert.equal(d.contextEdges.length,5);assert(!d.contextEdges.some(c=>(c.from===branchEdges[2].id&&c.to===branchEdges[3].id)||(c.from===branchEdges[3].id&&c.to===branchEdges[2].id)));
  await page.locator('#def-ids').check();assert((await page.locator('#def-graph').textContent()).includes(ids[0]));await page.locator('#def-ids').uncheck();
  await click('#def-fit');await page.screenshot({path:path.join(out,'builder.png'),fullPage:true});
  report.scenarios.push('Two explicit branching routes; five forward contexts, no arbitrary cross-branch pair; ID display toggle');
  await publish();s=(await snapshot()).state;let published=canvas(s);assert.equal(published.nodes.length,baseline.nodes.length+5);assert.equal(published.edges.length,baseline.edges.length+4);assert.deepEqual(published.accumulation.sources,baseline.accumulation.sources);assert.deepEqual(published.accumulation.decisions,baseline.accumulation.decisions);
  for(const old of initial.studies.filter(v=>!v.accumulation))assert.deepEqual(s.studies.find(v=>v.id===old.id),old);
  await publish();assert.deepEqual(canvas((await snapshot()).state),published);
  await page.reload();await saved();await page.locator('#def-text').waitFor();assert.equal(await page.locator('#def-text').inputValue(),'Гайка — крепёжная деталь с внутренней резьбой.');
  let context=draft((await snapshot()).state).contextEdges[0];await click(`[data-def-context-reverse="${context.id}"]`);await publish();published=canvas((await snapshot()).state);assert(published.accumulation.manual.contextEdges.some(c=>c.id===context.id&&c.from===context.to&&c.to===context.from));
  report.scenarios.push('Confirmed inclusion, unchanged K001/K002 and operator decisions, repeat idempotence, reload and manual context correction');
  await click('[data-view="accumulation"]');await page.locator('#accum-source-count').filter({hasText:'5 контекстных'}).waitFor();
  // Open new manual node via the ordinary SVG selector and the existing inspector.
  await page.locator(`#accum-graph [data-graph-node="${ids[0]}"]`).press('Enter');await page.locator('.accum-window-caption').filter({hasText:'показано'}).last().waitFor();
  assert((await page.locator('.accum-inspector').last().textContent()).includes('гайка'));
  const inspector=page.locator('.accum-inspector').last();await inspector.locator('[data-mode]').selectOption('text');await inspector.locator('.accum-window-text article').waitFor();assert((await inspector.locator('.accum-window-text').textContent()).includes(branchEdges[0].id));await inspector.locator('[data-mode]').selectOption('graph');
  await inspector.locator(`[data-graph-edge="${branchEdges[0].id}"]`).press('Enter');await page.locator('#dialog').waitFor({state:'visible'});assert((await page.locator('#dialog').textContent()).includes(branchEdges[0].id));await click('#modal-close');
  assert.equal(await page.locator('#toast.error:visible').count(),0);
  await page.screenshot({path:path.join(out,'canvas.png'),fullPage:true});
  report.scenarios.push('Manual node visible on historic accumulation; separate definition neighbourhood inspector');
  await click('[data-view="builder"]');await click('#def-new');await page.locator('#def-title').fill('Второе определение — reuse');await page.locator('#def-text').fill('Техническая повторная проба.');await click('#def-save');
  await search('гайка');await page.locator(`[data-def-use="${ids[0]}"]`).waitFor();await click(`[data-def-use="${ids[0]}"]`);await click(`[data-def-inspect="${ids[0]}"]`);assert((await page.locator('#dialog').textContent()).includes(branchEdges[0].id));await click('#modal-close');
  await page.locator('#def-search').fill(ids[1]);await page.locator(`[data-def-use="${ids[1]}"]`).waitFor();await click(`[data-def-use="${ids[1]}"]`);await connect(ids[0],ids[1]);await page.locator('#modal-form [name="edgeId"]').selectOption(branchEdges[0].id);await submit('Выбрать');await publish();
  const second=canvas((await snapshot()).state);assert.deepEqual(second.nodes,published.nodes);assert.deepEqual(second.edges,published.edges);assert.equal(Object.keys(second.accumulation.definitionPublications).length,2);
  report.scenarios.push('Next definition finds previously used concept and displays its ordinary/context edge IDs');
  const download=page.waitForEvent('download');await click('#def-export');const file=path.join(out,'workspace.json');await (await download).saveAs(file);const doc=JSON.parse(await fs.readFile(file,'utf8'));assert.equal(doc.version,4);assert.equal(doc.state.studies[0].accumulation.definitionDrafts.length,2);
  await stop();await start();await page.reload();await saved();assert.deepEqual(canvas((await snapshot()).state),doc.state.studies[0]);
  const isolated=path.join(out,'roundtrip.sqlite3');const check=spawnSync('python',['-c',`import json,sys\nfrom pathlib import Path\nfrom app.store import Store\nfrom scripts.verify_nut import accept\nd=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))\ns=Store(Path(sys.argv[2]))\naccept(s,d)\nassert s.read()['state']['studies']==d['state']['studies']\naccept(s,d)\nassert not any(p['status']=='pending' for p in s.read()['state']['proposals'])\nprint('exact roundtrip and repeat: OK')\n`,file,isolated],{cwd:root,windowsHide:true,encoding:'utf8',env:{...process.env,PYTHONUTF8:'1'}});assert.equal(check.status,0,check.stderr);
  // Real GUI import in a separate fresh browser-test database/process.
  await stop();server=spawn('python',['-m','app.server','--no-browser','--port',String(port),'--db',path.join(out,'gui-import.sqlite3')],{cwd:root,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});for(let i=0;i<100;i++){try{await snapshot();break;}catch{await pause(100);}}
  await page.reload();await saved();await stage(file);assert.deepEqual(canvas((await snapshot()).state),doc.state.studies[0]);
  report.scenarios.push('JSON v4 download, new server, exact clean Store import/repeat and GUI candidate review import');
  report.initial={nodes:baseline.nodes.length,edges:baseline.edges.length,sources:baseline.accumulation.sources.length};report.final={nodes:published.nodes.length,edges:published.edges.length,contexts:published.accumulation.manual.contextEdges.length};report.ids={nodes:ids,edges:branchEdges.map(e=>e.id)};assert.deepEqual(report.errors,[]);report.ok=true;
})().catch(e=>{report.failure=e.stack;process.exitCode=1;}).finally(async()=>{if(page)await page.screenshot({path:path.join(out,'last.png'),fullPage:true}).catch(()=>{});if(browser)await browser.close();await stop();await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({output:out,...report},null,2));});
