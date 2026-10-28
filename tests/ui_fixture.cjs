const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {JSDOM,VirtualConsole}=require('jsdom');
const root=path.resolve(__dirname,'..');
const consoleFiles=['app.js','console-directory.js','console-deployment.js','personas.js','console-processes.js','slowdown-diagnostics.js','psexec-catalogue.js','psexec-commands.js','console-psexec.js','psexec-terminal.js','action-widgets.js','reboot-monitor.js','knowledge-converter.js','knowledge-base.js','knowledge-articles.js','console-shell.js','inbox-workbench.js','inbox-actions.js','remote-services.js','copilot-diagnostics.js','script-library.js'];
function consoleSource(){return consoleFiles.map(file=>fs.readFileSync(path.join(root,'frontend/assets',file),'utf8')).join('\n')}
async function fixture({html='frontend/index.html',fetch:request,url='http://127.0.0.1:8892/installer'}={}){
 const errors=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(e.message));
 const dom=new JSDOM(fs.readFileSync(path.join(root,html),'utf8'),{url,runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:vc}),w=dom.window,context=dom.getInternalVMContext();
 w.fetch=request||((url,o)=>fetch(new URL(url,w.location.href),o));w.Headers=Headers;w.AbortController=AbortController;w.confirm=()=>false;w.matchMedia=()=>({matches:true,addEventListener(){}});w.ResizeObserver=class{observe(){}};
 w.HTMLElement.prototype.scrollIntoView=function(){};w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'))};
 const modules=new Map();
 async function moduleFor(spec){const file=path.join(root,'atlas',path.basename(spec.split(/[?#]/,1)[0]));if(modules.has(file))return modules.get(file);const pending=(async()=>{const mod=new vm.SourceTextModule(fs.readFileSync(file,'utf8'),{context,identifier:file});await mod.link(moduleFor);await mod.evaluate();return mod})();modules.set(file,pending);return pending}
 const run=(source)=>vm.runInContext(source,context,{importModuleDynamically:moduleFor});
 for(const file of ['client.js','shared-ui.js','machine-health.js'])run(fs.readFileSync(path.join(root,'frontend/assets',file),'utf8'));
 return {dom,w,context,run,errors,async console(){run(consoleSource());run(fs.readFileSync(path.join(root,'frontend/assets/remote-software.js'),'utf8'))},async map(tail=''){const mod=new vm.SourceTextModule(fs.readFileSync(path.join(root,'atlas/official-app.js'),'utf8')+tail,{context,identifier:'official-app',importModuleDynamically:moduleFor});await mod.link(moduleFor);await mod.evaluate();return mod.namespace}};
}
module.exports={fixture,consoleSource,consoleFiles,root};
