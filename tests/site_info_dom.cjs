const fs=require('fs'),assert=require('assert/strict'),{JSDOM}=require('jsdom');
(async()=>{
const w=new JSDOM('<body></body>',{url:'http://localhost/',runScripts:'outside-only'}).window;
w.AtlasUI={dialog(){const element=w.document.createElement('dialog'),body=w.document.createElement('div');element.append(body);w.document.body.append(element);return {element,body};}};
let copied;Object.defineProperty(w.navigator,'clipboard',{value:{writeText:async value=>{copied=value;}}});
w.eval(fs.readFileSync('atlas/site-info.js','utf8').replaceAll('export const ','const ').replace('export function openSiteInfo','window.openSiteInfo = function openSiteInfo').replaceAll('export function ','function '));
const dialog=w.openSiteInfo('daas');assert.equal(dialog.querySelectorAll('[role=tab]').length,4);
assert.equal(dialog.querySelector('#site-info-daas').hidden,false);
const copy=dialog.querySelector('#site-info-daas .site-copy');copy.click();await Promise.resolve();assert.equal(copied,'fGLBAZADCTXUsers');
const tab=dialog.querySelector('#site-info-tab-daas');tab.dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowRight'}));assert.equal(dialog.querySelector('#site-info-vdi').hidden,false);
assert(dialog.querySelector('#site-info-vdi').textContent.includes('fGLB-GLO_DaaS_Trader_Prod_VDI'));
assert.equal(w.openSiteInfo('contacts'),dialog);assert.equal(dialog.querySelector('#site-info-contacts').hidden,false);
for(const link of dialog.querySelectorAll('a[target]'))assert.equal(new URL(link.href).hostname,'citrix.cloud.com');
w.close();console.log('PASS: four tabs, keyboard switching, direct opening, exact group copy, tenant links and existing contacts');
})().catch(e=>{console.error(e);process.exit(1)});
