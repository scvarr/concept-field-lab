const test=require('node:test'),assert=require('node:assert/strict'),g=require('../app/static/graph-view.js'),check=require('./context-curve-check.cjs');
test('half arc-length marker belongs to quadratic and loop, not control point',()=>{
  for(const circle of [false,true])for(const loop of [false,true])for(const index of [1,2,3,4]){
    const a={x:0,y:0,...(circle?{radius:18}:{})},b=loop?a:{x:450,y:100,...(circle?{radius:8}:{})},e=g.edge(a,b,index),p=g.midpoint(e);
    const samples=Array.from({length:4097},(_,i)=>g.sample(e,i/4096));let total=0,left=0,min=Infinity,nearest=0;
    for(let i=1;i<samples.length;i++){total+=Math.hypot(samples[i].x-samples[i-1].x,samples[i].y-samples[i-1].y);const d=Math.hypot(samples[i].x-p.x,samples[i].y-p.y);if(d<min){min=d;nearest=i;}}
    for(let i=1;i<=nearest;i++)left+=Math.hypot(samples[i].x-samples[i-1].x,samples[i].y-samples[i-1].y);
    assert(Math.abs(left-total/2)<.2);assert(min<.2);
  }
});
test('diagonal and smoothed context avoids rectangles and alpha circles in both directions',()=>{
  const nodes=[{id:'alpha',x:180,y:60,radius:26},{id:'concept',x:380,y:100}],rects=g.obstacles(nodes),a={x:0,y:0},b={x:600,y:180};
  for(const [from,to] of [[a,b],[b,a]]){const route=g.flexible(from,to,rects);check(route.segments,nodes);assert.match(route.d,/Q/);assert(g.flexible({x:0,y:0},{x:100,y:50},[]).d.includes('L 100 50'));assert.deepEqual(g.flexible(from,to,rects),route);}
});
test('fixed marker covered by a node fails rather than relocates; coincident markers fail',()=>{
  const p=g.midpoint(g.edge({x:0,y:0},{x:400,y:0},1));assert.deepEqual(p,{x:200,y:0});assert.equal(g.flexible(p,{x:500,y:0},g.obstacles([{x:200,y:0}])),null);assert.equal(g.flexible(p,p,[]),null);
});
test('moving an unrelated obstacle rebuilds the corridor',()=>{
  const a={x:0,y:0},b={x:500,y:100},first=g.flexible(a,b,g.obstacles([{x:250,y:400}])),moved=g.flexible(a,b,g.obstacles([{x:250,y:50}]));assert.notEqual(first.d,moved.d);check(moved.segments,[{x:250,y:50}]);
});
test('bounded fallback reports enclosed endpoint without unsafe replacement',()=>{
  const rects=[{left:-20,right:-10,top:-20,bottom:20},{left:10,right:20,top:-20,bottom:20},{left:-20,right:20,top:-20,bottom:-10},{left:-20,right:20,top:10,bottom:20}];assert.equal(g.flexible({x:0,y:0},{x:100,y:100},rects),null);
});
