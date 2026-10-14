const assert=require('node:assert/strict');
// Independent dense sampling of saved SVG control points against actual node shapes.
module.exports=(segments,nodes)=>{
  assert(segments?.length);
  for(const controls of segments)for(let i=0;i<=256;i++){
    let points=controls.map(p=>({...p}));const t=i/256;
    while(points.length>1)points=points.slice(1).map((p,j)=>({x:points[j].x*(1-t)+p.x*t,y:points[j].y*(1-t)+p.y*t}));
    const p=points[0];
    for(const n of nodes)assert(n.radius?Math.hypot(p.x-n.x,p.y-n.y)>=n.radius-1e-6:Math.abs(p.x-n.x)>=80-1e-6||Math.abs(p.y-n.y)>=28-1e-6,'Curve intersects node '+n.id);
  }
};
