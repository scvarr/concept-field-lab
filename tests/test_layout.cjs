const {test}=require('node:test'),assert=require('node:assert/strict');
const layout=require('../app/static/layout-engine.js'),d3=require('../app/static/vendor/d3-7.9.0.min.js'),dagre=require('../app/static/vendor/dagre-1.1.5.min.js');
const base=()=>({nodes:Array.from({length:12},(_,i)=>({id:String(i),x:i*200,y:0,pinned:i===3,sources:[i<6?'a':'b']})),edges:Array.from({length:10},(_,i)=>({from:String(i<5?i:i+1),to:String(i<5?i+1:i+2)})),targetIds:['0','1','2','3','4','5'],algorithm:'force',spacing:32,reduceCrossings:true,rootId:'0'});
for(const algorithm of ['force','hierarchical','radial','clusters'])test(`${algorithm}: detached partial graph, pins, finite deterministic coordinates`,()=>{
  const input={...base(),algorithm},copy=structuredClone(input),r=layout(input,d3,dagre);
  assert.deepEqual(input,copy);assert.deepEqual(Object.keys(r.positions),algorithm==='radial'?['1','2','4','5']:['0','1','2','4','5']);
  assert.deepEqual(layout(input,d3,dagre).positions,r.positions);
  const complete=input.nodes.map(n=>({...n,...r.positions[n.id]}));
  for(const n of complete.filter(n=>r.positions[n.id]))for(const other of complete.filter(o=>o.id!==n.id))assert(Math.abs(n.x-other.x)>=191.999||Math.abs(n.y-other.y)>=87.999,'rectangle separation');
});
test('cycles, parallel edges, loops and disconnected nodes are retained',()=>{
  const input=base();input.edges.push({from:'0',to:'0'},{from:'2',to:'0'},{from:'0',to:'1'});input.targetIds=input.nodes.map(n=>n.id);
  for(const algorithm of ['hierarchical','radial','clusters'])assert.equal(layout({...input,algorithm},d3,dagre).moved,algorithm==='radial'?10:11);
});
test('scalable hierarchy covers hidden 2004 nodes / 3001 edges without Dagre dummy explosion',()=>{
  const nodes=Array.from({length:2004},(_,i)=>({id:String(i),x:i%35*260,y:Math.floor(i/35)*90,pinned:false,sources:[i<4?'a':'b']})),edges=[];
  for(let i=5;i<2004;i++)edges.push({from:i<=1004?'4':String(i-1),to:String(i)});
  for(let i=5;i<1004;i++)edges.push({from:String(i),to:String(i+1)});
  edges.push({from:'0',to:'1'},{from:'1',to:'2'},{from:'1',to:'3'});
  const r=layout({nodes,edges,targetIds:nodes.map(n=>n.id),algorithm:'hierarchical',spacing:32,reduceCrossings:true,rootId:'4'},d3,dagre);
  assert.equal(r.nodes,2004);assert.equal(r.edges,3001);assert.equal(r.moved,2004);assert(r.elapsedMs<30000);
  const points=Object.values(r.positions);assert(Math.max(...points.map(p=>p.x))-Math.min(...points.map(p=>p.x))<20000);assert(Math.max(...points.map(p=>p.y))-Math.min(...points.map(p=>p.y))<20000);
});
test('hierarchical ordering reduces crossings on a reproducible bipartite example',()=>{
  const edges=[[0,6],[0,9],[1,7],[1,8],[2,6],[2,7],[3,8],[3,9],[4,6],[4,8],[4,10]].map(([from,to])=>({from:String(from),to:String(to)}));
  const nodes=Array.from({length:12},(_,i)=>({id:String(i),x:0,y:0,pinned:false,sources:['a']}));
  const input={nodes,edges,targetIds:nodes.map(n=>n.id),algorithm:'hierarchical',spacing:32,rootId:'0'};
  const count=positions=>{let n=0;const side=(a,b,c)=>(b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x);for(let i=0;i<edges.length;i++)for(let j=i+1;j<edges.length;j++){const a=edges[i],b=edges[j];if(a.from===b.from||a.to===b.to)continue;const p=positions[a.from],q=positions[a.to],u=positions[b.from],v=positions[b.to];if(side(p,q,u)*side(p,q,v)<0&&side(u,v,p)*side(u,v,q)<0)n++;}return n;};
  assert.equal(count(layout({...input,reduceCrossings:false},d3,dagre).positions),13);
  assert.equal(count(layout({...input,reduceCrossings:true},d3,dagre).positions),10);
});
test('unanchored source clusters have disjoint bounding boxes; accepted shared origin is one cluster',()=>{
  const input=base();input.nodes.forEach(n=>n.pinned=false);input.targetIds=input.nodes.map(n=>n.id);input.algorithm='clusters';
  const points=layout(input,d3,dagre).positions;
  const box=source=>{const rows=input.nodes.filter(n=>n.sources.includes(source)).map(n=>points[n.id]);return {x1:Math.min(...rows.map(p=>p.x)),x2:Math.max(...rows.map(p=>p.x)),y1:Math.min(...rows.map(p=>p.y)),y2:Math.max(...rows.map(p=>p.y))};};
  const a=box('a'),b=box('b');assert(a.x2+192<=b.x1||b.x2+192<=a.x1||a.y2+88<=b.y1||b.y2+88<=a.y1);
  input.nodes[5].sources=['a','b'];assert.equal(layout(input,d3,dagre).moved,12);assert.deepEqual(input.nodes[5].sources,['a','b']);
});
test('large canvas fit has an explicit lower zoom bound without changing editor default',()=>{
  const geometry=require('../app/static/graph-view.js'),points=[{x:-99000,y:-99000},{x:99000,y:99000}];
  assert.equal(geometry.fit(points,1500,800).scale,.03);const camera=geometry.fit(points,1500,800,.002);assert(camera.scale<.005&&camera.scale>.002);assert.equal(geometry.zoom(camera,.01,camera,1500,800,.002).scale,.002);
});
