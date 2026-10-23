const fs=require('fs'),assert=require('assert/strict');
(async()=>{
 // The Desktop layout (dock, draggable windows, utilities) was removed: one Atlas layout remains.
 const registry=await import('../atlas/command-registry.js');
 assert.equal(registry.COMMANDS.find(c=>c.id==='desktop-mode'),undefined);
 for(const file of ['frontend/index.html','atlas/official-index.html'])assert(!fs.readFileSync(file,'utf8').includes('desktop-mode'),file);
 for(const file of ['desktop.html','desktop.js','desktop-mode.js','desktop-utility.html'])assert(!fs.existsSync('frontend/assets/'+file),file);
 console.log('PASS: single Atlas layout, no Desktop mode command or assets');
})().catch(e=>{console.error(e);process.exit(1)});
