/* A–D through real operator forms. Own SQLite, Chrome and HTTP process only. */
const {chromium}=require('playwright'),{spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),out=path.join(root,'test-output',`scenes-${Date.now()}`),port=54817,url=`http://127.0.0.1:${port}`;
const report={date:new Date().toISOString(),node:process.version,scenarios:[],negative:[],errors:[],scope:'Ручная структура; детерминированные состояния и локальные разрешения. Без NLP/физического вывода.'};
let server,browser,page;const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function start(db){server=spawn('python',['-m','app.server','--no-browser','--port',String(port),'--db',db],{cwd:root,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});let log='';server.stdout.on('data',c=>log+=c);server.stderr.on('data',c=>log+=c);for(let i=0;i<100;i++){if(log.includes('http://'))return;if(server.exitCode!==null)throw Error(log);await pause(100);}throw Error(log);}
async function stop(){if(server?.exitCode===null)await new Promise(r=>{server.once('exit',r);server.kill();});}
async function snapshot(){return(await(await fetch(url+'/api/state')).json());}
async function saved(){await page.waitForFunction(()=>!document.body.classList.contains('busy')&&document.querySelector('#save-status').textContent.startsWith('Сохранено'));}
async function submitModal(){await page.locator('#modal-form button[type=submit]').click();await page.locator('#dialog').waitFor({state:'hidden'});await saved();}
async function scene(label,kind){await page.locator('#scene-new').click();await page.locator('[name=label]').fill(label);await page.locator('[name=kind]').selectOption(kind);await submitModal();return(await snapshot()).state.sceneLab.scenes.at(-1).id;}
async function object(label,concept){await page.locator('#scene-object-new').click();await page.locator('[name=label]').fill(label);await page.locator('[name=conceptId]').selectOption(concept);await submitModal();return(await snapshot()).state.sceneLab.scenes.find(s=>s.id===awaitedScene).objects.at(-1).id;}
let awaitedScene;
async function openScene(id){awaitedScene=id;await page.locator('#scene-open').selectOption(id);}
async function input(text,kind,edge,from,to,slot='',retract){await page.locator('#scene-input-kind').selectOption(kind);await page.locator('#scene-input-text').fill(text);if(edge){await page.locator('[data-edge]').selectOption(edge);await page.locator('#scene-input-rows [data-from]').selectOption(from);await page.locator('#scene-input-rows [data-to]').selectOption(to);await page.locator('[data-slot]').fill(slot);}if(retract)await page.locator(`[name=retract][value="${retract}"]`).check();await page.locator('#scene-input-form button[type=submit]').click();await saved();}
async function extract(source,ids){await page.locator('#scene-extract-source').selectOption(source);for(const id of ids)await page.locator(`[name=extract][value="${id}"]`).check();await page.locator('#scene-extract-form button[type=submit]').click();await saved();}
async function main(){
  await fs.mkdir(out,{recursive:true});const db=path.join(out,'workspace.sqlite3');
  const init=spawnSync('python',['-m','scripts.scenes_fixture','--db',db,'--scaffold-only'],{cwd:root,encoding:'utf8',env:{...process.env,PYTHONUTF8:'1'}});assert.equal(init.status,0,init.stderr);
  await start(db);browser=await chromium.launch({channel:'chrome',headless:true});report.browser=browser.version();
  page=await browser.newPage({viewport:{width:1440,height:1100}});page.on('pageerror',e=>report.errors.push(e.message));
  await page.goto(url);await saved();await page.locator('#go-scenes').click();
  const knowledge=await scene('Гайка — деталь','knowledge');await openScene(knowledge);
  const nut=await object('Гайка','item'),detail=await object('Деталь','category');
  await input('Гайка — деталь','state','classification',nut,detail);
  const nutFact=(await snapshot()).sceneView.current[knowledge][0].id;
  assert((await page.locator('#scene-current-facts').innerText()).includes('Гайка — является → Деталь'));
  report.scenarios.push('A: поверх операторского каркаса формами созданы объекты и накопленная сцена «Гайка — деталь»; конкретного факта в каркасе нет.');
  const physics=await scene('Физика','knowledge');await openScene(physics);
  await page.locator('#scene-link-new').click();await page.locator('[name=targetId]').selectOption(knowledge);await submitModal();
  const dialogue=await scene('Разговор','dialogue');await openScene(dialogue);
  const scaffold=JSON.stringify((await snapshot()).state.nodes);
  await input('Физика','context');assert.equal(JSON.stringify((await snapshot()).state.nodes),scaffold);
  assert.equal((await snapshot()).state.sceneLab.workspaces.length,0);
  report.scenarios.push('B: ввод «Физика» находит одну существующую сцену, сохраняет ссылку и вход; граф не меняется, рабочие экземпляры не создаются.');
  const screw=await object('Винт №1','item'),table=await object('Стол','place'),floor=await object('Пол','place');
  await input('Винт лежит на столе','state','location',screw,table,'положение');
  let snap=await snapshot();const previous=snap.sceneView.current[dialogue][0].id;assert.equal(snap.sceneView.current[dialogue][0].to,table);
  await input('Винт упал на пол','event','fall',screw,floor,'',previous);
  assert.deepEqual((await snapshot()).sceneView.current[dialogue],[]);
  await input('Винт лежит на полу','state','location',screw,floor,'положение');
  snap=await snapshot();assert.equal(snap.sceneView.current[dialogue][0].to,floor);
  assert.deepEqual([...new Set(snap.state.sceneLab.scenes.find(s=>s.id===dialogue).entries.flatMap(e=>e.assertions.map(f=>f.from)))],[screw]);
  assert.equal(await page.locator('#scene-history summary').count(),4);
  await page.screenshot({path:path.join(out,'dialogue.png'),fullPage:true});
  report.scenarios.push('C: три реплики в одном разговоре, один ID винта, сохранённое событие и прежнее положение. Между событием и третьим входом положение неизвестно.');
  await page.locator('#scene-workspace-new').click();await page.locator('[name=label]').fill('Проверка копий');await submitModal();
  assert((await page.locator('#scene-working-copies').innerText()).includes('Рабочая область пуста'));
  await extract(knowledge,[nutFact]);snap=await snapshot();const workspace=snap.state.sceneLab.workspaces[0],first=workspace.bundles[0].assertions[0].id;
  await page.locator(`[data-scene-seed="${first}"]`).click();await saved();await extract(knowledge,[nutFact]);
  snap=await snapshot();assert.equal(snap.state.sceneLab.workspaces[0].bundles[0].assertions[0].activation,'seed');assert.equal(snap.state.sceneLab.workspaces[0].bundles[1].assertions[0].activation,'inactive');
  await page.screenshot({path:path.join(out,'workspace.png'),fullPage:true});
  report.scenarios.push('D: выборочное извлечение знания по ссылке Физика → Гайка; две копии имеют разное состояние и видимое происхождение до входа/утверждения/версии.');
  // Add an explicit classification to the dialogue to test a local permitted step.
  const screwClass=await object('Деталь','category');await input('Винт — деталь','state','classification',screw,screwClass);
  snap=await snapshot();const facts=snap.sceneView.current[dialogue],classification=facts.find(f=>f.edgeId==='classification').id,location=facts.find(f=>f.edgeId==='location').id;
  await extract(dialogue,[classification,location]);snap=await snapshot();let bundle=snap.state.sceneLab.workspaces[0].bundles.at(-1);const seed=bundle.assertions.find(f=>f.edgeId==='classification').id,dest=bundle.assertions.find(f=>f.edgeId==='location').id;
  assert.equal(await page.locator('[data-scene-step]').count(),0);
  await page.locator(`[data-scene-seed="${seed}"]`).click();await saved();
  assert.equal(await page.locator(`[data-scene-step="${dest}"]`).count(),1);
  await page.locator(`[data-scene-step="${dest}"]`).click();await saved();assert.equal((await page.locator(`[data-activation="${dest}"]`).innerText()),'context');
  report.scenarios.push('Явный seed разрешает ровно один направленный локальный шаг classification → location того же винта; вычисленная возможность видна отдельной кнопкой, исполнение сохраняет трассу.');
  // Stale tab must reject and preserve data; a refresh recovers the same scene.
  const second=await browser.newPage();await second.goto(url);await second.locator('#save-status').filter({hasText:'Сохранено'}).waitFor();await second.locator('#go-scenes').click();
  await page.locator('#scene-reset').click();await saved();const before=await snapshot();
  await second.locator('#scene-workspace-new').click();await second.locator('[name=label]').fill('Устаревшая запись');await second.locator('#modal-form button[type=submit]').click();await second.locator('#toast.error').filter({hasText:'другой вкладке'}).waitFor();
  assert.deepEqual((await snapshot()).state,before.state);await second.close();report.negative.push('Устаревшая вкладка получила HTTP 409; состояние не изменилось.');
  await page.locator('#scene-input-kind').selectOption('context');await page.locator('#scene-input-text').fill('Неизвестная наука');await page.locator('#scene-input-form button[type=submit]').click();await page.locator('#toast.error').filter({hasText:'не найдена'}).waitFor();assert.deepEqual((await snapshot()).state,before.state);report.negative.push('Неизвестный контекст отклонён без новой сцены, онтологии или изменения состояния.');
  await page.reload();await saved();await page.locator('#go-scenes').click();
  await page.setViewportSize({width:600,height:1000});await page.screenshot({path:path.join(out,'narrow.png'),fullPage:true});
  report.horizontalOverflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);assert.equal(report.horizontalOverflow,false);
  const doc=await(await fetch(url+'/api/export')).json();await fs.writeFile(path.join(out,'export.json'),JSON.stringify(doc,null,2));assert.equal(doc.version,3);
  const expected=(await snapshot()).state;await stop();await start(db);await page.reload();await saved();assert.deepEqual((await snapshot()).state,expected);
  report.scenarios.push('Перезапуск сервера и перезагрузка сохраняют сцены, историю, объекты и рабочие копии. Экспорт v3 содержит весь state и журнал. Ширина 600 px без горизонтального переполнения.');
  assert.deepEqual(report.errors,[]);report.result='passed';
}
main().catch(e=>{report.result='failed';report.failure=e.stack;process.exitCode=1;}).finally(async()=>{await browser?.close();await stop();await fs.writeFile(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({out,...report},null,2));});
