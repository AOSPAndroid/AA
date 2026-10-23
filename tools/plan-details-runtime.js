
const without = (items, excluded) => excluded.size ? (items || []).filter(item => !excluded.has(JSON.stringify(item))) : items || [];

export function applySourcePlanDetails(data) {
  for (const floor of data.floors) {
    const detail = sourcePlanDetails[floor.level];
    if (!detail) continue;
    const g = floor.geometry;
    for (const key of ["kitchenCounters", "kitchenTables", "kitchenSeats", "kitchenSinks", "stairTreads", "cupboards", "printers"])
      g[key] = detail[key];
    const walls = new Set([...detail.excludedWalls, ...detail.stairTreads].map(e => JSON.stringify(e)));
    const doors = new Set(detail.excludedDoors.map(e => JSON.stringify(e)));
    g.walls = without(g.walls, walls);
    g.doorSwings = without(g.doorSwings, doors);
    const removedPlan = new Set(detail.excludedPlanSegments.map(e => JSON.stringify(e)));
    g.planLinework = without(g.planLinework, removedPlan);
    const confirmedIds = new Set(detail.confirmedAmenities.map(p => p.id));
    const places = (g.wayfinding || []).filter(p => !p.id?.startsWith("source-") && !confirmedIds.has(p.id));
    for (const place of detail.confirmedAmenities)
      if (!places.some(p => p.id === place.id)) places.push(place);
    // Keep owner-confirmed names, use the separate floor-7 break-area position.
    if (floor.level === 7) {
      const kitchen = places.find(p => p.id === "kitchen-coffee");
      const label = detail.labels.find(p => p.text === "BREAK 01");
      if (kitchen && label) {
        kitchen.anchor = [...label.anchor];
        kitchen.points = [[-7,-7],[7,-7],[7,7],[-7,7]].map(([x,y]) => [x+label.anchor[0],y+label.anchor[1]]);
      }
    }
    for (const label of detail.labels) {
      const radius = label.kind === "lift" ? 125 : label.kind === "wc" ? 90 : 55;
      if (places.some(p => p.kind === label.kind && p.anchor && Math.hypot(p.anchor[0]-label.anchor[0],p.anchor[1]-label.anchor[1]) < radius)) continue;
      // BREAK is an area designation; it does not prove a kitchen or coffee point.
      const name = label.kind === "lift" ? "Elevator" : label.kind === "stairs" ? "Stairs" : label.kind === "wc" ? "Toilets" : label.kind === "print" ? "Print & stationery" : label.text.startsWith("BREAK") ? "Break area" : "Kitchen";
      const [x,y] = label.anchor;
      places.push({ id: "source-"+label.text.toLowerCase().replace(/\s+/g,"-"), name,
        kind: label.kind, anchor: [...label.anchor], sourceLabel: label.text,
        points: [[x-7,y-7],[x+7,y-7],[x+7,y+7],[x-7,y+7]] });
    }
    g.wayfinding = places;
  }
}
