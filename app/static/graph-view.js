'use strict';

// Geometry is independent of application state, persistence and the rendering surface.
const GraphGeometry = {
  edge(a,b,index=0) {
    if(Number.isFinite(a.radius)&&Number.isFinite(b.radius)){
      if(a===b||a.x===b.x&&a.y===b.y){const r=a.radius,s=45+index*14,p=[{x:a.x+r*.8,y:a.y-r*.6},{x:a.x+r+s,y:a.y-r-s},{x:a.x-r-s,y:a.y-r-s},{x:b.x-b.radius*.8,y:b.y-b.radius*.6}];return {d:`M ${p[0].x} ${p[0].y} C ${p[1].x} ${p[1].y}, ${p[2].x} ${p[2].y}, ${p[3].x} ${p[3].y}`,points:p,x:a.x,y:a.y-r-s};}
      const dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy),offset=index===1?0:(index%2? -1:1)*Math.ceil(index/2)*18,c={x:(a.x+b.x)/2-dy/len*offset,y:(a.y+b.y)/2+dx/len*offset};
      const boundary=(n,c)=>{const d=Math.hypot(c.x-n.x,c.y-n.y)||1;return {x:n.x+(c.x-n.x)*n.radius/d,y:n.y+(c.y-n.y)*n.radius/d};},start=boundary(a,c),end=boundary(b,c);
      return {d:`M ${start.x} ${start.y} Q ${c.x} ${c.y} ${end.x} ${end.y}`,points:[start,c,end],x:c.x,y:c.y};
    }
    if(a===b){const spread=Math.max(0,index-1)*24;return {d:`M ${a.x+65} ${a.y-8} C ${a.x+155+spread} ${a.y-105-spread}, ${a.x-65-spread} ${a.y-110-spread}, ${a.x-35} ${a.y-30}`,x:a.x+40,y:a.y-70-spread,points:[{x:a.x+65,y:a.y-8},{x:a.x+155+spread,y:a.y-105-spread},{x:a.x-65-spread,y:a.y-110-spread},{x:a.x-35,y:a.y-30}]};}
    const dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy)||1,offset=index===1?0:index===0?-12:(index%2===0?index/2:-(index-1)/2)*22;
    const x=(a.x+b.x)/2-dy/len*offset,y=(a.y+b.y)/2+dx/len*offset;
    // Intersect the ray with the rectangular node boundary (80 by 28 half-size).
    const t=Math.min(dx?80/Math.abs(dx):Infinity,dy?28/Math.abs(dy):Infinity);
    const pad=Number.isFinite(t)?t:0;
    return {d:`M ${a.x+dx*pad} ${a.y+dy*pad} Q ${x} ${y} ${b.x-dx*pad} ${b.y-dy*pad}`,x,y:y-7,points:[{x:a.x+dx*pad,y:a.y+dy*pad},{x,y},{x:b.x-dx*pad,y:b.y-dy*pad}]};
  },
  sample(edge,t) {
    let points=edge.points.map(p=>({...p}));
    while(points.length>1)points=points.slice(1).map((p,i)=>({x:points[i].x*(1-t)+p.x*t,y:points[i].y*(1-t)+p.y*t}));
    return points[0];
  },
  obstacles(positions){return positions.map(p=>({left:p.x-(p.radius===undefined?90:p.radius+10),right:p.x+(p.radius===undefined?90:p.radius+10),top:p.y-(p.radius===undefined?38:p.radius+10),bottom:p.y+(p.radius===undefined?38:p.radius+10)}));},
  inside(p,r){return p.x>r.left&&p.x<r.right&&p.y>r.top&&p.y<r.bottom;},
  segmentClear(a,b,rects) {
    if(a.x!==b.x&&a.y!==b.y)return false;
    return !rects.some(r=>a.x===b.x?a.x>r.left&&a.x<r.right&&Math.max(a.y,b.y)>r.top&&Math.min(a.y,b.y)<r.bottom:a.y>r.top&&a.y<r.bottom&&Math.max(a.x,b.x)>r.left&&Math.min(a.x,b.x)<r.right);
  },
  anchor(edge,rects,offset=0) {
    // Anchors belong to the actual Bezier curve, never to its label or a node.
    const fractions=[.5,.35,.65,.2,.8,.1,.9,.05,.95];
    for(let i=0;i<fractions.length;i++){const p=this.sample(edge,fractions[(i+offset)%fractions.length]);if(!rects.some(r=>this.inside(p,r)))return p;}
    return null;
  },
  orthogonal(start,end,rects) {
    if(!start||!end||rects.some(r=>this.inside(start,r)||this.inside(end,r)))return null;
    if(start.x===end.x&&start.y===end.y)return null;
    const simplify=points=>points.filter((p,i)=>!i||p.x!==points[i-1].x||p.y!==points[i-1].y).filter((p,i,a)=>!i||i===a.length-1||!((a[i-1].x===p.x&&p.x===a[i+1].x)||(a[i-1].y===p.y&&p.y===a[i+1].y)));
    const clear=points=>points.slice(1).every((p,i)=>this.segmentClear(points[i],p,rects));
    const length=points=>points.slice(1).reduce((sum,p,i)=>sum+Math.abs(p.x-points[i].x)+Math.abs(p.y-points[i].y),0);
    const xs=[...new Set([start.x,end.x,...rects.flatMap(r=>[r.left,r.right])])].sort((a,b)=>a-b),ys=[...new Set([start.y,end.y,...rects.flatMap(r=>[r.top,r.bottom])])].sort((a,b)=>a-b);
    // Most manual graphs need only one or two turns. Try inexpensive routes first.
    const rails=(values,a,b)=>{const nearest=values.slice().sort((x,y)=>Math.abs(x-a)+Math.abs(x-b)-Math.abs(y-a)-Math.abs(y-b));return [...new Set([...nearest.slice(0,32),values[0],values.at(-1)])];};
    const candidates=[[start,{x:end.x,y:start.y},end],[start,{x:start.x,y:end.y},end],...rails(xs,start.x,end.x).map(x=>[start,{x,y:start.y},{x,y:end.y},end]),...rails(ys,start.y,end.y).map(y=>[start,{x:start.x,y},{x:end.x,y},end])];
    candidates.sort((a,b)=>length(a)-length(b));
    for(const points of candidates)if(clear(points))return simplify(points);
    // Finite fallback for alternating obstacles: A* on their coordinate grid.
    // A failed/budget-limited route is reported; no line through nodes is substituted.
    const nx=xs.length,ny=ys.length,count=nx*ny;if(count>40000)return null;
    const horizontal=new Uint8Array(count),vertical=new Uint8Array(count);
    const xi=new Map(xs.map((x,i)=>[x,i])),yi=new Map(ys.map((y,i)=>[y,i]));
    for(const r of rects){const l=xi.get(r.left),rr=xi.get(r.right),t=yi.get(r.top),b=yi.get(r.bottom);for(let y=t;y<=b;y++)for(let x=l;x<=rr;x++){const id=y*nx+x;if(y>t&&y<b&&x<rr)horizontal[id]=1;if(x>l&&x<rr&&y<b)vertical[id]=1;}}
    const first=yi.get(start.y)*nx+xi.get(start.x),last=yi.get(end.y)*nx+xi.get(end.x),distance=new Float64Array(count).fill(Infinity),parent=new Int32Array(count).fill(-1),heap=[];
    const heuristic=id=>Math.abs(xs[id%nx]-end.x)+Math.abs(ys[Math.floor(id/nx)]-end.y);
    const push=(id,g)=>{const entry={id,g,f:g+heuristic(id)};let i=heap.length;heap.push(entry);while(i){const p=(i-1)>>1;if(heap[p].f<=entry.f)break;heap[i]=heap[p];i=p;}heap[i]=entry;};
    const pop=()=>{const result=heap[0],end=heap.pop();if(heap.length){let i=0;while(i*2+1<heap.length){let c=i*2+1;if(c+1<heap.length&&heap[c+1].f<heap[c].f)c++;if(heap[c].f>=end.f)break;heap[i]=heap[c];i=c;}heap[i]=end;}return result;};
    distance[first]=0;push(first,0);
    while(heap.length){const {id,g}=pop();if(g!==distance[id])continue;if(id===last){const points=[];for(let v=id;v!==-1;v=parent[v])points.push({x:xs[v%nx],y:ys[Math.floor(v/nx)]});return simplify(points.reverse());}const x=id%nx,y=Math.floor(id/nx),next=[];
      if(x+1<nx&&!horizontal[id])next.push(id+1);if(x&&!horizontal[id-1])next.push(id-1);if(y+1<ny&&!vertical[id])next.push(id+nx);if(y&&!vertical[id-nx])next.push(id-nx);
      for(const v of next){const cost=g+Math.abs(xs[v%nx]-xs[x])+Math.abs(ys[Math.floor(v/nx)]-ys[y]);if(cost<distance[v]){distance[v]=cost;parent[v]=id;push(v,cost);}}
    }
    return null;
  },
  zoom(camera,factor,anchor,width,height,minScale=.03) {
    const scale=Math.max(minScale,Math.min(4,camera.scale*factor)),ratio=camera.scale/scale;
    return {x:anchor.x+(camera.x-anchor.x)*ratio,y:anchor.y+(camera.y-anchor.y)*ratio,scale};
  },
  fit(points,width,height,minScale=.03) {
    const minX=Math.min(...points.map(p=>p.x))-110,maxX=Math.max(...points.map(p=>p.x))+110;
    const minY=Math.min(...points.map(p=>p.y))-65,maxY=Math.max(...points.map(p=>p.y))+65;
    return {x:(minX+maxX)/2,y:(minY+maxY)/2,scale:Math.max(minScale,Math.min(1,width/(maxX-minX),height/(maxY-minY)))};
  }
};
if(typeof module!=='undefined')module.exports=GraphGeometry;

