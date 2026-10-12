'use strict';

// Geometry is independent of application state, persistence and the rendering surface.
const GraphGeometry = {
  edge(a,b,index=0) {
    if(a===b){const spread=Math.max(0,index-1)*24;return {d:`M ${a.x+65} ${a.y-8} C ${a.x+155+spread} ${a.y-105-spread}, ${a.x-65-spread} ${a.y-110-spread}, ${a.x-35} ${a.y-30}`,x:a.x+40,y:a.y-70-spread};}
    const dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy)||1,offset=index===1?0:index===0?-12:(index%2===0?index/2:-(index-1)/2)*22;
    const x=(a.x+b.x)/2-dy/len*offset,y=(a.y+b.y)/2+dx/len*offset;
    // Intersect the ray with the rectangular node boundary (80 by 28 half-size).
    const t=Math.min(dx?80/Math.abs(dx):Infinity,dy?28/Math.abs(dy):Infinity);
    const pad=Number.isFinite(t)?t:0;
    return {d:`M ${a.x+dx*pad} ${a.y+dy*pad} Q ${x} ${y} ${b.x-dx*pad} ${b.y-dy*pad}`,x,y:y-7};
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
      this.host=host;this.options=options;this.nodes=new Map();this.edges=new Map();this.incident=new Map();this.positions=new Map();this.camera=null;this.frames=[];
      this.svg=svgElement('svg',{role:'img',tabindex:'0','aria-label':'Граф'});
      const defs=svgElement('defs'),marker=svgElement('marker',{id:`arrow-${host.id}`,markerWidth:8,markerHeight:8,refX:7,refY:4,orient:'auto'});this.defs=defs;this.markers=new Map();
      marker.append(svgElement('path',{d:'M0 0 L8 4 L0 8',fill:'#92aaa0'}));defs.append(marker);
      this.edgeLayer=svgElement('g');this.nodeLayer=svgElement('g');this.svg.append(defs,this.edgeLayer,this.nodeLayer);host.replaceChildren(this.svg);
      this.bind();this.observer=new ResizeObserver(()=>this.paintCamera());this.observer.observe(host);
    }
    size(){return {width:Math.max(1,this.host.clientWidth),height:Math.max(1,this.host.clientHeight)};}
    snapshot(){return {camera:this.camera&&{...this.camera},frames:this.frames.slice(-40),positions:Object.fromEntries(this.positions)};}
    changed(){this.options.changed?.(this.snapshot());}
    remember(){if(this.camera)this.frames.push({...this.camera});this.frames=this.frames.slice(-40);}
    restore(snapshot){this.camera=snapshot?.camera&&{...snapshot.camera};this.frames=snapshot?.frames||[];this.positions=new Map(Object.entries(snapshot?.positions||{}));}
    update(s,graph,focus,markings=new Map(),layout=new Map()) {
      this.study=s;this.focus=focus;this.svg.setAttribute('aria-label',`Граф ${s.title}`);
      const ids=new Set(graph.nodes.map(n=>n.id));
      for(const [id,e]of this.nodes)if(!ids.has(id)){e.remove();this.nodes.delete(id);}
      for(const n of graph.nodes) {
        const saved=Number.isFinite(n.x)&&Number.isFinite(n.y)?{x:n.x,y:n.y}:null;
        this.positions.set(n.id,saved||this.positions.get(n.id)||layout.get(n.id)||{x:0,y:0});
        let g=this.nodes.get(n.id);
        if(!g){g=svgElement('g',{'data-graph-node':n.id,role:'button',tabindex:0});g.append(svgElement('rect',{x:-80,y:-28,width:160,height:56,rx:9}),svgElement('text',{'text-anchor':'middle',y:-2}),svgElement('text',{'class':'kind-label','text-anchor':'middle',y:15}),svgElement('title'));this.nodeLayer.append(g);this.nodes.set(n.id,g);}
        const name=n.label||`α · ${n.id.slice(0,8)}`;
        g.setAttribute('class',`node ${n.structure==='combination'?'combination-node':''} ${n.id===focus?'selected':''} ${markings.get(n.id)||''}`);
        g.setAttribute('aria-label',`Узел ${name}`);g.children[1].textContent=name.length>21?name.slice(0,20)+'…':name;g.children[2].textContent=(n.badge||n.kind||'').slice(0,26);g.children[3].textContent=`${name}\n${n.notes||''}`;
        const p=this.positions.get(n.id);g.setAttribute('transform',`translate(${p.x},${p.y})`);
      }
      const shown=graph.edges.slice(0,3000),edgeIds=new Set(shown.map(e=>e.id));
      for(const [id,item]of this.edges)if(!edgeIds.has(id)){item.g.remove();this.edges.delete(id);}
      this.incident=new Map(graph.nodes.map(n=>[n.id,new Set()]));
      const parallel=new Map();
      shown.forEach(e=>{
        const pair=JSON.stringify([e.from,e.to].sort()),index=(parallel.get(pair)||0)+1;parallel.set(pair,index);
        let item=this.edges.get(e.id);
        if(!item){const g=svgElement('g',{'data-graph-edge':e.id}),hit=svgElement('path',{'class':'edge-hit',fill:'none',stroke:'transparent','stroke-width':14});const path=svgElement('path',{'marker-end':`url(#arrow-${this.host.id})`}),label=svgElement('text',{'class':'edge-label','text-anchor':'middle'}),title=svgElement('title');g.append(hit,path,label,title);this.edgeLayer.append(g);item={g,hit,path,label,title};this.edges.set(e.id,item);}
        item.edge=e;item.index=index;item.g.dataset.from=e.from;item.g.dataset.to=e.to;item.g.dataset.visualOnly=e.visualOnly?'true':'false';item.g.setAttribute('role','button');item.g.setAttribute('tabindex','0');item.hit.setAttribute('stroke-width',e.visualOnly?24:14);item.g.setAttribute('class',e.visualOnly?'visual-candidate':'');item.path.setAttribute('class',`edge ${e.role==='component'?'component-edge':''} ${e.visualOnly?'candidate-edge':''} ${e.highlight?'candidate-highlight':''}`);
        const title=e.displayTitle||(e.role==='component'?`компонент${e.componentRole?' · '+e.componentRole:''}`:e.type||'связь без типа');item.g.setAttribute('aria-label',`${e.visualOnly?'Кандидат':'Ребро'} ${title}`);item.label.textContent=title.slice(0,48);item.title.textContent=`${title}\n${e.notes||''}`;
        if(e.color){item.path.style.stroke=e.color;item.label.style.fill=e.color;if(!this.markers.has(e.color)){const id=`arrow-${this.host.id}-${this.markers.size}`,m=svgElement('marker',{id,markerWidth:8,markerHeight:8,refX:7,refY:4,orient:'auto'});m.append(svgElement('path',{d:'M0 0 L8 4 L0 8',fill:e.color}));this.defs.append(m);this.markers.set(e.color,id);}item.path.setAttribute('marker-end',e.visualOnly?'':`url(#${this.markers.get(e.color)})`);}else{item.path.style.stroke='';item.label.style.fill='';item.path.setAttribute('marker-end',e.visualOnly?'':`url(#arrow-${this.host.id})`);}
        this.incident.get(e.from)?.add(e.id);this.incident.get(e.to)?.add(e.id);this.paintEdge(item);
      });
      if(!this.camera){const size=this.size();this.camera=GraphGeometry.fit(graph.nodes.map(n=>this.positions.get(n.id)),size.width,size.height);if(this.camera.scale<.6){const p=this.positions.get(focus)||{x:0,y:0};this.camera={...p,scale:1};}}
      this.paintCamera();this.changed();
    }
    paintEdge(item){const a=this.positions.get(item.edge.from),b=this.positions.get(item.edge.to);if(!a||!b)return;const p=GraphGeometry.edge(a,b,item.index);item.path.setAttribute('d',p.d);item.hit.setAttribute('d',p.d);item.label.setAttribute('x',p.x);item.label.setAttribute('y',p.y);}
    paintNode(id){const p=this.positions.get(id);this.nodes.get(id)?.setAttribute('transform',`translate(${p.x},${p.y})`);for(const edge of this.incident.get(id)||[])this.paintEdge(this.edges.get(edge));}
    paintCamera(){if(!this.camera)return;const {width,height}=this.size(),c=this.camera;this.svg.setAttribute('viewBox',`${c.x-width/c.scale/2} ${c.y-height/c.scale/2} ${width/c.scale} ${height/c.scale}`);this.host.dataset.zoom=String(Math.round(c.scale*100));this.host.dataset.camera=JSON.stringify(c);this.host.classList.toggle('overview',c.scale<.45);this.options.cameraChanged?.(c);}
    fit(){this.remember();const {width,height}=this.size();this.camera=GraphGeometry.fit([...this.nodes.keys()].map(id=>this.positions.get(id)),width,height,this.options.minScale);this.paintCamera();this.changed();}
    center(id){const p=this.positions.get(id);if(!p)return;this.remember();this.camera={...p,scale:this.camera?.scale||1};this.paintCamera();this.changed();}
    back(){const c=this.frames.pop();if(c){this.camera=c;this.paintCamera();this.changed();}}
    setCamera(camera){if(camera){this.camera={...camera};this.paintCamera();this.changed();}}
    zoom(factor,anchor=this.camera,remember=true){if(!this.camera)return;if(remember)this.remember();const {width,height}=this.size();this.camera=GraphGeometry.zoom(this.camera,factor,anchor,width,height,this.options.minScale);this.paintCamera();this.changed();}
    point(e){const p=this.svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;return p.matrixTransform(this.svg.getScreenCTM().inverse());}
    flush(){if(this.pending){cancelAnimationFrame(this.pending);this.pending=null;}if(this.drag?.id)this.paintNode(this.drag.id);else this.paintCamera();}
    bind(){
      this.svg.onpointerdown=e=>{const id=e.target.closest('[data-graph-node]')?.dataset.graphNode;if(e.button!==0||!this.options.canInteract?.(id))return;e.preventDefault();this.svg.focus({preventScroll:true});const edgeId=e.target.closest('[data-graph-edge]')?.dataset.graphEdge,p=this.point(e);this.drag={id,edgeId,additive:e.ctrlKey||e.metaKey||e.shiftKey,start:p,original:id?{...this.positions.get(id)}:null,camera:{...this.camera},clientX:e.clientX,clientY:e.clientY,moved:false};this.host.classList.add('dragging');this.svg.setPointerCapture(e.pointerId);};
      this.svg.onpointermove=e=>{
        const d=this.drag;if(!d)return;if(Math.hypot(e.clientX-d.clientX,e.clientY-d.clientY)>3)d.moved=true;if(!d.moved)return;
        if(d.id){const p=this.point(e);this.positions.set(d.id,{x:Math.max(-100000,Math.min(100000,d.original.x+p.x-d.start.x)),y:Math.max(-100000,Math.min(100000,d.original.y+p.y-d.start.y))});}
        else {this.camera={...d.camera,x:d.camera.x-(e.clientX-d.clientX)/d.camera.scale,y:d.camera.y-(e.clientY-d.clientY)/d.camera.scale};}
        if(!this.pending)this.pending=requestAnimationFrame(()=>{this.pending=null;this.flush();});
      };
      this.svg.onpointerup=async e=>{const d=this.drag;if(!d)return;this.flush();this.drag=null;this.host.classList.remove('dragging');if(this.svg.hasPointerCapture(e.pointerId))this.svg.releasePointerCapture(e.pointerId);if(!d.moved){if(d.id)this.options.select(d.id,d.additive);else if(d.edgeId)this.options.editEdge?.(d.edgeId);return;}if(!d.id){this.frames.push(d.camera);this.frames=this.frames.slice(-40);this.changed();return;}try{await this.options.savePosition(d.id,{...this.positions.get(d.id)});}catch(error){this.positions.set(d.id,d.original);this.paintNode(d.id);this.options.error(error);}this.changed();};
      this.svg.onpointercancel=()=>{if(this.drag?.id){this.positions.set(this.drag.id,this.drag.original);this.paintNode(this.drag.id);}else if(this.drag)this.camera=this.drag.camera;this.drag=null;this.host.classList.remove('dragging');this.paintCamera();this.changed();};
      this.svg.onlostpointercapture=()=>{if(this.drag)this.svg.onpointercancel();};
      this.svg.addEventListener('wheel',e=>{e.preventDefault();if(this.drag)return;const delta=e.deltaY*(e.deltaMode===1?16:e.deltaMode===2?this.size().height:1),factor=Math.exp(-Math.max(-300,Math.min(300,delta))*.002);const anchor=this.point(e),remember=!this.wheelTimer;if(remember)this.remember();clearTimeout(this.wheelTimer);this.zoom(factor,anchor,false);this.options.sharedZoom?.(factor,remember);this.wheelTimer=setTimeout(()=>{this.wheelTimer=null;this.changed();},160);},{passive:false});
      this.svg.ondblclick=e=>{const id=e.target.closest('[data-graph-node]')?.dataset.graphNode;if(id)this.options.editNode?.(id);};
      this.svg.onkeydown=e=>{const id=e.target.closest('[data-graph-node]')?.dataset.graphNode,edge=e.target.closest('[data-graph-edge]')?.dataset.graphEdge;if(e.key==='Enter'){if(id){e.preventDefault();this.options.select(id);this.options.editNode?.(id);}else if(edge){e.preventDefault();this.options.editEdge?.(edge);}}if(['+','=','-'].includes(e.key)){e.preventDefault();this.zoom(e.key==='-'?1/1.2:1.2);}if(e.key==='Home'){e.preventDefault();this.center(this.study.rootId);}};
    }
  };
}
