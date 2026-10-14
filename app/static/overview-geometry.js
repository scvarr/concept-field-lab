'use strict';
(function(root){
  function metrics(state){const degree=new Map(state.nodes.map(n=>[n.id,0]));for(const e of state.edges)for(const id of new Set([e.from,e.to]))degree.set(id,(degree.get(id)||0)+1);return new Map(state.nodes.map(n=>[n.id,{degree:degree.get(n.id),radius:Math.min(26,8+3*Math.sqrt(degree.get(n.id)))}]));}
  function overlaps(nodes,limit=10000,targets=null){const grid=new Map(),pairs=[];for(const n of nodes){const x=Math.floor(n.x/60),y=Math.floor(n.y/60);for(let gx=x-1;gx<=x+1;gx++)for(let gy=y-1;gy<=y+1;gy++)for(const other of grid.get(`${gx},${gy}`)||[])if((!targets||targets.has(n.id)||targets.has(other.id))&&Math.hypot(n.x-other.x,n.y-other.y)<n.radius+other.radius){pairs.push([n.id,other.id]);if(pairs.length>=limit){pairs.truncated=true;return pairs;}}const key=`${x},${y}`;if(!grid.has(key))grid.set(key,[]);grid.get(key).push(n);}return pairs;}
  const api={metrics,overlaps};if(typeof module!=='undefined')module.exports=api;else root.OverviewGeometry=api;
})(globalThis);
