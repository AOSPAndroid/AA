"""Build reviewed plan corrections from the ten original PDFs (build-time only).

No runtime PDF parsing or inferred room creation. Furniture outlines are selected
from source paths, and amenity labels are anchored to source technical labels.
Run after build_curved_tables.py. Requires PyMuPDF and Shapely for authoring.
"""
import hashlib
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import pymupdf
from shapely.geometry import MultiPoint, Polygon, LineString

from build_curved_tables import furniture_edges, recover
from plan_fixture_corrections import correct_floor2_cupboards

ROOT = Path(__file__).resolve().parents[1]


def source_labels(page, factor):
    labels = []
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines', []):
            for span in line.get('spans', []):
                text = span['text'].strip()
                match = re.fullmatch(r'(LIFT|STAIRS?|WC|PRINT|BREAK|KITCHEN)\s+(\d+)', text)
                if match:
                    x0,y0,x1,y1 = span['bbox']
                    labels.append(dict(text=text, kind={'LIFT':'lift','STAIR':'stairs','STAIRS':'stairs',
                        'WC':'wc','PRINT':'print','BREAK':'kitchen','KITCHEN':'kitchen'}[match[1]],
                        anchor=[round((x0+x1)*factor/2,2), round((y0+y1)*factor/2,2)]))
    return labels


def source_points(drawing, factor):
    result = []
    cv = lambda p: [round(p.x*factor,2), round(p.y*factor,2)]
    for item in drawing['items']:
        if item[0] in ('l','c'):
            result.extend(cv(p) for p in item[1:])
        elif item[0] == 're':
            result.extend(cv(p) for p in (item[1].tl,item[1].tr,item[1].br,item[1].bl))
        elif item[0] == 'qu':
            result.extend(cv(p) for p in item[1])
    return result


def hull(points):
    return [[round(x,2),round(y,2)] for x,y in list(MultiPoint(points).convex_hull.exterior.coords)[:-1]]


def kitchen_furniture(level, geometry, drawings, factor):
    result = dict(kitchenCounters=[], kitchenTables=[], kitchenSeats=[], kitchenSinks=[])
    if level not in range(2,8):
        return result
    def find(bounds):
        matches = [d for d in drawings if max(abs(a*factor-b) for a,b in zip(d['rect'],bounds)) < .2]
        if len(matches) != 1:
            raise ValueError(f'Floor {level}: reviewed kitchen path {bounds} changed')
        return source_points(matches[0],factor)
    if level == 2:
        # This source uses its own counter geometry and four stools, not the
        # larger island drawn on floors 3-6. No speculative sink is added.
        result['kitchenCounters'] = [hull(find(b)) for b in [
            [765.88,593.51,853.55,675.98], [830.59,649.95,894.4,709.65],
            [872.08,697.15,962.96,781.67]]]
    elif level in (3,4,5,6):
        # Exact cupboard/island/bar outlines from the black source paths.
        top = find([764.98,347.49,846.36,418.23]) + find([764.98,400.92,802.69,424.33])
        island = find([809.17,392.39,893.95,473.64])
        bar = []
        for d in drawings:
            bounds = [v*factor for v in d['rect']]
            if d['color'] == (0,0,0) and len(d['items']) == 4 and all(i[0]=='l' for i in d['items']):
                if bounds[0]>867 and bounds[1]>450 and bounds[2]<959 and bounds[3]<538:
                    bar.extend(source_points(d,factor))
        if len(bar) != 96:
            raise ValueError(f'Floor {level}: expected twelve bar panels')
        result['kitchenCounters'] = [hull(top),hull(island),hull(bar)]
    # Floor 7 has three different break spaces. Preserve those paths without
    # transplanting the earlier floors' island, sink or meeting table.
    def stool(points):
        xs,ys=zip(*points);cx=(min(xs)+max(xs))/2;cy=(min(ys)+max(ys))/2
        region = (780<cx<980 and 580<cy<785) if level==2 else (620<cx<1100 and 200<cy<630) if level==7 else (850<cx<960 and 440<cy<540)
        return region and 150 < Polygon(points).area < 500
    recovered = recover(geometry,furniture_edges(ROOT/f'atlas/studio-floor-{level}.svg'),accept=stool)
    result['kitchenSeats'] = recovered['tables']
    if len(result['kitchenSeats']) != (6 if level==7 else 4):
        raise ValueError(f'Floor {level}: source stool contours changed')
    return result


