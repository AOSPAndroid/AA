/* Local structured-notes conversion; emits standard editable Draw.io XML. */
(()=>{'use strict';
const uid=()=>crypto.randomUUID();
const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[c]));
const blank=()=>({title:'Diagram from notes',notes:'',nodes:[],edges:[]});
const makeNode=(type,text,x,y)=>({id:uid(),type,text,x,y,w:type==='decision'?190:180,h:type==='decision'?120:80,color:'#e0f2fe'});
  function fromNotes(notes){
    const result={...blank(),title:'Diagram from notes',notes},known=new Map();
    const addLabel=(label)=>{label=label.trim().slice(0,2000);if(!label)return null;if(known.has(label))return known.get(label);if(result.nodes.length>=150)throw Error('Use at most 150 distinct steps per conversion.');const n=makeNode(label.endsWith('?')?'decision':'process',label,100+(result.nodes.length%4)*270,100+Math.floor(result.nodes.length/4)*170);result.nodes.push(n);known.set(label,n.id);return n.id;};
    const link=(a,b,label='')=>{if(a&&b&&a!==b&&!result.edges.some(e=>e.source===a&&e.target===b&&e.text===label))result.edges.push({id:uid(),source:a,target:b,text:label});};
    let previous=null;const stack=[];
    for(const raw of notes.split('\n').filter(s=>s.trim())){
      const indent=raw.match(/^\s*/)[0].replace(/\t/g,'  ').length;
      const line=raw.trim().replace(/^(?:[-*•]|\d+[.)])\s+/,'');if(!line||line.startsWith('#'))continue;
      const parts=line.split(/\s*(?:->|→)\s*/);
      if(parts.length>1){let a=addLabel(parts[0]);for(let i=1;i<parts.length;i++){const m=parts[i].match(/^\[([^\]]+)\]\s*(.*)$/);const b=addLabel(m?m[2]:parts[i]);link(a,b,m?m[1]:'');a=b;}previous=null;stack.length=0;}
      else{const id=addLabel(line);while(stack.length&&stack.at(-1).indent>=indent)stack.pop();if(stack.length)link(stack.at(-1).id,id);else if(previous)link(previous,id);stack.push({indent,id});previous=id;}
    }
    if(!result.nodes.length)throw Error('Add steps or connections to your notes first.');
    const degree=new Map(result.nodes.map(n=>[n.id,0])),level=new Map();
    for(const e of result.edges)degree.set(e.target,degree.get(e.target)+1);
    const queue=result.nodes.filter(n=>degree.get(n.id)===0).map(n=>n.id);for(const id of queue)level.set(id,0);
    for(let i=0;i<queue.length;i++){const id=queue[i];for(const e of result.edges.filter(e=>e.source===id)){level.set(e.target,Math.max(level.get(e.target)||0,level.get(id)+1));degree.set(e.target,degree.get(e.target)-1);if(!degree.get(e.target))queue.push(e.target);}}
    if(queue.length===result.nodes.length&&Math.max(...level.values())<30){const rows=new Map();for(const n of result.nodes){const col=level.get(n.id),row=rows.get(col)||0;rows.set(col,row+1);n.x=80+col*260;n.y=80+row*160;}}
    return result;
  }

function toXml(doc){return `<?xml version="1.0" encoding="UTF-8"?><mxfile host="Atlas"><diagram id="atlas" name="${escape(doc.title)}"><mxGraphModel grid="1" page="0"><root><mxCell id="0"/><mxCell id="1" parent="0"/>${doc.nodes.map(n=>`<mxCell id="${n.id}" value="${escape(n.text)}" style="${{process:'rounded=1;',decision:'rhombus;',terminal:'ellipse;',database:'shape=cylinder;',note:'shape=note;'}[n.type]}whiteSpace=wrap;html=0;fillColor=${n.color};strokeColor=#007fa3;" vertex="1" parent="1"><mxGeometry x="${n.x}" y="${n.y}" width="${n.w}" height="${n.h}" as="geometry"/></mxCell>`).join('')}${doc.edges.map(e=>`<mxCell id="${e.id}" value="${escape(e.text)}" edge="1" source="${e.source}" target="${e.target}" parent="1" style="edgeStyle=orthogonalEdgeStyle;endArrow=classic;html=0;"><mxGeometry relative="1" as="geometry"/></mxCell>`).join('')}</root></mxGraphModel></diagram></mxfile>`;}
window.AtlasKnowledgeConverter={fromNotes,toXml};
})();
