const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {pathToFileURL} = require('node:url');
const root = path.resolve(__dirname, '..');

(async () => {
  const {applyFurnitureCorrections} = await import(pathToFileURL(path.join(root, 'atlas/map-furniture.js')));
  const data = JSON.parse(fs.readFileSync(path.join(root, 'atlas/official-data.json'), 'utf8'));
  const before = new Map(data.floors.map(f => [f.level, f.geometry.doorSwings.length]));
  const beforeWalls = new Map(data.floors.map(f => [f.level, f.geometry.walls.length]));
  const beforeLines = new Map(data.floors.map(f => [f.level, f.geometry.planLinework.length]));
  const source = fs.readFileSync(path.join(root, 'atlas/official-app.js'), 'utf8');
  const triangulate = vm.runInNewContext(source.slice(source.indexOf('function triangulate('), source.indexOf('function polygonMesh(')) + '\ntriangulate');
  applyFurnitureCorrections(data);
  const once = JSON.stringify(data);
  applyFurnitureCorrections(data);
  assert.equal(JSON.stringify(data), once, 'Repeated loading must not duplicate tables');
  const exclusions = {'-1': 36, 0: 0, 1: 0, 2: 0, 3: 1, 4: 1, 5: 0, 6: 1, 7: 2, 8: 32};
  let count = 0;
  for (const floor of data.floors) {
    if (!(floor.level in exclusions)) continue;
    assert.equal(floor.geometry.doorSwings.length, before.get(floor.level) - exclusions[floor.level], 'Keep real door swings');
    assert.equal(floor.geometry.walls.length, beforeWalls.get(floor.level) - (floor.level === -1 ? 22 : 0), 'Only restaurant furniture and the confirmed demolished partition lose raised walls');
    assert.equal(floor.geometry.planLinework.length, beforeLines.get(floor.level) - (floor.level === -1 ? 1 : 0), 'Only the demolished partition is removed from the source underlay');
    for (const points of floor.geometry.curvedTables) {
      const triangles = triangulate(points);
      assert.equal(triangles.length, points.length - 2, `Floor ${floor.level} table must render in 3D`);
      count++;
    }
  }
  const tables = data.floors.find(f => f.level === 3).geometry.curvedTables;
  const containsBounds = (x, y) => tables.some(p => Math.min(...p.map(v => v[0])) < x && Math.max(...p.map(v => v[0])) > x && Math.min(...p.map(v => v[1])) < y && Math.max(...p.map(v => v[1])) > y);
  assert(containsBounds(780, 315), 'Oval private-office table recovered');
  assert(containsBounds(835, 905), 'Rounded private-office desk recovered');
  const restaurant = data.floors.find(f => f.level === -1).geometry;
  assert.equal(restaurant.curvedTables.filter(p => p.length === 32).length, 9, 'Nine round dining tables');
  assert.equal(restaurant.curvedTables.filter(p => p.length === 4).length, 3, 'Two communal tables plus the highlighted dining table');
  assert(restaurant.curvedTables.some(points => points.length === 4 &&
    Math.abs(points.reduce((sum,p) => sum+p[0],0)/4-884) < .1 &&
    Math.abs(points.reduce((sum,p) => sum+p[1],0)/4-552) < .1), 'New table occupies the highlighted restaurant location');
  assert.equal(restaurant.chairSeats.length, 23, 'Dining chairs use seat height rather than table height');
  assert.equal(restaurant.tables.length, 0, 'Do not also draw the dining chairs as tables');
  assert.equal(restaurant.counters.length, 2, 'Salad island and serving counter recovered');
  for (const points of restaurant.counters) {
    assert.equal(triangulate(points).length, points.length - 2, 'Counter surfaces must render completely in 3D');
  }
  const island = restaurant.counters[0];
  const cross = (a, b, p) => (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0]);
  const covered = point => triangulate(island).some(ids => {
    const [a, b, c] = ids.map(i => island[i]);
    const sides = [cross(a,b,point), cross(b,c,point), cross(c,a,point)];
    return sides.every(n => n >= 0) || sides.every(n => n <= 0);
  });
  assert(covered([795,665]), 'Countertop surface remains filled');
  assert(!covered([800,695]), 'Keep the opening between the two salad-bar arms');
  const walls = new Set(restaurant.walls.map(segment => JSON.stringify(segment)));
  const oldPartition = JSON.stringify([[728.74,597.23],[885.81,742.3]]);
  assert(!walls.has(oldPartition), 'Open the passage between the salad bar and seating');
  assert(!restaurant.planLinework.some(segment => JSON.stringify(segment) === oldPartition), 'The demolished partition must not remain as a floor line in 3D');
  assert(walls.has(JSON.stringify([[710.4,616.72],[728.74,597.23]])), 'Keep the adjoining kitchen wall at the end of the demolished partition');
  assert(!walls.has(JSON.stringify([[749.52,679.7],[803.2,729.28]])), 'Salad island sides are not room walls');
  assert(!walls.has(JSON.stringify([[712.33,740.69],[728.42,740.69]])), 'Serving units are not room walls');
  assert(walls.has(JSON.stringify([[710.4,653.92],[710.4,782.25]])), 'Keep the kitchen partition beside the salad bar');
  assert(walls.has(JSON.stringify([[762.35,782.38],[848.54,782.51]])), 'Keep the room boundary below the counters');
  const ground = data.floors.find(f => f.level === 0).geometry;
  assert.equal(ground.curvedTables.length, 28, 'Keep one surface for each cafe and lobby round furniture symbol');
  const centres = ground.curvedTables.map(points => [0,1].map(i => (Math.min(...points.map(p => p[i]))+Math.max(...points.map(p => p[i])))/2));
  assert(centres.every((p, i) => centres.slice(i+1).every(q => Math.hypot(p[0]-q[0],p[1]-q[1]) > .2)), 'Concentric source circles must not duplicate furniture');
  assert.equal(ground.chairSeats.length, 6, 'Two three-section sofas use seat height');
  assert.equal(ground.tables.length, 25, 'Other ground-floor furniture stays intact');
  assert.equal(ground.counters.length, 1, 'Reception counter recovered');
  assert.equal(triangulate(ground.counters[0]).length, ground.counters[0].length-2, 'L-shaped reception counter renders in 3D');
  assert(data.floors.filter(f => ![-1,0].includes(f.level)).every(f => !f.geometry.counters), 'Counter corrections are limited to the confirmed lower floors');

  const {applyMapAmenities} = await import(pathToFileURL(path.join(root, 'atlas/map-amenities.js')));
  applyMapAmenities(data);
  const amenitiesOnce = JSON.stringify(data);
  applyMapAmenities(data);
  assert.equal(JSON.stringify(data), amenitiesOnce, 'Reloading must not duplicate amenity labels');
  for (const level of [2, 3, 4, 5, 6, 7]) {
    const geometry = data.floors.find(f => f.level === level).geometry;
    assert.equal(geometry.kitchenCounters.length, level === 7 ? 0 : 3, `Floor ${level} uses its reviewed source counter outlines`);
    assert.equal(geometry.kitchenSinks.length, 0, `Floor ${level} does not guess a sink location`);
    assert.equal(geometry.kitchenTables.length, 0,
      `Floor ${level} does not add an invented meeting table beside the kitchen`);
    assert.equal(geometry.kitchenSeats.length, level === 7 ? 6 : 4,
      `Floor ${level} follows its source plan for kitchen seating`);
    for (const points of [...geometry.kitchenCounters, ...geometry.kitchenSinks,
      ...geometry.kitchenTables, ...geometry.kitchenSeats])
      assert.equal(triangulate(points).length, points.length - 2,
        `Floor ${level} kitchen fixture renders in 3D`);
  }
  const places = new Map(ground.wayfinding.map(p => [p.id,p]));
  for (const f of data.floors)
    for (const points of [...f.geometry.cupboards, ...f.geometry.printers])
      assert.equal(triangulate(points).length, points.length-2, 'Cupboard and printer surfaces render completely in 3D');
  for (const id of ['coffee','coffee-seating','lobby-seating','reception','build-room','main-entrance','secondary-entrance']) {
    assert(places.has(id), `Annotated ground-floor location ${id} is labelled`);
  }
  assert.equal(places.get('build-room').name, 'Build room');
  assert.equal(ground.wayfinding.filter(p => p.id === 'lift-main').length, 1, 'One main elevator-bank marker');
  assert(Math.max(...places.get('lift-main').points.map(p => p[0]))-Math.min(...places.get('lift-main').points.map(p => p[0])) > 170, 'Outline the entire bank, not one lift');
  for (const place of places.values()) assert.equal(triangulate(place.points).length, place.points.length-2, 'Ground-floor markers render in 3D');
  console.log(`PASS: ${count} curved tables triangulate; both reference shapes recovered; real doors retained`);
})().catch(error => { console.error(error); process.exitCode = 1; });
