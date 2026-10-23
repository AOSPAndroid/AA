// Real Knowledge Base handlers; every API response and editor message is fictional.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const { fixture } = require("./ui_fixture.cjs");
const settle = async () => {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
};
const xml = (label) =>
  `<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="2" parent="1" value="${label}" vertex="1"/></root></mxGraphModel>`;
const documents = ["A", "B"].map((id) => ({
  id,
  title: "Document " + id,
  notes: "Notes " + id,
  xml: xml(id),
  revision: 3,
  updated: "2026-10-06T10:00:00Z",
}));
const response = (data, ok = true) => ({
  ok,
  status: ok ? 200 : 500,
  headers: { get: () => null },
  json: async () => data,
});
async function setup({delaySave=false}={}) {
  const reads = [],
    writes = [], deletes = [], saves = [];
  const f = await fixture({
    fetch: async (url, options = {}) => {
      if (url === "/api/knowledge") return response({ documents });
      if (url === "/api/session") return response({ token: "fixture" });
      if (url.startsWith("/api/knowledge/") && options.method === "PUT") {
        const doc = JSON.parse(options.body);
        writes.push(doc);
        if(delaySave)return new Promise(resolve=>saves.push({finish:()=>resolve(response({revision:doc.revision+1,updated:'2026-10-07T12:00:00Z'}))}));
        return response({
          revision: doc.revision + 1,
          updated: "2026-10-06T10:00:00Z",
        });
      }
      if(url.startsWith('/api/knowledge/')&&options.method==='DELETE')
        return new Promise(resolve=>deletes.push({url,finish:()=>resolve(response({ok:true})),fail:()=>resolve(response({detail:'OBSOLETE DELETE FAILURE'},false))}));
      assert.equal(options.method || "GET", "GET");
      assert(
        url.startsWith("/api/knowledge/"),
        "Unexpected fixture request " + url,
      );
      return new Promise((resolve) =>
        reads.push({
          id: url.split("/").pop(),
          finish: () =>
            resolve(
              response(
                documents.find((doc) => doc.id === url.split("/").pop()),
              ),
            ),
          fail: () =>
            resolve(response({ detail: "OBSOLETE LOAD FAILURE" }, false)),
        }),
      );
    },
  });
  f.run(fs.readFileSync("frontend/assets/knowledge-converter.js", "utf8"));
  f.run(fs.readFileSync("frontend/assets/knowledge-base.js", "utf8"));
  const { w } = f,
    d = w.document,
    api = w.AtlasKnowledge;
  await api.open();
  const open = async (id) => {
    const count = reads.length;
    d.querySelector(`[data-doc="${id}"]`).click();
    await settle();
    assert.equal(
      reads.length,
      count + 1,
      "Document read begins after leaving the draft",
    );
    return reads.at(-1);
  };
  const connect = (captureXml = () => api.getDocument().xml) => {
    const frame = d.getElementById("kbDrawio");
    const emit = (message) =>
      w.dispatchEvent(
        new w.MessageEvent("message", {
          origin: w.location.origin,
          source: frame.contentWindow,
          data: JSON.stringify(message),
        }),
      );
    frame.contentWindow.postMessage = (text) => {
      const message = JSON.parse(text);
      if (message.action === "export")
        emit({ event: "export", xml: captureXml(), message });
    };
    emit({ event: "load" });
    return emit;
  };
  return {
    ...f,
    d,
    api,
    reads,
    writes,
    deletes,
    saves,
    open,
    connect,
    status: () => d.getElementById("kbStatus").textContent,
    close() {
      assert.deepEqual(f.errors, []);
      w.close();
    },
  };
}
(async () => {
  let f = await setup();
  const a = await f.open("A"),
    b = await f.open("B");
  b.finish();
  await settle();
  a.finish();
  await settle();
  assert.equal(
    f.api.getDocument().id,
    "B",
    "Late document A must not replace the latest document B",
  );
  f.close();

  f = await setup();
  const failedA = await f.open("A"),
    goodB = await f.open("B");
  goodB.finish();
  await settle();
  const savedStatus = f.status();
  failedA.fail();
  await settle();
  assert.equal(f.api.getDocument().id, "B");
  assert.equal(
    f.status(),
    savedStatus,
    "An obsolete failure cannot replace current status",
  );
  f.close();

  f = await setup();
  const beforeNew = await f.open("A");
  f.d.querySelector('[data-kb="new"]').click();
  await settle();
  const newId = f.api.getDocument().id;
  beforeNew.finish();
  await settle();
  assert.equal(
    f.api.getDocument().id,
    newId,
    "New invalidates earlier library reads",
  );
  assert.equal(f.api.getDocument().title, "Untitled diagram");
  f.close();

  for (const failure of [false, true]) {
    f = await setup();
    const beforeEdit = await f.open("A"),
      draftId = f.api.getDocument().id;
    const notes = f.d.getElementById("kbNotes");
    notes.value = "NEWER RUNBOOK EDIT";
    notes.dispatchEvent(new f.w.Event("input"));
    const dirtyStatus = f.status();
    failure ? beforeEdit.fail() : beforeEdit.finish();
    await settle();
    assert.equal(f.api.getDocument().id, draftId);
    assert.equal(f.api.getDocument().notes, "NEWER RUNBOOK EDIT");
    assert.equal(
      f.status(),
      dirtyStatus,
      "Newer edits retain their truthful unsaved status",
    );
    assert.equal(f.writes.length, 0);
    f.close();
  }

  f = await setup();
  f.connect();
  const beforeSavedEdit = await f.open("A"),
    savedDraftId = f.api.getDocument().id,
    savedNotes = f.d.getElementById("kbNotes");
  savedNotes.value = "NEWER SAVED RUNBOOK";
  savedNotes.dispatchEvent(new f.w.Event("input"));
  await f.api.command("kb-save");
  const savedEditStatus = f.status();
  assert.match(savedEditStatus, /^Saved/);
  beforeSavedEdit.finish();
  await settle();
  assert.equal(f.api.getDocument().id, savedDraftId);
  assert.equal(f.api.getDocument().notes, "NEWER SAVED RUNBOOK");
  assert.equal(
    f.status(),
    savedEditStatus,
    "Saving a newer edit cannot revive an earlier document load",
  );
  f.close();

  f = await setup();
  const emit = f.connect();
  const beforeAutosave = await f.open("A"),
    diagramId = f.api.getDocument().id;
  emit({ event: "autosave", xml: xml("NEWER DIAGRAM") });
  const autosaveStatus = f.status();
  beforeAutosave.finish();
  await settle();
  assert.equal(f.api.getDocument().id, diagramId);
  assert.equal(f.api.getDocument().xml, xml("NEWER DIAGRAM"));
  assert.equal(f.status(), autosaveStatus);
  f.close();

  f = await setup();
  f.connect(() => xml("CAPTURED EDIT"));
  const capturedDraftId = f.api.getDocument().id,
    afterCapture = await f.open("A");
  assert.equal(f.writes.length, 1);
  assert.equal(f.writes[0].id, capturedDraftId);
  assert.equal(f.writes[0].xml, xml("CAPTURED EDIT"));
  afterCapture.finish();
  await settle();
  assert.equal(
    f.api.getDocument().id,
    "A",
    "Synchronous editor capture is included in the switch context",
  );
  f.close();

  f = await setup();
  const beforeCopy = await f.open("A");
  await f.api.command("kb-copy-document");
  const copyId = f.api.getDocument().id;
  beforeCopy.finish();
  await settle();
  assert.equal(f.api.getDocument().id, copyId);
  assert.match(f.api.getDocument().title, /copy$/);
  f.close();

  f = await setup();
  const beforeImport = await f.open("A"),
    input = f.d.getElementById("kbImport");
  Object.defineProperty(input, "files", {
    value: [
      {
        name: "fixture.atlas.json",
        size: 100,
        text: async () =>
          JSON.stringify({
            title: "Imported fixture",
            notes: "Imported notes",
            xml: xml("IMPORT"),
          }),
      },
    ],
  });
  input.dispatchEvent(new f.w.Event("change"));
  await settle();
  const importId = f.api.getDocument().id;
  assert.equal(f.api.getDocument().title, "Imported fixture");
  beforeImport.finish();
  await settle();
  assert.equal(f.api.getDocument().id, importId);
  f.close();

  const deferred=()=>{let resolve,reject;const promise=new Promise((done,fail)=>{resolve=done;reject=fail});return {promise,resolve,reject};};
  const imported=JSON.stringify({title:'Imported older file',notes:'OLDER IMPORT',xml:xml('OLDER IMPORT')});
  const file=(f,pending)=>{
    const control=f.d.getElementById('kbImport');
    Object.defineProperty(control,'files',{configurable:true,value:[{name:'fictional.atlas.json',size:100,text:()=>pending.promise}]});
    return control;
  };
  const edit=(f,text)=>{const notes=f.d.getElementById('kbNotes');notes.value=text;notes.dispatchEvent(new f.w.Event('input'));};
  for(const change of ['switch','notes','title','failure']){
    f=await setup();const pending=deferred(),control=file(f,pending),opening=control.onchange();
    if(change==='switch'||change==='failure')await f.api.command('kb-new');
    if(change==='title'){const title=f.d.getElementById('kbTitle');title.value='NEWER TITLE';title.dispatchEvent(new f.w.Event('input'));}
    else edit(f,'NEWER IMPORT CONTEXT');
    const current=f.api.getDocument(),currentStatus=f.status(),frame=f.d.getElementById('kbDrawio');
    change==='failure'?pending.reject(Error('OBSOLETE FILE FAILURE')):pending.resolve(imported);await opening;
    assert.deepEqual(f.api.getDocument(),current,'A delayed file read cannot replace '+change+' context');assert.equal(f.status(),currentStatus);assert.equal(f.d.getElementById('kbDrawio'),frame);assert.equal(f.writes.length,0);f.close();
  }
  f=await setup();const oldFile=deferred(),newFile=deferred(),control=file(f,oldFile);let selectedValue='old-file';
  Object.defineProperty(control,'value',{configurable:true,get:()=>selectedValue,set:value=>{selectedValue=value}});
  const oldImport=control.onchange();file(f,newFile);selectedValue='new-file';const newImport=control.onchange();
  oldFile.resolve(imported);await oldImport;assert.equal(selectedValue,'new-file','An older import finally cannot clear the newer file selection');
  newFile.resolve(JSON.stringify({title:'Latest imported file',notes:'LATEST IMPORT',xml:xml('LATEST')}));await newImport;
  assert.equal(f.api.getDocument().notes,'LATEST IMPORT');assert.equal(selectedValue,'');f.close();

  for(const sameDocument of [false,true])for(const failed of [false,true]){
    f=await setup();const opened=await f.open('A');opened.finish();await settle();f.w.confirm=()=>true;
    const deleteOperation=f.api.command('kb-delete-document');await settle();assert.equal(f.deletes.length,1);assert.equal(f.deletes[0].url,'/api/knowledge/A?revision=3');
    if(!sameDocument){const newer=await f.open('B');newer.finish();await settle();}
    edit(f,'NEWER DELETE CONTEXT');const current=f.api.getDocument(),currentStatus=f.status(),frame=f.d.getElementById('kbDrawio');
    failed?f.deletes[0].fail():f.deletes[0].finish();await deleteOperation;
    assert.equal(f.api.getDocument().notes,current.notes,'Pending DELETE cannot erase newer edits');assert.equal(f.d.getElementById('kbDrawio'),frame,'Pending DELETE preserves the newer editor session');assert.equal(f.writes.length,0);
    if(sameDocument&&!failed){assert.notEqual(f.api.getDocument().id,'A');assert.equal(f.api.getDocument().revision,0);assert(f.status().includes('current edits kept as a new draft'));}
    else{assert.equal(f.api.getDocument().id,current.id);assert.equal(f.status(),currentStatus,'Obsolete delete results cannot replace current status');}
    f.close();
  }
  f=await setup();const existing=await f.open('A');existing.finish();await settle();f.w.confirm=()=>true;
  const deleting=f.api.command('kb-delete-document');await settle();f.deletes[0].finish();await deleting;
  assert.notEqual(f.api.getDocument().id,'A');assert.equal(f.api.getDocument().title,'Untitled diagram');assert.equal(f.api.getDocument().revision,0);f.close();

  // Editing while leaving a draft waits for the normal discard decision.
  f=await setup({delaySave:true});edit(f,'ORIGINAL UNSAVED NOTES');const saveBeforeImport=deferred(),importControl=file(f,saveBeforeImport),pendingImport=importControl.onchange();
  saveBeforeImport.resolve(imported);await settle();assert.equal(f.saves.length,1);assert.equal(f.writes[0].notes,'ORIGINAL UNSAVED NOTES');
  edit(f,'NEWER NOTES DURING SAVE');let discardPrompts=0;f.w.confirm=()=>{discardPrompts++;return false};
  f.saves[0].finish();await pendingImport;assert.equal(discardPrompts,1);assert.equal(f.api.getDocument().notes,'NEWER NOTES DURING SAVE');assert.equal(f.api.getDocument().revision,1);assert.equal(f.api.getDocument().title,'Untitled diagram');f.close();

  console.log(
    "PASS: latest KB switches and edits survive pending reads/imports/deletes, deleted current edits remain a fresh draft, obsolete statuses/file resets are ignored, ordinary capture/save/import/delete remain usable and newer edits require explicit discard",
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
