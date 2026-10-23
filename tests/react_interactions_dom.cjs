// Evaluate the actual production React bundle against fictional, inert controls.
const assert=require('node:assert/strict'),fs=require('node:fs');
const {fixture}=require('./ui_fixture.cjs');
const settle=()=>new Promise(r=>setTimeout(r,40));
(async()=>{
 const f=await fixture({fetch:async()=>{throw Error('The tools island must never fetch a service')}});
 const {w,run}=f,d=w.document;
 const style=d.createElement('style');style.textContent=fs.readFileSync('frontend/assets/design-system.css','utf8');d.head.append(style);
 w.ResizeObserver=class{observe(){} unobserve(){} disconnect(){}};
 w.HTMLElement.prototype.getClientRects=function(){return this.closest('[hidden], .page:not(.active)')?[]:[{}]};
 w.HTMLElement.prototype.getBoundingClientRect=function(){return{x:0,y:0,left:0,top:0,right:200,bottom:30,width:200,height:30}};
 d.documentElement.dataset.atlasMotion='reduce';
 w.AtlasUI.motion.isReduced=()=>true;
 const fixtureNode=d.createElement('section');fixtureNode.className='panel';fixtureNode.innerHTML='<h2>Fixture actions</h2><button id="safe-action">Safe simulated action</button><button id="restricted-action" disabled>Restricted action</button><label>Fixture field<input id="fixture-field"></label>';
 d.getElementById('workspace').append(fixtureNode);let calls=0;d.getElementById('safe-action').onclick=()=>calls++;
 run(fs.readFileSync('frontend/assets/atlas-interactions.js','utf8'));await settle();await settle();
 assert(w.AtlasInteractions.ready);assert.equal(d.querySelectorAll('.atlas-interactions-host').length,1);assert.equal(d.querySelectorAll('.atlas-reachable-toggle').length,0,'The React island replaces the fallback');
 const click=node=>{assert(node,'Expected an available UI control');const Pointer=w.PointerEvent||w.MouseEvent;node.dispatchEvent(new Pointer('pointerdown',{bubbles:true,button:0,pointerType:'mouse'}));node.dispatchEvent(new w.MouseEvent('mousedown',{bubbles:true,button:0}));node.dispatchEvent(new Pointer('pointerup',{bubbles:true,button:0,pointerType:'mouse'}));node.dispatchEvent(new w.MouseEvent('click',{bubbles:true}));};
 const open=async()=>{click(d.querySelector('[aria-label="Open tools"]'));await settle();};
 const filter=async text=>{const input=d.querySelector('[aria-label="Find a tool or field"]');const setter=Object.getOwnPropertyDescriptor(w.HTMLInputElement.prototype,'value').set;setter.call(input,text);input.dispatchEvent(new w.Event('input',{bubbles:true}));await settle();};
 await open();assert(d.querySelector('.atlas-tools-expanded'));assert.equal(d.activeElement,d.querySelector('[aria-label="Find a tool or field"]'));
 await filter('Restricted action');assert(d.querySelector('[data-tool-id="restricted-action"]').disabled);
 await filter('Safe simulated action');click(d.querySelector('[data-tool-id="safe-action"]'));await settle();assert.equal(calls,1);assert(!d.querySelector('.atlas-tools-body'));
 await open();const fields=[...d.querySelectorAll('[role="tab"]')].find(n=>n.textContent==='Fields');click(fields);await settle();await filter('Fixture field');click(d.querySelector('[data-tool-id="fixture-field"]'));await settle();assert.equal(d.activeElement.id,'fixture-field');assert(!d.querySelector('.atlas-tools-body'));
 await open();d.querySelector('[aria-label="Find a tool or field"]').dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));await settle();assert(!d.querySelector('.atlas-tools-body'));assert.equal(d.activeElement.getAttribute('aria-label'),'Open tools');
 // Keyboard focus can reopen the Radix tooltip after Escape. Its fixed
 // positioned wrapper must remain transparent to clicks on nearby commands.
 d.activeElement.blur();d.querySelector('[aria-label="Open tools"]').focus();await settle();
 const tooltip=d.querySelector('.atlas-tools-tooltip');assert(tooltip,'actual Radix tooltip is mounted on keyboard focus');
 const wrapper=tooltip.closest('[data-radix-popper-content-wrapper]');assert(wrapper,'actual tooltip owns a positioned Radix wrapper');
 assert.equal(w.getComputedStyle(tooltip).pointerEvents,'none');
 assert.equal(w.getComputedStyle(wrapper).pointerEvents,'none','tooltip wrapper cannot block adjacent command controls');
 const interactive=d.createElement('div');interactive.setAttribute('data-radix-popper-content-wrapper','');interactive.innerHTML='<button>Interactive popover action</button>';d.body.append(interactive);
 assert.notEqual(w.getComputedStyle(interactive).pointerEvents,'none','interactive popovers retain pointer input');interactive.remove();
 // A disabled original cannot be activated through a previously enabled React card.
 await open();await filter('Safe simulated action');d.getElementById('safe-action').disabled=true;click(d.querySelector('[data-tool-id="safe-action"]'));await settle();assert.equal(calls,1);assert(d.querySelector('[data-tool-id="safe-action"]').disabled);
 d.getElementById('pageTitle').textContent='Active Directory';await settle();assert(!d.querySelector('.atlas-tools-body'),'Navigation closes the island');
 d.getElementById('workspace').classList.remove('active');d.getElementById('admin').classList.add('active');d.getElementById('pageTitle').textContent='Remote Admin';d.getElementById('barTarget').textContent='OLD-PC';d.getElementById('adminPc').value='MANUAL-PC';
 await open();assert(d.querySelector('.atlas-tools-context-label').textContent.includes('MANUAL-PC'));
 const pc=d.getElementById('adminPc');pc.focus();pc.value='CHANGED-PC';pc.dispatchEvent(new w.Event('input',{bubbles:true}));await settle();assert(d.querySelector('.atlas-tools-context-label').textContent.includes('CHANGED-PC'));assert.equal(d.activeElement,pc,'Context refresh never steals field focus');
 assert.deepEqual(f.errors,[]);w.dispatchEvent(new w.Event('pagehide'));w.close();
 console.log('PASS: actual React/Motion/Radix bundle mounts once, morphs inline, filters actions/fields, retains original handlers and focus, handles Escape, rejects changed restrictions, and closes on navigation without network');
})().catch(e=>{console.error(e);process.exitCode=1});
