const assert = require('node:assert/strict');
const fs = require('node:fs');
const crypto = require('node:crypto');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const root = path.resolve(__dirname, '..');

(async () => {
  const load = name => import(pathToFileURL(path.join(root, 'atlas', name)));
  const {applyMapAmenities} = await load('map-amenities.js');
  const {applyFurnitureCorrections} = await load('map-furniture.js');
  const {sourcePlanDetails} = await load('map-plan-details.js');
  const original = JSON.parse(fs.readFileSync(path.join(root, 'atlas/official-data.json')));
  const data = structuredClone(original);
  applyMapAmenities(data);
  applyFurnitureCorrections(data);
  const once = JSON.stringify(data);
  applyMapAmenities(data);
  applyFurnitureCorrections(data);
  assert.equal(JSON.stringify(data), once, 'Normal loading order is idempotent');
  assert.deepEqual(data.records, original.records, 'The plan review must not edit occupancy');
  let treads = 0;
  for (const floor of data.floors) {
    const detail = sourcePlanDetails[floor.level];
    assert(detail, `Floor ${floor.level} was reviewed`);
    const hash = crypto.createHash('sha256').update(fs.readFileSync(path.join(root, `atlas/official-floor-${floor.level}.pdf`))).digest('hex');
    assert.equal(detail.sourceSha256, hash, 'Corrections refer to the current original PDF');
    const before = original.floors.find(f => f.level === floor.level).geometry;
    const g = floor.geometry;
    assert.deepEqual(g.rooms, before.rooms, 'Do not infer new rooms from furniture');
    const walls = new Set(g.walls.map(JSON.stringify));
    const lines = new Set(g.planLinework.map(JSON.stringify));
    for (const tread of detail.stairTreads) {
      assert(!walls.has(JSON.stringify(tread)), 'Stair treads must not be raised as walls');
      assert(lines.has(JSON.stringify(tread)), 'Stair geometry stays visible in the plan underlay');
      treads++;
    }
    for (const label of detail.labels) {
      const radius = label.kind === 'lift' ? 125 : label.kind === 'wc' ? 90 : 55;
      assert(g.wayfinding.some(p => p.kind === label.kind && Math.hypot(p.anchor[0]-label.anchor[0],p.anchor[1]-label.anchor[1]) < radius), `${floor.level}: source location ${label.text} has a nearby marker`);
    }
    assert.equal(g.planLinework.length, before.planLinework.length - (floor.level === -1 ? 1 : floor.level === 2 ? 34 : 0), 'Only confirmed demolition and cupboard swing details leave the source underlay');
  }
  const fifth = data.floors.find(f => f.level === 5).geometry;
  const second = data.floors.find(f => f.level === 2).geometry;
  assert.equal(second.cupboards.length, 2, 'Two closed cupboards beside Credit Sales');
  assert.equal(second.printers.length, 1, 'One printer beside the cupboards');
  assert.equal(second.doorSwings.length, original.floors.find(f => f.level === 2).geometry.doorSwings.length - 2, 'Only the two confirmed cupboard swings leave the door layer');
  assert(second.doorSwings.some(c => c[0][0] === 620.359 && c[0][1] === 1058.28), 'Keep the real room doorway above the cupboards');
  assert(!second.walls.some(e => JSON.stringify(e) === JSON.stringify([[595.41,1093.81],[595.41,1134.02]])), 'Printer edges are not walls');
  assert(second.wayfinding.some(p => p.id === 'credit-sales-printer' && p.kind === 'print'), 'Printer appears with the amenity labels');
  const artwork = fs.readFileSync(path.join(root,'atlas/studio-floor-2.svg'),'utf8');
  assert(!artwork.includes('M9082 3206C8865.991') && !artwork.includes('M9082 3671C8865.991'), 'The styled 2D plan does not retain the cupboard swing arcs');
  assert(artwork.includes('M9082 2778V3242H9545V2778Z'), 'The lower cupboard is closed in the styled plan');
  assert(fifth.tables.some(p => p.some(([x,y]) => 375 < x && x < 417 && 680 < y && y < 750)), 'Keep the real MEET 01 furniture elsewhere on floor 5');
  const eighth = data.floors.find(f => f.level === 8).geometry;
  assert.equal(eighth.doorSwings.length, original.floors.find(f => f.level === 8).geometry.doorSwings.length - 36, 'Remove furniture curves and inner table surround, retaining passage doors');
  assert.equal(data.floors.find(f => f.level === 1).geometry.curvedTables.length, 3, 'All three large floor-1 tables are recovered');
  console.log(`PASS: all 10 original PDFs fingerprinted; ${treads} stair segments kept flat; source amenities and occupancy preserved`);
})().catch(error => { console.error(error); process.exitCode = 1; });
