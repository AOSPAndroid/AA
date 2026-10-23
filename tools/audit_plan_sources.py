"""Compare effective map wall/door coordinates with each original PDF.

Build-time audit, not a runtime dependency. Requires PyMuPDF, NumPy, Shapely.
Prints geometry counts only; no directory/occupant data is exported.
Coordinate provenance is not proof of the physical meaning of a CAD symbol.
"""
import json
import subprocess
from pathlib import Path

import numpy as np
import pymupdf
from shapely import STRtree
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parents[1]


def audit():
    script = """const fs=require('fs');const {pathToFileURL}=require('url');
    (async()=>{const d=JSON.parse(fs.readFileSync('atlas/official-data.json'));
    for(const [file,fn] of [['map-amenities.js','applyMapAmenities'],['map-furniture.js','applyFurnitureCorrections']])
      (await import(pathToFileURL(process.cwd()+'/atlas/'+file)))[fn](d);
    console.log(JSON.stringify(d.floors.map(f=>({level:f.level,geometry:{walls:f.geometry.walls,doorSwings:f.geometry.doorSwings}}))));})();"""
    floors = json.loads(subprocess.check_output(['node','--no-warnings','-e',script],cwd=ROOT,encoding='utf8'))
    failed = False
    for floor in floors:
        level = floor['level']; lines = []; curves = []
        with pymupdf.open(ROOT/f'atlas/official-floor-{level}.pdf') as doc:
            page = doc[0]; factor = 1800/page.rect.width
            xy = lambda p: [p.x*factor,p.y*factor]
            for drawing in page.get_drawings():
                for item in drawing['items']:
                    if item[0] == 'l': lines.append(LineString([xy(item[1]),xy(item[2])]))
                    elif item[0] == 'c':
                        curve = [xy(p) for p in item[1:]]
                        curves.append(curve)
                        # Large source curves are represented by sixteen wall
                        # segments per cubic in the original map extractor.
                        sampled = [[sum(w*p[j] for w,p in zip(((1-t)**3,3*(1-t)**2*t,3*(1-t)*t*t,t**3),curve)) for j in (0,1)] for t in [i/16 for i in range(17)]]
                        lines.extend(LineString([a,b]) for a,b in zip(sampled,sampled[1:]))
                    elif item[0] in ('re','qu'):
                        r = item[1]
                        points = [r.tl,r.tr,r.br,r.bl,r.tl] if item[0]=='re' else [r.ul,r.ur,r.lr,r.ll,r.ul]
                        lines.extend(LineString([xy(a),xy(b)]) for a,b in zip(points,points[1:]))
        tree = STRtree(lines); source_curves = np.array(curves)
        missing_walls = []
        for edge in floor['geometry']['walls']:
            line = LineString(edge)
            # Query all nearby lines: duplicate and overlapping CAD paths can
            # have identical distances but different segment endpoints.
            if not any(line.hausdorff_distance(lines[i]) < .04 for i in tree.query(line.buffer(.04))):
                missing_walls.append(edge)
        missing_doors = []
        for curve in floor['geometry']['doorSwings']:
            p = np.array(curve)
            distance = min(np.max(np.abs(source_curves-p),axis=(1,2)).min(),
                np.max(np.abs(source_curves-p[::-1]),axis=(1,2)).min())
            if distance >= .04: missing_doors.append(curve)
        row = dict(floor=level,walls=len(floor['geometry']['walls']),doors=len(floor['geometry']['doorSwings']),
            unmatched_walls=len(missing_walls),unmatched_doors=len(missing_doors))
        print(json.dumps(row))
        failed |= bool(missing_walls or missing_doors)
    if failed: raise SystemExit('Some coordinates need source review')


if __name__ == '__main__': audit()
