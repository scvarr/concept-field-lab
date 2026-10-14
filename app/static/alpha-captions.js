'use strict';
// Pure presentation; no derived text is assigned to graph objects or the dictionary.
(function(root){
  function view(graph,draft){
    if(!draft)return graph;
    const nodes=new Map(graph.nodes.map(n=>[n.id,n])),edges=new Map(graph.edges.map(e=>[e.id,e]));
    for(const [id,e] of edges)if(e.definitionId===draft.id)edges.delete(id);
    for(const n of draft.nodes)nodes.set(n.id,n.existing?(nodes.get(n.id)||n.base||n):n);
    for(const e of draft.edges)edges.set(e.id,e);
    const designations=[...graph.designations];
    for(const n of draft.nodes)if(!graph.nodes.some(v=>v.id===n.id))for(const d of n.designations|| (n.designation?[{text:n.designation}]:[]))designations.push({...d,target:n.id});
    return {nodes:[...nodes.values()],edges:[...edges.values()],designations};
  }
  function create(graph){
    const nodes=new Map(graph.nodes.map(n=>[n.id,n])),terms=new Map(),children=new Map(),memo=new Map();
    for(const d of graph.designations)if(d.text){const rows=terms.get(d.target)||[];rows.push(d.text);terms.set(d.target,rows);}
    for(const e of graph.edges)if(e.role==='component'){const rows=children.get(e.from)||[];rows.push(e.to);children.set(e.from,rows);}
    for(const ids of children.values())ids.sort((a,b)=>Number(nodes.get(a)?.structure==='alpha')-Number(nodes.get(b)?.structure==='alpha'));
    const cut=(s,max=512)=>s.length>max?s.slice(0,max-1)+'…':s;
    function label(id,depth=0,budget={left:256}){
      if(--budget.left<0)return '…';
      const key=id+'@'+depth;if(memo.has(key))return memo.get(key);
      const own=terms.get(id)?.[0],n=nodes.get(id);if(own)return cut(own);
      if(n?.structure!=='alpha')return cut(n?.label||id);
      if(depth>=12)return 'α …';
      const ids=children.get(id)||[];if(!ids.length)return 'α · состав ещё не задан';
      let text='{';for(let i=0;i<ids.length;i++){if(i)text+=', ';text+=label(ids[i],depth+1,budget);if(text.length>=510||budget.left<=0){text=cut(text,510)+'…';break;}}text+='}';
      // Cache only complete computations; a parent's exhausted budget must not poison siblings.
      if(budget.left>0)memo.set(key,text);return text;
    }
    const captions=new Map(graph.nodes.map(n=>[n.id,label(n.id)])),groups=new Map();
    for(const n of graph.nodes)if(n.structure==='alpha'&&!terms.has(n.id)){const text=captions.get(n.id),ids=groups.get(text)||[];ids.push(n.id);groups.set(text,ids);}
    function token(id){let length=8;while(length<id.length&&graph.nodes.some(n=>n.id!==id&&n.id.slice(0,length)===id.slice(0,length)))length++;return id.slice(0,length);}
    const display=id=>{const text=captions.get(id)||label(id);return nodes.get(id)?.structure==='alpha'&&!terms.has(id)&&groups.get(text)?.length>1?text+' · #'+token(id):text;};
    function matches(id,query){const q=query.trim().toLocaleLowerCase('ru').replaceAll('ё','е');if(!q)return true;
      const normalize=s=>String(s).toLocaleLowerCase('ru').replaceAll('ё','е');if(normalize(id+' '+display(id)+' '+(terms.get(id)||[]).join(' ')).includes(q))return true;
      if(nodes.get(id)?.structure!=='alpha'||terms.has(id))return false;
      const queue=[{id,depth:0}],seen=new Set([id]);let cursor=0;
      while(cursor<queue.length){const v=queue[cursor++];if((terms.get(v.id)||[]).some(t=>normalize(t).includes(q)))return true;if(v.depth<20)for(const child of children.get(v.id)||[])if(!seen.has(child)&&queue.length<2048){seen.add(child);queue.push({id:child,depth:v.depth+1});}}return false;
    }
    return {label:id=>captions.get(id)||label(id),display,token,matches,anonymous:id=>nodes.get(id)?.structure==='alpha'&&!terms.has(id)};
  }
  const api={create,view};if(typeof module!=='undefined')module.exports=api;else root.AlphaCaptions=api;
})(typeof window==='undefined'?globalThis:window);
