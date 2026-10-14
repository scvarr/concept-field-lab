'use strict';
// One transient menu shared by both graph surfaces. No graph data is stored here.
window.CanvasMenu = class {
  constructor() {
    this.host=document.createElement('div');this.host.className='canvas-menu';this.host.hidden=true;this.host.setAttribute('role','menu');document.body.append(this.host);
    document.addEventListener('pointerdown',e=>{if(!this.host.contains(e.target))this.close(false);});
    window.addEventListener('resize',()=>this.close(false));
    window.addEventListener('scroll',e=>{if(!this.host.contains(e.target))this.close(false);},true);
    this.host.onkeydown=e=>{
      const buttons=[...this.host.querySelectorAll('button:not(:disabled)')],index=buttons.indexOf(document.activeElement);
      if(e.key==='Escape'){e.preventDefault();this.close();}
      else if(e.key==='Tab')this.close(false);
      else if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();buttons[e.key==='Home'?0:e.key==='End'?buttons.length-1:(index+(e.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length]?.focus();}
    };
  }
  close(focus=true) { if(this.host.hidden)return;this.host.hidden=true;if(focus&&this.previous?.isConnected)this.previous.focus({preventScroll:true}); }
  open(event,title,actions) {
    this.close(false);this.previous=document.activeElement;this.host.replaceChildren();
    const heading=document.createElement('strong');heading.textContent=title;this.host.append(heading);this.host.setAttribute('aria-label',title);
    for(const action of actions){const b=document.createElement('button');b.type='button';b.setAttribute('role','menuitem');b.textContent=action.label;b.disabled=!!action.disabled;b.dataset.canvasAction=action.id;
      b.onclick=()=>{this.close(false);action.run();};this.host.append(b);}
    this.host.hidden=false;const rect=this.host.getBoundingClientRect(),anchor=event?.currentTarget?.getBoundingClientRect?.();
    const x=event?.clientX??anchor?.left??12,y=event?.clientY??anchor?.bottom??60;
    this.host.style.left=Math.max(8,Math.min(x,innerWidth-rect.width-8))+'px';this.host.style.top=Math.max(8,Math.min(y,innerHeight-rect.height-8))+'px';
    this.host.querySelector('button:not(:disabled)')?.focus({preventScroll:true});
  }
};
