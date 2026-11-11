const assert = require('node:assert/strict'),fs = require('node:fs'),zlib = require('node:zlib'),acorn = require('acorn');
const {JSDOM} = require('jsdom');
const code = fs.readFileSync('frontend/assets/atlas-interactions.js');
const ast = acorn.parse(code.toString(), {ecmaVersion:'latest',sourceType:'module'});
assert(!ast.body.some(node=>node.type==='ImportDeclaration'), 'The production module must not need remote libraries or unserved chunks');
assert(code.length<360*1024 && zlib.gzipSync(code).length<115*1024,'The console interaction bundle stays within its reduced performance budget');
for(const file of ['frontend/index.html','frontend/database.html','atlas/official-index.html']){
 const w = new JSDOM(fs.readFileSync(file,'utf8')).window,d = w.document;
 assert.equal(!!d.querySelector('script[type=module][src="/assets/atlas-interactions.js"]'),file==='frontend/index.html','React loads only in the console that owns its islands');
 const sheets=[...d.querySelectorAll('link[rel=stylesheet]')].map(n=>n.getAttribute('href').split('?')[0]);
 assert(sheets.includes('/assets/atlas-interactions.css'));
 assert.equal(sheets.at(-1),'/assets/design-system.css','Atlas geometry remains the final style contract');
 w.close();
}
const css=fs.readFileSync('frontend/assets/atlas-interactions.css','utf8');
assert(css.includes('.atl\\:flex'),'Tailwind utilities are prefixed');assert(!css.includes('box-sizing:border-box'),'Tailwind does not add a global reset');
console.log('PASS: local production bundle and size budget, prefix-only Tailwind utilities, shared entry points and final Atlas style contract');
