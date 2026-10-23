// Fictional records; clipboard and navigation are simulated.
const fs=require('node:fs'),assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
const w=new JSDOM('<body></body>',{runScripts:'outside-only',url:'http://localhost'}).window,d=w.document;
w.matchMedia=()=>({matches:false,addEventListener(){}});
w.HTMLElement.prototype.scrollIntoView=function(){};
w.HTMLDialogElement.prototype.showModal=function(){this.open=true};
w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'))};
w.HTMLElement.prototype.getBoundingClientRect=function(){return this.classList.contains('atlas-ad-context')?{width:260,height:600}:{left:50,bottom:80}};
const selected=[],copied=[],opened=[],searched=[];
Object.defineProperty(w.navigator,'clipboard',{value:{writeText:async text=>copied.push(text)}});
w.eval(fs.readFileSync('frontend/assets/shared-ui.js','utf8'));
w.AtlasAD={show:(kind,identity,run,action)=>selected.push({kind,identity,run,action})};
w.AtlasContext.configure({openPerson:key=>opened.push(key),search:term=>searched.push(term)});
d.body.innerHTML=w.AtlasUI.person({id:7,name:'Alice <Example>',user_name:'alice',email:'alice+it@example.test',manager:'Bob Example',department:'Trading',location:'Paris'});
const person=d.querySelector('.atlas-person');
const open=node=>node.dispatchEvent(new w.MouseEvent('contextmenu',{bubbles:true,composed:true,cancelable:true,clientX:1023,clientY:767}));
const menu=()=>d.querySelector('.atlas-ad-context');
const button=cmd=>menu().querySelector(`[data-cmd="${cmd}"]`);
const key=key=>d.activeElement.dispatchEvent(new w.KeyboardEvent('keydown',{key,bubbles:true,cancelable:true}));
open(person);assert.equal(d.activeElement.textContent,'See groups');
assert.equal(menu().style.left,'756px');assert.equal(menu().style.top,'160px');
key('End');assert.equal(d.activeElement.dataset.cmd,'copy-user-report');key('Home');key('ArrowUp');assert.equal(d.activeElement.dataset.cmd,'copy-user-report');key('Escape');assert.equal(menu(),null);assert.equal(d.activeElement,person);
for(const [cmd,action] of [['ad-groups','groups'],['ad-compare','compare'],['ad-properties','properties'],['ad-export','export'],['ad-summary','summary']]){
 open(person);button(cmd).click();assert.equal(menu(),null);assert.deepEqual(selected.at(-1),{kind:'user',identity:'alice',run:true,action});
}
open(person);button('copy-email').click();assert.equal(copied.at(-1),'alice+it@example.test');
open(person);button('copy-domain').click();assert.equal(copied.at(-1),'INTRANET\\alice');
open(person);button('user-devices').click();assert.deepEqual(opened,['id:7']);
for(const cmd of ['user-manager','user-department','user-location']){open(person);button(cmd).click();}
assert.deepEqual(searched,['user:Bob Example','department:Trading','location:Paris']);
// A second person's menu must not borrow the currently displayed user's identity.
const other=d.createElement('button');other.setAttribute('data-ad-kind','user');other.setAttribute('data-ad-identity','carol');d.body.append(other);
open(other);assert(button('copy-email').disabled);button('ad-compare').click();assert.equal(selected.at(-1).identity,'carol');
// Context Menu / Shift+F10, dismissal, and composed events from palette results.
person.focus();person.dispatchEvent(new w.KeyboardEvent('keydown',{key:'F10',shiftKey:true,bubbles:true,cancelable:true}));assert(menu());key('Tab');assert.equal(menu(),null);
const shadowHost=d.createElement('div');d.body.append(shadowHost);const shadow=shadowHost.attachShadow({mode:'open'});shadow.innerHTML='<button data-ad-kind="user" data-ad-identity="shadow.account">User</button>';
open(shadow.querySelector('button'));button('ad-groups').click();assert.equal(selected.at(-1).identity,'shadow.account');
open(person);w.dispatchEvent(new w.Event('resize'));assert.equal(menu(),null);
// Phone inventory remains available, without offering computer groups or losing serials.
const phone=d.createElement('article');d.body.append(phone);
w.AtlasContext.bindDevice(phone,{name:'PHONE-7',model_category:'Mobile Device - Handheld',model_id:'APPLE iPhone 13',serial_number:'SERIAL-7',asset_tag:'ASSET-7'});
open(phone);for(const cmd of ['ad-groups','ad-compare','ad-properties','ad-export','ad-summary'])assert(button(cmd).disabled,cmd);
button('copy-serial').click();assert.equal(copied.at(-1),'SERIAL-7');
open(phone);button('inventory').click();assert(d.querySelector('.atlas-dialog-body').textContent.includes('SERIAL-7'));d.querySelector('.atlas-dialog').close();
// A menu inside a modal belongs to that modal's top layer and navigation closes it.
const dialog=w.AtlasUI.dialog('Person');dialog.body.append(person);open(person);assert(dialog.element.contains(menu()));button('ad-compare').click();assert(!dialog.element.isConnected);
d.body.append(person);const meta=d.createElement('meta');meta.name='atlas-mode';meta.content='viewer';d.head.append(meta);
open(person);assert(!button('ad-groups').disabled);for(const cmd of ['ad-compare','ad-properties','ad-export','ad-summary'])assert(button(cmd).disabled,cmd);assert(!button('copy-email').disabled);
w.close();console.log('PASS: exact user context actions, record copy/search, keyboard navigation, viewport clamping, shadow/modal menus, phone inventory and read-only guards');