def stair_treads(geometry, labels, level):
    anchors=[label['anchor'] for label in labels if label['kind']=='stairs']
    # Clearly drawn but unlabelled lower cores on the two split-level PDFs.
    if level==1: anchors += [[140,920],[210,800],[800,940],[1480,775]]
    if level==2: anchors += [[392,92]]
    candidates=[];seen=set()
    for edge in geometry['walls']:
        a,b=sorted(edge);signature=json.dumps([a,b])
        if signature in seen:continue
        seen.add(signature);dx=b[0]-a[0];dy=b[1]-a[1];length=math.hypot(dx,dy)
        if not 10<length<110:continue
        angle=math.atan2(dy,dx)%math.pi
        if angle > math.pi-.008: angle=0
        if abs(angle-math.pi/2)<.008: angle=math.pi/2
        u=(math.cos(angle),math.sin(angle));m=((a[0]+b[0])/2,(a[1]+b[1])/2)
        if min((math.dist(m,p) for p in anchors),default=999)>110:continue
        candidates.append((angle,length,m,edge,u))
    chosen={}
    for ang,length,mid,edge,u in candidates:
        matches=[]
        for a,le,mi,ed,_ in candidates:
            if abs(ang-a)<.008 and abs(length-le)<.6 and abs((mi[0]-mid[0])*u[0]+(mi[1]-mid[1])*u[1])<.6:
                matches.append(((mi[0]-mid[0])*-u[1]+(mi[1]-mid[1])*u[0],ed))
        matches.sort();chunks=[[]]
        for item in matches:
            if chunks[-1] and item[0]-chunks[-1][-1][0]>10:chunks.append([])
            if not chunks[-1] or item[0]-chunks[-1][-1][0]>1:chunks[-1].append(item)
        for chunk in chunks:
            if len(chunk)>=6:
                for _,ed in chunk:chosen[json.dumps(sorted(ed))]=ed
    # Return the exact existing segments, including duplicates, for stable removal.
    return [e for e in geometry['walls'] if json.dumps(sorted(e)) in chosen]


def flat_furniture_details(level, geometry, drawings, factor):
    """Keep floor-8 inner table surrounds flat; preserve the actual room walls."""
    if level != 8:
        return [], []
    bounds = [[47.65,773.34,236.59,842.09], [281.86,769.36,384.93,838.05],
        [310.98,675.34,396.86,738.32], [401.6,492.31,616.32,560.99],
        [905.37,679.7,997.01,745.5], [466.5,767.0,546.69,847.22],
        [1214.68,588.92,1356.4,730.62]]
    lines, curves = [], []
    for box in bounds:
        matches = [d for d in drawings if max(abs(a*factor-b) for a,b in zip(d['rect'],box)) < .2]
        if len(matches) != 1:
            raise ValueError('Floor 8: reviewed inner table surround changed')
        for item in matches[0]['items']:
            if item[0] == 're':
                r = item[1]; points = [r.tl,r.tr,r.br,r.bl,r.tl]
                lines.extend([[[round(p.x*factor,2),round(p.y*factor,2)] for p in (a,b)] for a,b in zip(points,points[1:])])
            elif item[0] == 'c':
                curve = [[round(p.x*factor,2),round(p.y*factor,2)] for p in item[1:]]
                curves.append(curve)
                sampled = [[sum(w*p[j] for w,p in zip(((1-t)**3,3*(1-t)**2*t,3*(1-t)*t*t,t**3),curve)) for j in (0,1)] for t in [i/16 for i in range(17)]]
                lines.extend([[a,b] for a,b in zip(sampled,sampled[1:])])
    same = lambda a,b: max(math.dist(p,q) for p,q in zip(a,b)) < .03
    excluded_walls = [e for e in geometry['walls'] if any(same(e,l) or same(e,l[::-1]) for l in lines)]
    excluded_doors = [c for c in geometry['doorSwings'] if any(same(c,s) or same(c,s[::-1]) for s in curves)]
    if len(excluded_walls) != 84 or len(excluded_doors) != 4:
        raise ValueError('Floor 8: table surround geometry changed')
    return excluded_walls, excluded_doors


