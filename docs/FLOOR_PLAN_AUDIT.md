# Floor-plan review — 12 September 2026

All ten floors, B1 and 00–08, were compared visually with their original PDF
plans. The review covered floor outlines, partitions, door symbols, furniture,
stairs, lift banks and amenity positions. Corrections are shared by Admin, Demo
and the private preview.

| Floor | Review and resulting corrections |
| --- | --- |
| B1 | Restaurant tables, communal seating, serving counter and salad island checked. Preserve the owner-confirmed demolished partition and added dining table even though they differ from the original drawing. Add missing source-labelled toilets, stairs and lifts. Keep stair treads flat. |
| 00 | Check the original plan alongside the owner's annotated reception, entrances, build room and coffee/seating locations. Preserve those annotations. Add missing source-labelled amenities and keep stair treads flat. |
| 01 | Restore the three large conference-table surfaces omitted from the furniture recovery pass. Check this floor's separate cores; do not copy the standard office-floor arrangement. Add source-labelled amenities and keep stair treads flat. |
| 02 | Use this floor's own three kitchen counter footprints and four stool contours. Remove the previously guessed sink and extra meeting table. Keep the lift-bank outline and source stair geometry. |
| 03 | Trace cupboard, island and bar footprints from this floor's original paths, with four stools. Remove the guessed sink and extra table. Keep cupboard panel edges and stair treads from becoming full-height walls. Preserve rounded private-office furniture. |
| 04 | Independently check the source plan; apply its traced cupboard, island, bar and four stools. Preserve real partitions and passage doors while flattening furniture edges and stair treads. |
| 05 | Remove the invented kitchen meeting-table arrangement. Preserve the genuine MEET 01 furniture elsewhere on this floor, which is present in the original PDF. Use the source counter footprints and four stools. |
| 06 | Independently check this floor's kitchen, private-office furniture and layout. Use its source counter footprints and four stools; flatten cupboard edges and stair treads. |
| 07 | Preserve its different three-break-area layout. Move the kitchen/coffee marker to BREAK 01 and label the other break areas from the source. Remove the transplanted island, sink and extra table. Retain the six source stool contours; other fine fixture detail remains in the plan underlay. |
| 08 | Recover 30 curved furniture surfaces and remove 32 furniture arcs from the door layer. Keep inner table surrounds and the large circular break-area surround flat, removing four more false door arcs. Resolve the intersecting MEET 06 furniture contours using the tapered source outline. Preserve the enclosing room partitions. |

## Verification

- `tools/audit_plan_sources.py` independently matches all 25,758 remaining wall
  segments and 648 door curves to the original PDFs within 0.04 units on the
  1,800-unit map canvas. Large curved walls use the extractor's 16-segment cubic
  approximation. There are no unmatched coordinates. This verifies coordinate
  provenance, not the physical meaning of every CAD symbol.
- `tests/plan_details.cjs` checks fingerprints of all ten original PDFs, source
  amenity coverage, repeated loading, preservation of occupancy data and source
  linework, and that 771 stair-tread segments remain flat rather than raised walls.
- `tests/map_furniture.cjs` checks all 127 recovered curved furniture surfaces
  and kitchen surfaces triangulate completely for 3D, and protects the confirmed
  B1/00 changes and actual passage doors.
- Owner follow-up: the two units beside the floor-2 Credit Sales desks are
  cupboards, with a printer alongside. Their source footprints are retained,
  but the two cupboard swings and open leaves are removed from both 2D and 3D.
  The printer's four edges are furniture, not walls. The actual room doorway
  above the units is preserved. A Printer amenity label identifies
  the spot. The original PDFs remain unchanged.
- Map movement, label placement, render caching and read-only viewer regressions
  are checked separately. No PDF parsing or extra scans run in the browser.

## What remains an approximation

The PDFs establish the drawn layout, not today's physical condition. Existing
owner-confirmed changes take precedence where documented. Desk occupants and
machine assignments were not reverified by this architectural review.

Wall heights, furniture heights, slab shape and some small fixtures remain a
visual representation, not surveyed BIM. Stairs retain their plan treads rather
than individual measured 3D steps. The precise sink positions are not clear
enough in the available drawings to place confidently; the guessed basins were
removed. Floor 8 MEET 06 contains overlapping furniture outlines in the source.

For a management demonstration, describe Atlas as a plan-based office and IT
navigation tool. A facilities walk-through is still needed before claiming that
every detail matches the current building.

## Rebuilding the reviewed details

Authoring requires PyMuPDF and Shapely; the independent coordinate audit also
uses NumPy. These are build-time tools, not new Atlas runtime dependencies.

```text
python tools/build_curved_tables.py
python tools/build_plan_details.py
python tools/audit_plan_sources.py
node tests/map_furniture.cjs
node tests/plan_details.cjs
```

The generators fail when selected source contours no longer match. Review a
changed drawing before updating these selections or accepting new fingerprints.
