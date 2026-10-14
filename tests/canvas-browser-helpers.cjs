/* Interact with the actual canvas UI, including SVG hit paths and popup forms. */
module.exports=page=>{
  const saved=async()=>{await page.waitForFunction(()=>!document.body.classList.contains('busy'));await page.locator('#save-status').filter({hasText:'Сохранено'}).waitFor();};
  const click=async selector=>{await page.locator(selector).click();await saved();if(selector==='#workspace-tools')await page.locator('#dialog').waitFor({state:'visible'});};
  const submit=async name=>{await page.locator('#modal-form').getByRole('button',{name,exact:true}).click();await page.locator('#dialog').waitFor({state:'hidden'});await saved();};
  const menu=async(kind,id,surface='#def-graph')=>{
    if(kind==='edge'){
      const p=await page.locator(`${surface} [data-graph-edge="${id}"] .edge-hit`).evaluate((path,id)=>{const m=path.getScreenCTM();for(const fraction of [.5,.25,.75,.1,.9,.4,.6]){const p=path.getPointAtLength(path.getTotalLength()*fraction),x=m.a*p.x+m.c*p.y+m.e,y=m.b*p.x+m.d*p.y+m.f;if(document.elementFromPoint(x,y)?.closest('[data-graph-edge]')?.dataset.graphEdge===id)return {x,y};}throw Error('No visible hit segment for '+id);},id);
      await page.mouse.click(p.x,p.y,{button:'right'});
    }else if(kind==='node')await page.locator(`${surface} [data-graph-node="${id}"] rect`).click({button:'right'});
    else{const r=await page.locator(surface).boundingBox();await page.mouse.click(r.x+12,r.y+12,{button:'right'});}
    await page.locator('.canvas-menu').waitFor({state:'visible'});
  };
  const action=async id=>{await page.locator(`[data-canvas-action="${id}"]`).click();await saved();};
  const search=async word=>{if(!await page.locator('#def-search').isVisible())await click('#def-search-open');await page.locator('#def-search').fill(word);await page.locator('#def-results strong').filter({hasText:new RegExp('^'+word+'$')}).first().waitFor();};
  const addWord=async word=>{await search(word);const row=page.locator('.definition-search-results>div').filter({has:page.locator('strong',{hasText:new RegExp('^'+word+'$')})}).filter({has:page.locator('[data-def-word]')}).first();await row.locator('[data-def-word]').click();await page.locator('#dialog').waitFor({state:'hidden'});await saved();};
  const openNode=async id=>{await menu('node',id);await action('edit-node');await page.locator('#dialog').waitFor({state:'visible'});};
  const connect=async(from,to)=>{await menu('node',from);await action('connect');await page.locator('#def-graph [data-graph-node="'+to+'"] rect').click();await saved();};
  const routeAdd=async id=>{await menu('edge',id);await action('route-add');};
  const moveNode=async(id,dx,dy,surface='#def-graph')=>{const r=await page.locator(`${surface} [data-graph-node="${id}"] rect`).boundingBox();await page.mouse.move(r.x+r.width/2,r.y+r.height/2);await page.mouse.down();await page.mouse.move(r.x+r.width/2+dx,r.y+r.height/2+dy,{steps:10});await page.mouse.up();await saved();};
  const definition=async(title,text)=>{await click('#def-definition');await page.locator('#def-title').fill(title);await page.locator('#def-text').fill(text);await submit('Сохранить определение');};
  const publish=async()=>{await click('#def-preview');await page.locator('#dialog').waitFor({state:'visible'});await page.locator('#modal-form [name=confirmed]').check();await submit('Включить в граф');};
  return {saved,click,submit,menu,action,search,addWord,openNode,connect,routeAdd,moveNode,definition,publish};
};