if(typeof window!=='undefined') {
  const ns='http://www.w3.org/2000/svg';
  const svgElement=(tag,attrs={},text)=>{const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;return e;};
  window.GraphView=class {
    constructor(host,options) {
      this.host=host;this.options=options;this.nodes=new Map();this.edges=new Map();this.contexts=new Map();this.incident=new Map();this.positions=new Map();this.camera=null;this.frames=[];this.autoLabels=false;
      this.svg=svgElement('svg',{role:'img',tabindex:'0','aria-label':'Граф'});
      const defs=svgElement('defs'),marker=svgElement('marker',{id:`arrow-${host.id}`,markerWidth:8,markerHeight:8,refX:7,refY:4,orient:'auto'});this.defs=defs;this.markers=new Map();
      marker.append(svgElement('path',{d:'M0 0 L8 4 L0 8',fill:'#92aaa0'}));defs.append(marker);
      const contextMarker=svgElement('marker',{id:`context-arrow-${host.id}`,markerWidth:8,markerHeight:8,refX:7,refY:4,orient:'auto'});contextMarker.append(svgElement('path',{d:'M0 0 L8 4 L0 8',fill:'#8b509a'}));defs.append(contextMarker);
      this.contextLayer=svgElement('g',{'class':'context-layer'});this.edgeLayer=svgElement('g');this.nodeLayer=svgElement('g');this.svg.append(defs,this.contextLayer,this.edgeLayer,this.nodeLayer);this.legend=document.createElement('div');this.legend.className='context-legend';this.legend.hidden=true;host.replaceChildren(this.svg,this.legend);
      this.bind();this.observer=new ResizeObserver(()=>this.paintCamera());this.observer.observe(host);
    }
    size(){return {width:Math.max(1,this.host.clientWidth),height:Math.max(1,this.host.clientHeight)};}
    snapshot(){return {camera:this.camera&&{...this.camera},frames:this.frames.slice(-40),positions:Object.fromEntries(this.positions)};}
    changed(){this.options.changed?.(this.snapshot());}
    remember(){if(this.camera)this.frames.push({...this.camera});this.frames=this.frames.slice(-40);}
    restore(snapshot){this.camera=snapshot?.camera&&{...snapshot.camera};this.frames=snapshot?.frames||[];this.positions=new Map(Object.entries(snapshot?.positions||{}));}
    update(s,graph,focus,markings=new Map(),layout=new Map()) {
      this.study=s;this.focus=focus;this.radii=new Map(graph.nodes.map(n=>[n.id,n.radius]));this.svg.setAttribute('aria-label',`Граф ${s.title}`);
      const ids=new Set(graph.nodes.map(n=>n.id));
      for(const [id,e]of this.nodes)if(!ids.has(id)){e.remove();this.nodes.delete(id);}
      for(const n of graph.nodes) {
        const saved=Number.isFinite(n.x)&&Number.isFinite(n.y)?{x:n.x,y:n.y}:null;
        this.positions.set(n.id,saved||this.positions.get(n.id)||layout.get(n.id)||{x:0,y:0});
        let g=this.nodes.get(n.id);
        if(!g){g=svgElement('g',{'data-graph-node':n.id,role:'button',tabindex:0});g.append(this.options.circular?svgElement('circle',{r:n.radius||8}):svgElement('rect',{x:-80,y:-28,width:160,height:56,rx:9}),svgElement('text',{'text-anchor':'middle',y:-2}),svgElement('text',{'class':'kind-label','text-anchor':'middle',y:15}),svgElement('title'));this.nodeLayer.append(g);this.nodes.set(n.id,g);}
        const name=n.label||`α · ${n.id.slice(0,8)}`;
        g.setAttribute('class',`node ${['combination','alpha'].includes(n.structure)?'combination-node':''} ${n.id===focus?'selected':''} ${markings.get(n.id)||''}`);
        g.classList.toggle('round-node',!!this.options.circular);g.dataset.radius=String(n.radius||0);g.dataset.degree=String(n.degree||0);g.dataset.pinned=n.layoutPinned?'true':'false';if(this.options.circular){g.children[0].setAttribute('r',n.radius);g.children[1].setAttribute('y',-n.radius-8);g.children[1].setAttribute('class','overview-label');g.children[2].textContent='';g.onmouseenter=()=>{this.hovered=n.id;this.paintLabels();};g.onmouseleave=()=>{this.hovered=null;this.paintLabels();};g.onfocus=()=>{this.focused=n.id;this.paintLabels();};g.onblur=()=>{this.focused=null;this.paintLabels();};}g.setAttribute('aria-label',`Узел ${name}`);g.children[1].textContent=name.length>(this.options.circular?48:21)?name.slice(0,this.options.circular?47:20)+'…':name;g.children[2].textContent=this.options.circular?'':(n.badge||n.kind||'').slice(0,26);g.children[3].textContent=`${n.displayTitle||name}\n${n.notes||''}`;
        const p=this.positions.get(n.id);g.setAttribute('transform',`translate(${p.x},${p.y})`);
      }
      const shown=graph.edges.slice(0,this.options.edgeLimit||3000),edgeIds=new Set(shown.map(e=>e.id));
      for(const [id,item]of this.edges)if(!edgeIds.has(id)){item.g.remove();this.edges.delete(id);}
      this.incident=new Map(graph.nodes.map(n=>[n.id,new Set()]));
      const parallel=new Map();
      shown.forEach(e=>{
        const pair=JSON.stringify([e.from,e.to].sort()),index=(parallel.get(pair)||0)+1;parallel.set(pair,index);
        let item=this.edges.get(e.id);
        if(!item){const g=svgElement('g',{'data-graph-edge':e.id}),hit=svgElement('path',{'class':'edge-hit',fill:'none',stroke:'transparent','stroke-width':14});const path=svgElement('path',{'marker-end':`url(#arrow-${this.host.id})`}),label=svgElement('text',{'class':'edge-label','text-anchor':'middle'}),title=svgElement('title');g.append(hit,path,label,title);this.edgeLayer.append(g);item={g,hit,path,label,title};this.edges.set(e.id,item);}
        item.edge=e;item.index=index;item.g.dataset.from=e.from;item.g.dataset.to=e.to;item.g.dataset.visualOnly=e.visualOnly?'true':'false';item.g.setAttribute('role','button');item.g.setAttribute('tabindex','0');item.hit.setAttribute('stroke-width',e.visualOnly?24:14);item.g.setAttribute('class',e.visualOnly?'visual-candidate':'');item.path.setAttribute('class',`edge ${e.role==='component'?'component-edge':''} ${e.visualOnly?'candidate-edge':''} ${e.highlight?'candidate-highlight':''}`);
        const title=e.displayTitle||(e.role==='component'?`компонент${e.componentRole?' · '+e.componentRole:''}`:e.type||'связь без типа');item.g.setAttribute('aria-label',`${e.visualOnly?'Кандидат':'Ребро'} ${title}`);item.label.textContent='';item.title.textContent=`${title}\n${e.notes||''}`;
        if(e.color){item.path.style.stroke=e.color;item.label.style.fill=e.color;if(!this.markers.has(e.color)){const id=`arrow-${this.host.id}-${this.markers.size}`,m=svgElement('marker',{id,markerWidth:8,markerHeight:8,refX:7,refY:4,orient:'auto'});m.append(svgElement('path',{d:'M0 0 L8 4 L0 8',fill:e.color}));this.defs.append(m);this.markers.set(e.color,id);}item.path.setAttribute('marker-end',e.visualOnly?'':`url(#${this.markers.get(e.color)})`);}else{item.path.style.stroke='';item.label.style.fill='';item.path.setAttribute('marker-end',e.visualOnly?'':`url(#arrow-${this.host.id})`);}
        this.incident.get(e.from)?.add(e.id);this.incident.get(e.to)?.add(e.id);this.paintEdge(item);
      });
      this.contextEdges=graph.contextEdges||[];this.paintContexts();
      if(!this.camera){const size=this.size();this.camera=GraphGeometry.fit(graph.nodes.map(n=>this.positions.get(n.id)).concat(this.contextPoints||[]),size.width,size.height);if(this.camera.scale<.6){const p=this.positions.get(focus)||{x:0,y:0};this.camera={...p,scale:1};}}
      this.paintCamera();this.changed();
    }
    paintEdge(item){const a=this.positions.get(item.edge.from),b=this.positions.get(item.edge.to);if(!a||!b)return;const aa=this.options.circular?{...a,radius:this.radii.get(item.edge.from)}:a,bb=item.edge.from===item.edge.to?aa:this.options.circular?{...b,radius:this.radii.get(item.edge.to)}:b;const p=GraphGeometry.edge(aa,bb,item.index);item.geometry=p;item.path.setAttribute('d',p.d);item.hit.setAttribute('d',p.d);item.label.setAttribute('x',p.x);item.label.setAttribute('y',p.y);}
    paintContexts(){
      const rects=GraphGeometry.obstacles([...this.nodes.keys()].map(id=>this.options.circular?{...this.positions.get(id),radius:this.radii.get(id)}:this.positions.get(id))),keep=new Set(),started=performance.now();this.contextPoints=[];let blocked=0,filtered=0,limited=0,attempted=0;
      for(const [i,c] of (this.contextEdges||[]).entries()){
        const from=this.edges.get(c.from),to=this.edges.get(c.to);if(!from?.geometry||!to?.geometry){filtered++;continue;}if(attempted++>=800||performance.now()-started>(this.options.contextBudgetMs||Infinity)){limited++;continue;}
        const start=GraphGeometry.anchor(from.geometry,rects,i%3),end=GraphGeometry.anchor(to.geometry,rects,(i+1)%3),points=GraphGeometry.orthogonal(start,end,rects);
        if(!points){blocked++;continue;}keep.add(c.id);this.contextPoints.push(...points);
        let item=this.contexts.get(c.id);if(!item){const g=svgElement('g',{'data-graph-context':c.id,role:'button',tabindex:0}),hit=svgElement('path',{'class':'context-hit',fill:'none',stroke:'transparent','stroke-width':12}),path=svgElement('path',{'class':'context-edge',fill:'none','marker-end':`url(#context-arrow-${this.host.id})`}),source=svgElement('circle',{'class':'context-port',r:3}),target=svgElement('circle',{'class':'context-port target-port',r:3}),title=svgElement('title');g.append(hit,path,source,target,title);this.contextLayer.append(g);item={g,hit,path,source,target,title};this.contexts.set(c.id,item);}
        const d=points.map((p,j)=>`${j?'L':'M'} ${p.x} ${p.y}`).join(' ');item.path.setAttribute('d',d);item.hit.setAttribute('d',d);item.g.dataset.from=c.from;item.g.dataset.to=c.to;item.g.dataset.points=JSON.stringify(points);item.g.setAttribute('aria-label',`Контекст ${c.id}: ${c.from} → ${c.to}`);item.title.textContent=`Контекст ${c.id}\n${from.edge.displayTitle||c.from}\n→ ${to.edge.displayTitle||c.to}`;
        for(const [port,p] of [[item.source,start],[item.target,end]]){port.setAttribute('cx',p.x);port.setAttribute('cy',p.y);}
      }
      for(const [id,item] of this.contexts)if(!keep.has(id)){item.g.remove();this.contexts.delete(id);}
      this.host.dataset.contextShown=String(keep.size);this.host.dataset.contextBlocked=String(blocked);this.host.dataset.contextFiltered=String(filtered);this.host.dataset.contextLimited=String(limited);
      this.legend.hidden=!this.contextEdges?.length;this.legend.textContent=`Пунктир → контекст между рёбрами · ${keep.size}/${this.contextEdges?.length||0}${blocked?` · не проложено: ${blocked} (переместите поля или откройте список)`:''}${filtered?` · вне вида: ${filtered}`:''}${limited?` · сверх лимита: ${limited}`:''}`;
    }
    paintNode(id){const p=this.positions.get(id);this.nodes.get(id)?.setAttribute('transform',`translate(${p.x},${p.y})`);for(const edge of this.incident.get(id)||[])this.paintEdge(this.edges.get(edge));this.paintContexts();this.paintLabels();}
    paintCamera(){if(!this.camera)return;const {width,height}=this.size(),c=this.camera;this.svg.setAttribute('viewBox',`${c.x-width/c.scale/2} ${c.y-height/c.scale/2} ${width/c.scale} ${height/c.scale}`);this.host.dataset.zoom=String(Math.round(c.scale*100));this.host.dataset.camera=JSON.stringify(c);this.host.classList.toggle('overview',c.scale<.45);this.options.cameraChanged?.(c);this.paintLabels();}
    paintLabels(){
      if(!this.options.circular||!this.camera)return;
      const scale=this.camera.scale,mode=this.options.labelMode?.()||'auto';if(scale>=.85)this.autoLabels=true;else if(scale<=.65)this.autoLabels=false;this.host.dataset.autoLabels=String(!!this.autoLabels);
      const obstacles=[...this.nodes].map(([id])=>{const p=this.positions.get(id),r=this.radii.get(id);return {id,l:(p.x-r)*scale,r:(p.x+r)*scale,t:(p.y-r)*scale,b:(p.y+r)*scale};}),boxes=[],nodes=[...this.nodes].sort(([a],[b])=>Number(b===this.focus||this.nodes.get(b).classList.contains('search-match'))-Number(a===this.focus||this.nodes.get(a).classList.contains('search-match')));
      for(const [id,g] of nodes){const p=this.positions.get(id),text=g.children[1],forced=id===this.focus||id===this.hovered||id===this.focused||g.classList.contains('search-match');let shown=forced||mode==='always'||mode==='auto'&&this.autoLabels;if(g.labelText!==text.textContent){text.style.display='block';text.style.fontSize='13px';g.labelText=text.textContent;g.labelWidth=text.getComputedTextLength()||text.textContent.length*8;}text.style.fontSize=(13/scale)+'px';text.style.strokeWidth=String(3/scale);const width=g.labelWidth+4,size=this.size(),sx=(p.x-this.camera.x)*scale+size.width/2,sy=(p.y-this.camera.y)*scale+size.height/2,radius=this.radii.get(id),anchor=sx<width/2+8?'start':sx>size.width-width/2-8?'end':'middle',below=sy-radius*scale<25; text.setAttribute('text-anchor',anchor);text.setAttribute('y',below?radius+20/scale:-radius-8/scale);const left=p.x*scale-(anchor==='middle'?width/2:anchor==='end'?width:0),box={l:left,r:left+width,t:below?(p.y+radius)*scale+4:(p.y-radius)*scale-25,b:below?(p.y+radius)*scale+24:(p.y-radius)*scale-4};if(shown&&!forced&&mode==='auto'&&[...boxes,...obstacles.filter(o=>o.id!==id)].some(b=>box.l<b.r&&box.r>b.l&&box.t<b.b&&box.b>b.t))shown=false;if(shown)boxes.push(box);text.style.display=shown?'block':'none';g.dataset.labelShown=String(shown);}
    }
    fit(){this.remember();const {width,height}=this.size();this.camera=GraphGeometry.fit([...this.nodes.keys()].map(id=>this.positions.get(id)).concat(this.contextPoints||[]),width,height,this.options.minScale);this.paintCamera();this.changed();}
    center(id){const p=this.positions.get(id);if(!p)return;this.remember();this.camera={...p,scale:this.camera?.scale||1};this.paintCamera();this.changed();}
    back(){const c=this.frames.pop();if(c){this.camera=c;this.paintCamera();this.changed();}}
    setCamera(camera){if(camera){this.camera={...camera};this.paintCamera();this.changed();}}
    zoom(factor,anchor=this.camera,remember=true){if(!this.camera)return;if(remember)this.remember();const {width,height}=this.size();this.camera=GraphGeometry.zoom(this.camera,factor,anchor,width,height,this.options.minScale);this.paintCamera();this.changed();}
    point(e){const p=this.svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;return p.matrixTransform(this.svg.getScreenCTM().inverse());}
    flush(){if(this.pending){cancelAnimationFrame(this.pending);this.pending=null;}if(this.drag?.id)this.paintNode(this.drag.id);else this.paintCamera();}
    bind(){
      this.svg.onpointerdown=e=>{const id=e.target.closest('[data-graph-node]')?.dataset.graphNode;if(e.button!==0||!this.options.canInteract?.(id))return;e.preventDefault();this.svg.focus({preventScroll:true});const edgeId=e.target.closest('[data-graph-edge]')?.dataset.graphEdge,contextId=e.target.closest('[data-graph-context]')?.dataset.graphContext,p=this.point(e);this.drag={id,edgeId,contextId,additive:e.ctrlKey||e.metaKey||e.shiftKey,start:p,original:id?{...this.positions.get(id)}:null,camera:{...this.camera},clientX:e.clientX,clientY:e.clientY,moved:false};this.host.classList.add('dragging');this.svg.setPointerCapture(e.pointerId);};
      this.svg.onpointermove=e=>{
        const d=this.drag;if(!d)return;if(Math.hypot(e.clientX-d.clientX,e.clientY-d.clientY)>3)d.moved=true;if(!d.moved)return;
        if(d.id){const p=this.point(e);this.positions.set(d.id,{x:Math.max(-100000,Math.min(100000,d.original.x+p.x-d.start.x)),y:Math.max(-100000,Math.min(100000,d.original.y+p.y-d.start.y))});}
        else {this.camera={...d.camera,x:d.camera.x-(e.clientX-d.clientX)/d.camera.scale,y:d.camera.y-(e.clientY-d.clientY)/d.camera.scale};}
        if(!this.pending)this.pending=requestAnimationFrame(()=>{this.pending=null;this.flush();});
      };
      this.svg.onpointerup=async e=>{const d=this.drag;if(!d)return;this.flush();this.drag=null;this.host.classList.remove('dragging');if(this.svg.hasPointerCapture(e.pointerId))this.svg.releasePointerCapture(e.pointerId);if(!d.moved){if(d.id)this.options.select(d.id,d.additive);else if(d.contextId)this.options.editContext?.(d.contextId);else if(d.edgeId)this.options.editEdge?.(d.edgeId);return;}if(!d.id){this.frames.push(d.camera);this.frames=this.frames.slice(-40);this.changed();return;}try{await this.options.savePosition(d.id,{...this.positions.get(d.id)});}catch(error){this.positions.set(d.id,d.original);this.paintNode(d.id);this.options.error(error);}this.changed();};
      this.svg.onpointercancel=()=>{if(this.drag?.id){this.positions.set(this.drag.id,this.drag.original);this.paintNode(this.drag.id);}else if(this.drag)this.camera=this.drag.camera;this.drag=null;this.host.classList.remove('dragging');this.paintCamera();this.changed();};
      this.svg.onlostpointercapture=()=>{if(this.drag)this.svg.onpointercancel();};
      this.svg.addEventListener('wheel',e=>{e.preventDefault();if(this.drag)return;const delta=e.deltaY*(e.deltaMode===1?16:e.deltaMode===2?this.size().height:1),factor=Math.exp(-Math.max(-300,Math.min(300,delta))*.002);const anchor=this.point(e),remember=!this.wheelTimer;if(remember)this.remember();clearTimeout(this.wheelTimer);this.zoom(factor,anchor,false);this.options.sharedZoom?.(factor,remember);this.wheelTimer=setTimeout(()=>{this.wheelTimer=null;this.changed();},160);},{passive:false});
      this.svg.ondblclick=e=>{const id=e.target.closest('[data-graph-node]')?.dataset.graphNode;if(id)this.options.editNode?.(id);};
      this.svg.oncontextmenu=e=>{if(!this.options.contextMenu)return;e.preventDefault();if(this.options.canInteract?.()===false)return;const id=e.target.closest('[data-graph-node]')?.dataset.graphNode,edge=e.target.closest('[data-graph-edge]')?.dataset.graphEdge,context=e.target.closest('[data-graph-context]')?.dataset.graphContext;this.options.contextMenu(id?'node':context?'context':edge?'edge':'canvas',id||context||edge,e);};
      this.svg.onkeydown=e=>{const id=e.target.closest('[data-graph-node]')?.dataset.graphNode,edge=e.target.closest('[data-graph-edge]')?.dataset.graphEdge,context=e.target.closest('[data-graph-context]')?.dataset.graphContext;if(this.options.contextMenu&&(e.key==='ContextMenu'||e.key==='F10'&&e.shiftKey)){e.preventDefault();if(this.options.canInteract?.()===false)return;const r=e.target.getBoundingClientRect();this.options.contextMenu(id?'node':context?'context':edge?'edge':'canvas',id||context||edge,{clientX:r.left+r.width/2,clientY:r.top+r.height/2});return;}if(e.key==='Enter'){if(id){e.preventDefault();if(this.options.activateNode)this.options.activateNode(id);else{this.options.select(id);this.options.editNode?.(id);}}else if(context){e.preventDefault();this.options.editContext?.(context);}else if(edge){e.preventDefault();this.options.editEdge?.(edge);}}if(['+','=','-'].includes(e.key)){e.preventDefault();this.zoom(e.key==='-'?1/1.2:1.2);}if(e.key==='Home'){e.preventDefault();this.center(this.study.rootId);}};
    }
  };
}
