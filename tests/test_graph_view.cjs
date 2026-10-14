const {test}=require('node:test');
const assert=require('node:assert/strict');
const geometry=require('../app/static/graph-view.js');

test('zoom preserves world point under cursor, including scale limits',()=>{
  const camera={x:100,y:50,scale:1},anchor={x:250,y:20};
  for(const factor of [.001,.8,2,100]){
    const next=geometry.zoom(camera,factor,anchor,800,600);
    assert.ok(Math.abs((anchor.x-camera.x)*camera.scale-(anchor.x-next.x)*next.scale)<1e-9);
    assert.ok(Math.abs((anchor.y-camera.y)*camera.scale-(anchor.y-next.y)*next.scale)<1e-9);
    assert.ok(next.scale>=.03&&next.scale<=4);
  }
});
test('edge intersects vertical and horizontal node boundaries, and supports loops',()=>{
  const a={x:0,y:0};
  const vertical=geometry.edge(a,{x:0,y:200},1).d.match(/-?\d+(?:\.\d+)?/g).map(Number);
  assert.ok(vertical.every((n,i)=>Math.abs(n-[0,28,0,100,0,172][i])<1e-9));
  assert.match(geometry.edge(a,{x:300,y:0},1).d,/^M 80 0 Q 150 0 220 0$/);
  assert.match(geometry.edge(a,a).d,/ C /);
  assert.doesNotMatch(geometry.edge(a,{x:0,y:0}).d,/NaN|Infinity/);
});
test('fit includes node padding and respects viewport aspect ratio',()=>{
  const c=geometry.fit([{x:-500,y:-100},{x:500,y:100}],800,600);
  assert.equal(c.x,0);assert.equal(c.y,0);
  assert.ok(610*c.scale<=400);assert.ok(165*c.scale<=300);
});

test('parallel source relations and loops remain visually distinct',()=>{
  const a={x:0,y:0},b={x:300,y:0};
  assert.equal(new Set([1,2,3,4].map(i=>geometry.edge(a,b,i).d)).size,4);
  assert.equal(new Set([1,2,3].map(i=>geometry.edge(a,a,i).d)).size,3);
});
const verifyRoute=(points,rects,start,end)=>{
  assert(points&&points.length>=2,'route exists');assert.deepEqual(points[0],start);assert.deepEqual(points.at(-1),end);
  for(let i=1;i<points.length;i++){
    const a=points[i-1],b=points[i];assert(a.x===b.x||a.y===b.y,'orthogonal segment');
    for(const r of rects){if(a.x===b.x)assert(!(a.x>r.left&&a.x<r.right&&Math.max(a.y,b.y)>r.top&&Math.min(a.y,b.y)<r.bottom),'vertical avoids rectangle');else assert(!(a.y>r.top&&a.y<r.bottom&&Math.max(a.x,b.x)>r.left&&Math.min(a.x,b.x)<r.right),'horizontal avoids rectangle');}
  }
};
test('context anchors follow actual quadratic and cubic curves',()=>{
  const a={x:0,y:0},b={x:300,y:0};assert.deepEqual(geometry.sample(geometry.edge(a,b,1),.5),{x:150,y:0});
  const loop=geometry.edge(a,a,2),rects=geometry.obstacles([a]);const anchor=geometry.anchor(loop,rects);assert(anchor);assert(!geometry.inside(anchor,rects[0]));
  for(const i of [1,2,3,4])assert(geometry.anchor(geometry.edge(a,b,i),geometry.obstacles([a,b])));
});
test('rectilinear context avoids a node between ordinary edge anchors',()=>{
  const start={x:125,y:0},end={x:620,y:0},rects=geometry.obstacles([{x:0,y:0},{x:245,y:0},{x:490,y:0},{x:735,y:0}]);
  const route=geometry.orthogonal(start,end,rects);verifyRoute(route,rects,start,end);assert(route.some(p=>p.y!==0));assert.deepEqual(geometry.orthogonal(start,end,rects),route);
});
test('moving a nonincident blocking node changes the context route',()=>{
  const start={x:0,y:0},end={x:500,y:0};const free=geometry.orthogonal(start,end,geometry.obstacles([{x:250,y:200}]));
  const blocked=geometry.obstacles([{x:250,y:0}]),route=geometry.orthogonal(start,end,blocked);verifyRoute(route,blocked,start,end);assert.notDeepEqual(route,free);
});
test('alternating obstacles require more than three segments and exercise bounded A star',()=>{
  const start={x:0,y:0},end={x:600,y:0},rects=[{left:100,right:150,top:-140,bottom:20},{left:250,right:300,top:-20,bottom:140},{left:400,right:450,top:-140,bottom:20},{left:-10,right:610,top:100,bottom:130},{left:-10,right:610,top:-130,bottom:-100}];
  const route=geometry.orthogonal(start,end,rects);verifyRoute(route,rects,start,end);assert(route.length>4);
});
test('covered anchors, coincident endpoints and enclosed endpoints give explicit failure',()=>{
  const r={left:-10,right:10,top:-10,bottom:10};assert.equal(geometry.orthogonal({x:0,y:0},{x:20,y:0},[r]),null);
  assert.equal(geometry.orthogonal({x:20,y:0},{x:20,y:0},[]),null);
  assert.equal(geometry.anchor(geometry.edge({x:0,y:0},{x:1,y:0},1),[{left:-200,right:200,top:-200,bottom:200}]),null);
  const walls=[{left:-20,right:-10,top:-20,bottom:20},{left:10,right:20,top:-20,bottom:20},{left:-20,right:20,top:-20,bottom:-10},{left:-20,right:20,top:10,bottom:20}];assert.equal(geometry.orthogonal({x:0,y:0},{x:50,y:50},walls),null);
});
test('touching and overlapping rectangles retain avoidance with reversed direction',()=>{
  const start={x:-100,y:0},end={x:300,y:0},rects=[{left:0,right:100,top:-50,bottom:50},{left:80,right:200,top:-20,bottom:80}];
  verifyRoute(geometry.orthogonal(start,end,rects),rects,start,end);verifyRoute(geometry.orthogonal(end,start,rects),rects,end,start);
});
test('fit contains context detours as well as node rectangles',()=>{
  const points=[{x:0,y:0},{x:500,y:0},{x:100,y:-250},{x:400,y:-250}],c=geometry.fit(points,800,600);
  for(const p of points){assert(Math.abs(p.x-c.x)*c.scale<400);assert(Math.abs(p.y-c.y)*c.scale<300);}
});
