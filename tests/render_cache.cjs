const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');const {fixture,root}=require('./ui_fixture.cjs');
(async()=>{
 const data=JSON.parse(fs.readFileSync(path.join(root,'atlas/official-data.json'),'utf8'));
 const f=await fixture({html:'atlas/official-index.html',url:'http://127.0.0.1:8892/',fetch:async url=>({ok:true,json:async()=>String(url).includes('official-data.json')?data:{records:data.records,legacy:[],mappings:{},token:'test'}})});const {w}=f;
 let uploads=0,draws=0;const frames=new Map();let frame=0;
 w.requestAnimationFrame=fn=>{frames.set(++frame,fn);return frame};w.cancelAnimationFrame=id=>frames.delete(id);
 const gl=new Proxy({bufferData:()=>uploads++,drawArrays:()=>draws++,getShaderParameter:()=>true,getProgramParameter:()=>true},{get:(o,k)=>o[k]||(()=>({}))});
 w.HTMLCanvasElement.prototype.getContext=type=>type==='webgl'?gl:null;for(const [k,v] of [['clientWidth',900],['clientHeight',650]])Object.defineProperty(w.HTMLCanvasElement.prototype,k,{get:()=>v});
 const t=await f.map(`\nsetView('3d');export {renderFrame,draw};export function move(){cam.yaw+=.01;cam.cx+=.1}export function choose(){selected=records.find(r=>r.floor===floor)}export function edit(){records=records.map(r=>({...r,angle:(r.angle||0)+90}))}export function changeFloor(){floor=4}export function filter(){document.querySelector('#search').value='test';lastMatches=[]}`);
 t.renderFrame();const first=uploads;assert(first>=2);for(let i=0;i<60;i++){t.move();t.renderFrame()}assert.equal(uploads,first,'camera does not upload geometry');t.choose();t.renderFrame();assert.equal(uploads,first+1);t.edit();t.renderFrame();assert.equal(uploads,first+2);t.filter();t.renderFrame();assert.equal(uploads,first+3);t.changeFloor();t.renderFrame();assert.equal(uploads,first+5);
 for(let i=0;i<100;i++)t.draw();assert.equal(frames.size,1);assert.equal(f.errors.length,0,f.errors.join('\n'));w.close();console.log('PASS: current official map, 60 camera frames without geometry uploads, selection/edit/filter/floor invalidation and coalesced rendering');
})().catch(error=>{console.error(error);process.exitCode=1});
