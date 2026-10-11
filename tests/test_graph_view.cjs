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
