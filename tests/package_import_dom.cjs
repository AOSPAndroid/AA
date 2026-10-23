// Package metadata uploads operate independently of the directory workbook.
const assert = require('node:assert/strict'), fs = require('node:fs');
const {fixture} = require('./ui_fixture.cjs');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
const count = value => value.toLocaleString();
(async () => {
 let finish, saves = 0, previews = 0, statuses = 0;
 const delayed = new Promise(resolve => finish = resolve);
 const preview = {id:'package-stage',source:'package.csv',report:{rows:2003,unique:2000,added:1900,changed:50,unchanged:50,retained:100,source_available:true,matched:1500,source_packages:8000,metadata_only:499,ambiguous:1,duplicates:3,conflicting_duplicates:2,duplicate_examples:[{short_name:'ixExample',rows:4,selected_row:3096,selection:'last_row'}],unmatched_rows:2,unmatched_records:2,unmatched_examples:[{row:15238,short_name:'',package_id:'EPP-RAW',reason:'missing_short_name'},{row:15239,short_name:'../ixExample',package_id:'EPP-PATH',reason:'non_folder_name'}],extra_columns:[],examples:[{short_name:'ixExample',state:'Work in Progress',package_id:'EPP123',packager:'Operator'}]}};
 const f = await fixture({html:'frontend/database.html',url:'http://localhost/manage-database',fetch:async (url, options={}) => {
   assert(!url.startsWith('/api/database/'), 'Package workflow never calls directory APIs');
   if(url==='/api/session')return response({token:'test'});
   if(url==='/api/package-data/import/status') { statuses++; return response({count:statuses===1?100:2100,last_import:null}); }
   if(url==='/api/package-data/import/preview') { previews++; return previews===1 ? delayed : response(preview); }
   if(url==='/api/package-data/import/apply/package-stage') { saves++; return saves===1 ? response({detail:'Preview expired'},409) : response({count:2100,backup:'package-data-test.json.gz'}); }
   if(url==='/api/package-data/import/preview/package-stage' && options.method==='DELETE') return response({ok:true});
   throw Error('Unexpected request '+url);
 }});
 const {w,run} = f,d=w.document,get=id=>d.getElementById('package-data-'+id);
 assert.equal(new Set([...d.querySelectorAll('[id]')].map(node=>node.id)).size,d.querySelectorAll('[id]').length,'Uploader IDs stay unique');
 run(fs.readFileSync('frontend/assets/package-data-import.js','utf8'));await sleep(30);
 assert(!get('validate').disabled && get('review').hidden && get('apply').disabled);
 await get('validate').onclick();assert.match(get('message').textContent,/Choose a package CSV/);assert.equal(previews,0);
 const select=name=>{Object.defineProperty(get('file'),'files',{configurable:true,value:[{name,size:100}]});get('file').onchange();};
 select('users.xlsx');await get('validate').onclick();assert.equal(previews,0);
 select('package.csv');const work=get('validate').onclick();await sleep(30);assert(get('validate').disabled && !get('progress').hidden);
 assert(!d.getElementById('validate').disabled,'A package validation does not disable the directory uploader');
 await get('validate').onclick();assert.equal(previews,1,'Busy state prevents duplicate uploads');
 finish(response(preview));await work;assert(!get('review').hidden && !get('apply').disabled);assert.match(get('summary').textContent,/100 existing records retained/);assert(get('coverage').textContent.includes(`${count(1500)} matched to ${count(8000)}`));
 assert(get('summary').textContent.includes(`${count(2003)} source rows`));assert.match(get('warnings').textContent,/3 duplicate rows reconciled automatically; 2 differing records/);assert.match(get('warnings').textContent,/All original rows and columns are preserved/);
 assert(!get('duplicates').hidden);assert(get('duplicate-examples').textContent.includes(`ixExample · 4 rows · selected row ${count(3096)} (last CSV row)`));
 assert(get('summary').textContent.includes(`${count(2000)} package records`));assert.match(get('warnings').textContent,/2 rows with missing or unusual short names imported as metadata only \(2 records\)/);
 assert(!get('unmatched').hidden);assert(get('unmatched-examples').textContent.includes(`Row ${count(15238)} · EPP-RAW · Short name not supplied · Metadata only`));assert.match(get('unmatched-examples').textContent,/\.\.\/ixExample · Original short name kept/);
 assert(d.getElementById('preview').hidden,'Package preview never opens directory replacement controls');
 await get('apply').onclick();assert.match(get('message').textContent,/Preview expired/);assert(!get('apply').disabled,'A failed save remains retryable');
 select('replacement.csv');assert(get('review').hidden && get('apply').disabled,'Changing the CSV invalidates the prior preview');
 await get('validate').onclick();await get('cancel').onclick();assert(get('review').hidden && get('apply').disabled);
 await get('validate').onclick();await get('apply').onclick();assert(get('message').textContent.includes(`Package data saved: ${count(2100)} records`));assert(get('review').hidden);assert(get('status').textContent.includes(count(2100)));
 assert.deepEqual(f.errors,[]);w.close();console.log('PASS: independent package CSV validation, busy feedback, preview coverage, retry, cancellation and metadata save');
})().catch(error=>{console.error(error);process.exitCode=1});