def credit_sales_fixtures(level, geometry, drawings, factor):
    """Floor 2: the owner identified PHO 04/05 as cupboards and the adjacent unit as a printer."""
    detail = dict(cupboards=[], printers=[], confirmedAmenities=[], excludedPlanSegments=[])
    if level != 2:
        return detail, [], []
    # Match the unchanged source contours before applying the owner's meaning.
    bounds = [[557.32,1064.05,612.15,1093.81], [557.32,1034.23,612.15,1064.05],
        [595.41,1093.81,611.64,1134.02]]
    for box in bounds:
        if sum(max(abs(a*factor-b) for a,b in zip(d['rect'],box)) < .02 for d in drawings) != 1:
            raise ValueError('Floor 2 Credit Sales fixture footprint changed')
    detail['cupboards'] = [
        [[582.46,1034.23],[612.15,1034.23],[612.15,1064.05],[582.46,1064.05]],
        [[582.46,1064.05],[612.15,1064.05],[612.15,1093.81],[582.46,1093.81]]]
    printer = [[595.41,1093.81],[611.64,1093.81],[611.64,1134.02],[595.41,1134.02]]
    detail['printers'] = [printer]
    detail['confirmedAmenities'] = [dict(id='credit-sales-printer',kind='print',name='Printer',
        anchor=[603.53,1113.92],points=printer)]
    doors = [c for c in geometry['doorSwings'] if all(557<p[0]<583 and 1036<p[1]<1092 for p in c)]
    # Remove only the two open leaves and their sampled swing arcs from the
    # underlay. The closed cupboard front and actual room doorway remain.
    detail['excludedPlanSegments'] = [e for e in geometry['planLinework']
        if all(556<p[0]<583 and 1035<p[1]<1095 for p in e) and any(p[0]<582.4 for p in e)]
    surface = Polygon(printer).buffer(.02)
    walls = [e for e in geometry['walls'] if surface.covers(LineString(e))]
    if len(doors)!=2 or len(walls)!=4 or len(detail['excludedPlanSegments'])!=34:
        raise ValueError('Floor 2 cupboard/printer details changed')
    return detail, walls, doors


def build():
    data=json.loads((ROOT/'atlas/official-data.json').read_text(encoding='utf8'))
    corrections={}
    for floor in data['floors']:
        level=floor['level'];geometry=floor['geometry'];path=ROOT/f'atlas/official-floor-{level}.pdf'
        with pymupdf.open(path) as doc:
            page=doc[0];factor=1800/page.rect.width;drawings=page.get_drawings()
            labels=source_labels(page,factor)
            fixtures=kitchen_furniture(level,geometry,drawings,factor)
            surfaces=[Polygon(p).buffer(.12) for p in fixtures['kitchenCounters']]
            fixture_walls=[e for e in geometry['walls'] if any(p.covers(LineString(e)) for p in surfaces)]
            # A cupboard-door swing inside the exact cupboard outline is a
            # furniture detail, not a full-height passage door.
            fixture_doors=[c for c in geometry['doorSwings'] if any(p.buffer(2).covers(LineString(c)) for p in surfaces)]
            flat_walls, flat_doors = flat_furniture_details(level,geometry,drawings,factor)
            storage, storage_walls, storage_doors = credit_sales_fixtures(level,geometry,drawings,factor)
            corrections[level]=dict(sourceSha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                labels=labels, **fixtures, **storage, excludedWalls=fixture_walls+flat_walls+storage_walls,
                excludedDoors=fixture_doors+flat_doors+storage_doors, stairTreads=stair_treads(geometry,labels,level))
            print(f'Floor {level}: {len(labels)} source labels, {len(fixture_walls)} cupboard edges, '
                  f'{len(fixture_doors)} cupboard swings, {len(corrections[level]["stairTreads"])} stair tread segments')
    template=(ROOT/'tools/plan-details-runtime.js').read_text(encoding='utf8')
    (ROOT/'atlas/map-plan-details.js').write_text('// Generated by tools/build_plan_details.py from reviewed original PDF paths.\n'
        +'export const sourcePlanDetails = '+json.dumps(corrections,separators=(',',':'))+';\n'+template,encoding='utf8')
    artwork = ROOT/'atlas/studio-floor-2.svg'
    tree = ET.parse(artwork)
    if correct_floor2_cupboards(tree.getroot()):
        ET.register_namespace('', 'http://www.w3.org/2000/svg')
        artwork.write_text(ET.tostring(tree.getroot(),encoding='unicode'),encoding='utf8')


if __name__=='__main__':build()
