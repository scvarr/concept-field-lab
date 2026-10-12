/* Real Chromium GUI on isolated synthetic data; no user database is touched. */
const {chromium}=require('playwright'),{spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),stamp=Date.now(),output=path.join(root,'test-output',`layout-${stamp}`);
const db=path.join(root,'local-data','accumulation-m005',`layout-browser-${stamp}`,'workspace.sqlite3');
const port=12000+stamp%30000,url=`http://127.0.0.1:${port}`;let server,browser,page,sid;
const report={date:new Date().toISOString(),node:process.version,scenarios:[],measurements:[],errors:[],layoutActions:[]};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function start(dbPath){server=spawn('python',['-m','app.server','--no-browser','--port',String(port),'--db',dbPath],{cwd:root,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});let log='';server.stdout.on('data',c=>log+=c);server.stderr.on('data',c=>log+=c);for(let i=0;i<100;i++){if(log.includes('http://'))return;if(server.exitCode!==null)throw Error(log);await sleep(100);}throw Error(log);}
async function stop(){if(server?.exitCode===null)await new Promise(r=>{server.once('exit',r);server.kill();});}
async function snapshot(){return (await (await fetch(url+'/api/state')).json());}
const study=snap=>snap.state.studies.find(s=>s.id===sid);
const coords=s=>Object.fromEntries(s.nodes.map(n=>[n.id,{x:n.x,y:n.y}]));
const semantics=s=>{s=structuredClone(s);for(const n of s.nodes){delete n.x;delete n.y;delete n.layoutPinned;}delete s.accumulation.camera;delete s.accumulation.lastLayout;return s;};
async function saved(){await page.waitForFunction(()=>!document.body.classList.contains('busy'));await page.locator('#save-status').filter({hasText:'Сохранено'}).waitFor();}
async function settle(){await saved();await sleep(800);await saved();}
async function submit(name){await page.locator('#modal-form').getByRole('button',{name,exact:true}).click();await page.locator('#dialog').waitFor({state:'hidden'});await saved();}
async function openPanel(){await page.locator('#layout-panel summary').click();}
async function preview(algorithm,options={}){
  await page.locator('#layout-algorithm').selectOption(algorithm);
  if(options.scope)await page.locator('#layout-scope').selectOption(options.scope);
  if(options.auxiliary!==undefined)await page.locator('#layout-auxiliary').setChecked(options.auxiliary);
  await settle();const before=await snapshot();
  await page.evaluate(()=>{window.layoutFrameGaps=[];window.layoutBeatGaps=[];window.layoutLastFrame=performance.now();window.layoutLastBeat=performance.now();window.layoutMonitor=true;function frame(t){if(!window.layoutMonitor)return;window.layoutFrameGaps.push(t-window.layoutLastFrame);window.layoutLastFrame=t;requestAnimationFrame(frame);}requestAnimationFrame(frame);window.layoutInterval=setInterval(()=>{const t=performance.now();window.layoutBeatGaps.push(t-window.layoutLastBeat);window.layoutLastBeat=t;},50);});
  const started=performance.now();await page.locator('#layout-preview').click();
  if(options.pan){
    // Pan while the worker calculates; this must preserve the running job.
    const graph=page.locator('#accum-graph'),box=await graph.boundingBox();
    await page.mouse.move(box.x+box.width-15,box.y+box.height-15);await page.mouse.down();await page.mouse.move(box.x+box.width-90,box.y+box.height-65,{steps:8});await page.mouse.up();
  }
  await page.waitForFunction(()=>!document.querySelector('#layout-apply').disabled||!document.querySelector('#layout-preview').disabled,{},{timeout:35000});
  const status=await page.locator('#layout-status').innerText();assert(status.startsWith('Предпросмотр:'),status);
  const measurement=await page.evaluate(()=>{window.layoutMonitor=false;clearInterval(window.layoutInterval);return {result:document.querySelector('#accum-graph').graphView.study.nodes.length,maxFrameMs:Math.max(0,...window.layoutFrameGaps),maxBeatMs:Math.max(0,...window.layoutBeatGaps),beats:window.layoutBeatGaps.length,frames:window.layoutFrameGaps.length};});
  measurement.algorithm=algorithm;measurement.wallMs=performance.now()-started;measurement.status=status;report.measurements.push(measurement);
  assert(measurement.maxBeatMs<1000,`UI heartbeat stalled: ${measurement.maxBeatMs}`);
  assert.deepEqual(coords(study(await snapshot())),coords(study(before)),'preview must not persist coordinates');
  assert.deepEqual(semantics(study(await snapshot())),semantics(study(before)));
  return before;
}
async function apply(){const before=await snapshot(),count=report.layoutActions.length,started=performance.now();await page.locator('#layout-apply').click();await page.locator('#layout-status').filter({hasText:'одной записью истории'}).waitFor();await saved();const after=await snapshot();assert.equal(after.revision,before.revision+1);assert.equal(report.layoutActions.length,count+1);assert.equal(report.layoutActions.at(-1).action,'layout_positions');return {before,after,ms:performance.now()-started};}
async function undo(){await page.locator('#layout-undo').click();await page.locator('#layout-status').filter({hasText:'восстановлено одной записью'}).waitFor();await saved();}
(async()=>{
  await fs.mkdir(output,{recursive:true});
  const fixture=spawnSync('python',['-m','scripts.accumulation_fixture','--db',db,'--large','2000'],{cwd:root,encoding:'utf8',windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});assert.equal(fixture.status,0,fixture.stderr);
  const manifest=JSON.parse(await fs.readFile(db.replace(/\.sqlite3$/,'-manifest.json'),'utf8'));
  await start(db);browser=await chromium.launch({channel:'chrome',headless:true});report.browser=browser.version();page=await browser.newPage({viewport:{width:1600,height:1100}});
  page.on('pageerror',e=>report.errors.push(e.message));page.on('console',m=>{if(m.type()==='error')report.errors.push(m.text());});
  page.on('request',r=>{if(r.url().endsWith('/api/action')){const body=r.postDataJSON();if(body.action.startsWith('layout_')||body.action==='position')report.layoutActions.push({action:body.action,count:Object.keys(body.data.positions||{}).length});}});
  await page.goto(url);await saved();await page.locator('[data-view="accumulation"]').click();await page.locator('#accum-create').click();await page.locator('#modal-form [name="title"]').fill('Раскладка — 2004 / 3001');
  for(const id of [manifest.A.studyId,manifest.large.studyId])await page.locator(`#modal-form [name="source"][value="${id}"]`).check();await submit('Создать полотно');await settle();
  sid=(await snapshot()).state.studies.find(s=>s.accumulation).id;const original=study(await snapshot());
  const geometryInput={nodes:original.nodes.map(n=>({id:n.id,x:n.x,y:n.y,pinned:!!n.layoutPinned,sources:[...new Set(n.origins.map(o=>o.studyId))]})),edges:original.edges.map(e=>({from:e.from,to:e.to})),targetIds:original.nodes.map(n=>n.id),rootId:original.rootId,spacing:32,reduceCrossings:true};
  await fs.writeFile(path.join(output,'geometry-input.json'),JSON.stringify(geometryInput,null,2));
  assert.equal(original.nodes.length,2004);assert.equal(original.edges.length,3001);assert.equal(await page.locator('#accum-graph [data-graph-node]').count(),1000);
  await openPanel();await page.screenshot({path:path.join(output,'before.png'),fullPage:true});
  report.scenarios.push('2004 / 3001: calculation uses all nodes, only 1000 rendered');
  // Full preview / cancel, including pan during computation.
  await preview('force',{scope:'all',pan:true,auxiliary:false});await page.locator('#layout-cancel').click();assert.deepEqual(coords(study(await snapshot())),coords(original));
  report.scenarios.push('full force preview, responsive pan, cancel without coordinate revision');
  for(const algorithm of ['force','hierarchical','radial','clusters']) {
    const before=await preview(algorithm,{scope:'all'}),result=await apply();report.measurements.at(-1).applyMs=result.ms;
    const actual=study(result.after);assert.deepEqual(semantics(actual),semantics(original));assert.equal(actual.nodes.length,2004);assert.notDeepEqual(coords(actual),coords(original));
    const hidden=original.nodes.at(-1);assert.notDeepEqual(coords(actual)[hidden.id],coords(original)[hidden.id]);
    await page.locator('#layout-fit').click();await settle();await page.screenshot({path:path.join(output,`${algorithm}.png`),fullPage:true});
    await undo();assert.deepEqual(coords(study(await snapshot())),coords(study(before)));
  }
  report.scenarios.push('four algorithms applied and undone, hidden last node preserved, one transaction each');
  // Pin a manually positioned root and select a whole source, including hidden nodes.
  await page.locator('#layout-pick').click();const pinned=original.rootId;await page.locator('#layout-pin').click();await saved();assert(study(await snapshot()).nodes.find(n=>n.id===pinned).layoutPinned);
  await page.locator('#layout-source').selectOption(manifest.large.studyId);const partialBefore=await preview('force',{scope:'source'});await apply();const partial=study(await snapshot());
  const exterior=study(partialBefore).nodes.filter(n=>!n.origins.some(o=>o.studyId===manifest.large.studyId));for(const n of exterior)assert.deepEqual(coords(partial)[n.id],{x:n.x,y:n.y});
  assert.deepEqual(coords(partial)[pinned],coords(original)[pinned]);await undo();
  report.scenarios.push('source subset: all 2000 included, 4 exterior nodes and pin unchanged');
  // Explicit dictionary geometry opt-in without changes to edges/decisions.
  const auxBefore=await preview('force',{scope:'all',auxiliary:true});await apply();assert.deepEqual(semantics(study(await snapshot())),semantics(study(auxBefore)));
  report.scenarios.push('dictionary springs opt-in preserves all semantic edges, origins and decisions');
  // Browser reload retains positions and pins; no spontaneous layout.
  const persisted=study(await snapshot());await page.reload();await saved();await page.locator('#accum-title').waitFor();assert.deepEqual(study(await snapshot()),persisted);await openPanel();assert(await page.locator('#layout-apply').isDisabled());
  // Existing GUI export and staged import to a clean, restarted database.
  const downloadPromise=page.waitForEvent('download');await page.locator('#accum-export').click();const download=await downloadPromise,file=path.join(output,'export.json');await download.saveAs(file);
  const doc=JSON.parse(await fs.readFile(file,'utf8'));assert.deepEqual(doc.state.studies.find(s=>s.id===sid),persisted);assert(doc.history.length>0);
  await stop();const importedDb=path.join(output,'import.sqlite3');await start(importedDb);await page.goto(url);await saved();await page.locator('[data-view="exchange"]').click();await page.locator('#import-file').setInputFiles(file);await page.locator('#stage-import').click();await submit('Добавить в очередь');await page.locator('#select-proposals').click();await page.locator('#accept-proposals').click();await submit('Принять');
  assert.deepEqual(study(await snapshot()),persisted);await page.reload();await saved();assert.deepEqual(study(await snapshot()),persisted);
  // Return from JSON to the earlier geometry via the same single undo operation.
  if(!await page.locator('#accum-title').isVisible()){await page.locator('#toggle-studies').click();await page.locator(`[data-study="${sid}"]`).click();}
  await openPanel();await undo();assert.deepEqual(coords(study(await snapshot())),coords(original));
  report.scenarios.push('GUI JSON export/import, reload and imported previous geometry, pin retained');
  // A dictionary group selects its hidden member, independently of SVG limits.
  await page.locator('#accum-toggle-index').click();await page.locator('#accum-index-query').fill('удалённые узлы');
  await page.locator('.accum-group').filter({hasText:'удалённые узлы'}).click();await page.locator('#layout-group').click();await page.locator('#layout-selection').filter({hasText:'Выбрано 3 узлов'}).waitFor();
  const groupBefore=await preview('force',{scope:'selected',auxiliary:false});const groupApply=await apply();const groupAfter=study(groupApply.after);
  assert.equal(report.layoutActions.at(-1).count,2);assert.notDeepEqual(coords(groupAfter)[original.nodes.at(-1).id],coords(original)[original.nodes.at(-1).id]);
  for(const n of study(groupBefore).nodes)if(!['корень Источник A','Большой корень','Сильно удалённый узел'].includes(n.label))assert.deepEqual(coords(groupAfter)[n.id],{x:n.x,y:n.y});
  await undo();await page.locator('#accum-toggle-index').click();report.scenarios.push('full dictionary group subset includes invisible distant member; all exterior positions fixed');
  // Explicit Ctrl / Shift subset and distance control with all exterior nodes fixed.
  await page.locator('#accum-roots').selectOption(original.rootId);await page.locator('#accum-go-root').click();await page.locator('#accum-zoom-reset').click();await settle();
  await page.locator('#layout-clear').click();await page.locator(`#accum-graph [data-graph-node="${original.rootId}"]`).click();
  await page.locator(`#accum-graph [data-graph-node="${original.nodes[1].id}"]`).click({modifiers:['Shift']});
  await page.locator('#layout-selection').filter({hasText:'Выбрано 2 узлов'}).waitFor();await page.locator('#layout-spacing').fill('80');await page.locator('#layout-crossings').uncheck();
  const subsetBefore=await preview('hierarchical',{scope:'selected'});const subsetApply=await apply();const subset=study(subsetApply.after);
  for(const n of study(subsetBefore).nodes)if(n.id!==original.nodes[1].id)assert.deepEqual(coords(subset)[n.id],{x:n.x,y:n.y});assert.equal(report.layoutActions.at(-1).count,1);await undo();
  report.scenarios.push('Shift multiple selection, 80px gap, heuristic off; exterior 2003 nodes fixed');
  // Abort a live worker without committing a single coordinate.
  await page.locator('#layout-scope').selectOption('all');await page.locator('#layout-algorithm').selectOption('force');await page.locator('#layout-spacing').fill('32');const cancelBefore=await snapshot();
  await page.locator('#layout-preview').click();await page.locator('#layout-cancel').click();await sleep(500);assert.deepEqual(coords(study(await snapshot())),coords(study(cancelBefore)));assert(await page.locator('#layout-apply').isDisabled());
  report.scenarios.push('immediate live-worker cancellation leaves coordinates unchanged');
  // Narrow viewport controls remain reachable and graph usable.
  await page.setViewportSize({width:760,height:1000});await page.screenshot({path:path.join(output,'narrow.png'),fullPage:true});assert(await page.locator('#layout-preview').isVisible());
  const importedSnapshot=await snapshot();await stop();await start(importedDb);assert.deepEqual((await snapshot()).state,importedSnapshot.state);
  report.scenarios.push('narrow viewport and process restart persistence');assert.deepEqual(report.errors,[]);
  report.success=true;report.db=db;report.output=output;
})().catch(e=>{report.failure=e.stack;process.exitCode=1;}).finally(async()=>{await browser?.close();await stop();await fs.mkdir(output,{recursive:true});await fs.writeFile(path.join(output,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));});
