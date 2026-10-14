'use strict';

// Detached geometry only: no knowledge objects, IDs or edges are rewritten.
// The same engine is used in the worker and deterministic Node checks.
function calculateLayout(input, d3, dagre, progress=()=>{}) {
  const {algorithm, spacing, reduceCrossings, rootId} = input;
  if(!['force','hierarchical','radial','clusters'].includes(algorithm)||!Number.isFinite(spacing)||spacing<20||spacing>400)throw Error('Некорректные параметры раскладки.');
  const started=performance.now(), selected=new Set(input.targetIds);
  const nodes=input.nodes.map(n=>({...n})), byId=new Map(nodes.map(n=>[n.id,n]));
  const fixed=n=>!selected.has(n.id)||n.pinned||(algorithm==='radial'&&n.id===rootId);
  const movable=nodes.filter(n=>!fixed(n));
  if(!movable.length)throw Error('Нет незакреплённых узлов в выбранной области.');
  const edges=input.edges.filter(e=>byId.has(e.from)&&byId.has(e.to));
  const adjacency=new Map(nodes.map(n=>[n.id,[]]));
  for(const e of edges){if(e.from===e.to)continue;adjacency.get(e.from).push(e.to);adjacency.get(e.to).push(e.from);}
  const center=movable.reduce((p,n)=>({x:p.x+n.x/movable.length,y:p.y+n.y/movable.length}),{x:0,y:0});
  const circular=input.geometry==='circle',width=circular?Math.max(...nodes.map(n=>n.radius||8))*2:160,height=circular?width:56;
  const distance=(circular?width+20:180)+spacing;
  let repairs=0;
  function separate(rows,obstacles) {
    const cell=distance,grid=new Map(),key=(x,y)=>`${x},${y}`;
    const add=n=>{const k=key(Math.floor(n.x/cell),Math.floor(n.y/cell));if(!grid.has(k))grid.set(k,[]);grid.get(k).push(n);};
    obstacles.forEach(add);
    for(const n of rows) {
      const ox=n.x,oy=n.y;let found=false;
      for(let attempt=0;attempt<300;attempt++) {
        const gx=Math.floor(n.x/cell),gy=Math.floor(n.y/cell);let collision=false;
        for(let x=gx-1;x<=gx+1&&!collision;x++)for(let y=gy-1;y<=gy+1&&!collision;y++)for(const other of grid.get(key(x,y))||[])
          if(circular?Math.hypot(n.x-other.x,n.y-other.y)<(n.radius||8)+(other.radius||8)+spacing:Math.abs(n.x-other.x)<width+spacing&&Math.abs(n.y-other.y)<height+spacing){collision=true;break;}
        if(!collision){found=true;break;}
        const a=attempt*2.399963229728653,r=distance*Math.sqrt(attempt+1);n.x=ox+Math.cos(a)*r;n.y=oy+Math.sin(a)*r;repairs++;
      }
      if(!found)throw Error('Не удалось разместить узлы без наложений. Уменьшите расстояние или выберите меньшую область.');
      add(n);
    }
  }
  function force(group,links,cx,cy) {
    // Seed an even spiral instead of retaining a badly collapsed initial graph.
    group.forEach((n,i)=>{if(fixed(n)){n.fx=n.x;n.fy=n.y;}else{const r=distance*Math.sqrt(i+1)/2,a=i*Math.PI*(3-Math.sqrt(5));n.x=cx+r*Math.cos(a);n.y=cy+r*Math.sin(a);}});
    const ticks=reduceCrossings?360:200;
    const sim=d3.forceSimulation(group).stop().alphaDecay(1-Math.pow(.001,1/ticks))
      .force('charge',d3.forceManyBody().strength(-distance*7).distanceMax(distance*20))
      .force('links',d3.forceLink(links.map(e=>({source:e.from,target:e.to}))).id(n=>n.id).distance(distance).strength(.15))
      .force('collision',d3.forceCollide(circular?n=>(n.radius||8)+spacing/2:(Math.hypot(160,56)+spacing)/2).iterations(2))
      .force('x',d3.forceX(cx).strength(.018)).force('y',d3.forceY(cy).strength(.018));
    try {for(let i=0;i<ticks;i++){sim.tick();if(i%40===0)progress(Math.round(i/ticks*90));}}finally{sim.stop();}
  }
  if(algorithm==='force')force(nodes,edges,center.x,center.y);
  if(algorithm==='hierarchical') {
    // Lay out only the chosen induced graph; exterior nodes remain obstacles.
    const chosen=nodes.filter(n=>selected.has(n.id));
    if(chosen.length>300||edges.length>600) {
      // Dagre's dummy nodes on long edges can grow quadratically on a star
      // followed by a long chain. Bound that variant and use breadth layers.
      const outgoing=new Map(chosen.map(n=>[n.id,[]])),indegree=new Map(chosen.map(n=>[n.id,0]));
      for(const e of edges)if(selected.has(e.from)&&selected.has(e.to)&&e.from!==e.to){outgoing.get(e.from).push(e.to);indegree.set(e.to,indegree.get(e.to)+1);}
      const depth=new Map(),queue=[];
      const seed=id=>{depth.set(id,0);queue.push(id);};
      chosen.filter(n=>!indegree.get(n.id)).forEach(n=>seed(n.id));
      const walk=()=>{for(let i=0;i<queue.length;i++)for(const id of outgoing.get(queue[i]))if(!depth.has(id)){depth.set(id,depth.get(queue[i])+1);queue.push(id);}};
      walk();if(selected.has(rootId)&&!depth.has(rootId)){seed(rootId);walk();}
      for(const n of chosen)if(!depth.has(n.id)){seed(n.id);walk();}
      const layers=new Map();for(const n of chosen){const d=depth.get(n.id);if(!layers.has(d))layers.set(d,[]);layers.get(d).push(n);}
      const ordered=[...layers].sort((a,b)=>a[0]-b[0]),order=new Map();
      const assign=()=>ordered.forEach(([,layer])=>layer.forEach((n,i)=>order.set(n.id,i-(layer.length-1)/2)));
      assign();
      if(reduceCrossings)for(let pass=0;pass<6;pass++) {
        const sweep=pass%2?[...ordered].reverse():ordered;
        for(const [d,layer] of sweep){const score=n=>{const ns=adjacency.get(n.id).filter(id=>depth.has(id)&&(pass%2?depth.get(id)>d:depth.get(id)<d));return ns.length?ns.reduce((s,id)=>s+order.get(id),0)/ns.length:order.get(n.id);};layer.sort((a,b)=>score(a)-score(b)||a.id.localeCompare(b.id));layer.forEach((n,i)=>order.set(n.id,i-(layer.length-1)/2));}
      }
      // Wide levels use a rectangular grid. Long chains wrap into bands:
      // a thousand siblings plus a thousand levels must not create a mostly
      // empty 190000 x 88000 canvas. Edges themselves retain their direction.
      const slots=new Map();let x=0,y=0,bandHeight=0;
      for(const [,layer] of ordered) {
        const columns=Math.max(1,Math.ceil(Math.sqrt(layer.length*(height+spacing)/(width+spacing)))),rows=Math.ceil(layer.length/columns);
        const layerWidth=columns*(width+spacing),layerHeight=rows*(height+spacing);
        if(x&&x+layerWidth>12000){x=0;y+=bandHeight+distance;bandHeight=0;}
        layer.forEach((n,i)=>slots.set(n.id,{x:x+Math.floor(i/rows)*(width+spacing),y:y+(i%rows)*(height+spacing)}));
        x+=layerWidth+spacing;bandHeight=Math.max(bandHeight,layerHeight);
      }
      const cx=chosen.reduce((s,n)=>s+slots.get(n.id).x/chosen.length,0),cy=chosen.reduce((s,n)=>s+slots.get(n.id).y/chosen.length,0);
      chosen.forEach(n=>{if(!fixed(n)){const p=slots.get(n.id);n.x=center.x+p.x-cx;n.y=center.y+p.y-cy;}});
      progress(85);
    } else {
    const g=new dagre.graphlib.Graph({multigraph:true});
    g.setGraph({rankdir:'LR',nodesep:spacing,ranksep:spacing,edgesep:20,ranker:'longest-path'});
    g.setDefaultEdgeLabel(()=>({}));
    chosen.forEach(n=>g.setNode(n.id,{width:circular?n.radius*2:160,height:circular?n.radius*2:56}));
    edges.forEach((e,i)=>{if(selected.has(e.from)&&selected.has(e.to))g.setEdge(e.from,e.to,{},String(i));});
    dagre.layout(g,{disableOptimalOrderHeuristic:!reduceCrossings});progress(85);
    const laid=chosen.map(n=>g.node(n.id)),cx=laid.reduce((s,p)=>s+p.x/laid.length,0),cy=laid.reduce((s,p)=>s+p.y/laid.length,0);
    chosen.forEach(n=>{if(!fixed(n)){const p=g.node(n.id);n.x=p.x-cx+center.x;n.y=p.y-cy+center.y;}});
    }
  }
  if(algorithm==='radial') {
    if(!selected.has(rootId)||!byId.has(rootId))throw Error('Радиальный центр должен входить в выбранную область.');
    const root=byId.get(rootId),origin={x:root.x,y:root.y},depth=new Map([[rootId,0]]),queue=[rootId];
    for(let i=0;i<queue.length;i++)for(const id of adjacency.get(queue[i]))if(selected.has(id)&&!depth.has(id)){depth.set(id,depth.get(queue[i])+1);queue.push(id);}
    const rings=new Map();
    // Disconnected nodes have a separate outer ring, never disappear.
    const outer=Math.max(...depth.values())+1;
    for(const n of nodes.filter(n=>selected.has(n.id)&&n.id!==rootId)){const d=depth.get(n.id)??outer;if(!rings.has(d))rings.set(d,[]);rings.get(d).push(n);}
    let radius=0;const angles=new Map([[rootId,0]]);
    for(const [level,ring] of [...rings].sort((a,b)=>a[0]-b[0])) {
      if(reduceCrossings)ring.sort((a,b)=>{
        const score=n=>{const previous=adjacency.get(n.id).filter(id=>angles.has(id));return previous.length?previous.reduce((s,id)=>s+angles.get(id),0)/previous.length:Math.PI;};
        return score(a)-score(b)||a.id.localeCompare(b.id);
      });
      radius=Math.max(radius+spacing,ring.length*distance/(2*Math.PI));
      ring.forEach((n,i)=>{const a=2*Math.PI*i/ring.length;angles.set(n.id,a);if(!fixed(n)){n.x=origin.x+radius*Math.cos(a);n.y=origin.y+radius*Math.sin(a);}});
    }
    progress(85);
  }
  if(algorithm==='clusters') {
    // A manually merged node belongs to every original source. Union those
    // sources; arbitrary "first origin" assignment would split accepted identity.
    const parent=new Map();
    const find=id=>{if(!parent.has(id))parent.set(id,id);while(parent.get(id)!==id)id=parent.get(id);return id;};
    nodes.forEach(n=>{const sources=n.sources.length?n.sources:['unassigned'];sources.forEach(find);for(const s of sources)parent.set(find(s),find(sources[0]));});
    const groups=new Map();
    for(const n of nodes){const k=find(n.sources[0]||'unassigned');if(!groups.has(k))groups.set(k,[]);groups.get(k).push(n);}
    const columns=Math.ceil(Math.sqrt(groups.size));let cursorX=center.x,cursorY=center.y,rowHeight=0,column=0;
    for(const group of groups.values()) {
      if(!group.some(n=>!fixed(n)))continue;
      const ids=new Set(group.map(n=>n.id));
      const local=group.filter(n=>!fixed(n));
      const anchor=group.filter(fixed);
      const cx=anchor.length?anchor.reduce((s,n)=>s+n.x/anchor.length,0):0,cy=anchor.length?anchor.reduce((s,n)=>s+n.y/anchor.length,0):0;
      force(group,edges.filter(e=>ids.has(e.from)&&ids.has(e.to)),cx,cy);
      separate(local,anchor);
      if(!anchor.length) {
        const minX=Math.min(...local.map(n=>n.x)),maxX=Math.max(...local.map(n=>n.x)),minY=Math.min(...local.map(n=>n.y)),maxY=Math.max(...local.map(n=>n.y));
        local.forEach(n=>{n.x+=cursorX-minX;n.y+=cursorY-minY;});
        cursorX+=maxX-minX+distance*2;rowHeight=Math.max(rowHeight,maxY-minY+distance*2);
        if(++column===columns){column=0;cursorX=center.x;cursorY+=rowHeight;rowHeight=0;}
      }
    }
  }
  // Resolve node rectangles against all fixed/exterior positions, including
  // hidden nodes, without moving any of those obstacles. Bounded work, no clamp.
  // Translate a completely free layout into the coordinate domain; preserve
  // requested distances and never scale/clamp individual points.
  if(!nodes.some(fixed))for(const axis of ['x','y']) {
    const min=Math.min(...movable.map(n=>n[axis])),max=Math.max(...movable.map(n=>n[axis]));
    if(max-min>199000)throw Error('Раскладка слишком велика для ±100000. Уменьшите расстояние или область.');
    const shift=max>99500?99500-max:min< -99500?-99500-min:0;
    movable.forEach(n=>n[axis]+=shift);
  }
  separate(movable,nodes.filter(fixed));
  const positions=Object.fromEntries(movable.map(n=>[n.id,{x:Math.round(n.x*1000)/1000,y:Math.round(n.y*1000)/1000}]));
  if(Object.values(positions).some(p=>!Number.isFinite(p.x)||!Number.isFinite(p.y)||Math.abs(p.x)>100000||Math.abs(p.y)>100000))throw Error('Раскладка выходит за ±100000. Уменьшите расстояние или область.');
  return {positions,elapsedMs:performance.now()-started,nodes:nodes.length,edges:edges.length,moved:movable.length,repairs};
}
if(typeof module!=='undefined')module.exports=calculateLayout;
