"""Recover rounded furniture from the blue furniture paths in the styled plans.

The old door extractor also collected cubic segments belonging to tables. Keep
the original curves for an exact exclusion and sample the closed furniture
outline once at build time, rather than doing SVG analysis in the browser.
"""
from collections import defaultdict, deque
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
TOKEN = re.compile(r'[MLCHVZ]|-?(?:\d*\.)?\d+')
B1_REMOVED_PARTITION = [[728.74, 597.23], [885.81, 742.3]]
B1_ADDED_DINING_TABLE = [[876.87,533.19],[903.33,557.59],[891.13,570.81],[864.67,546.41]]


def correct_b1_plan(root):
    """Remove only the demolished diagonal; retain the adjoining room edges."""
    old = 'M13812 8259 11363 10521 11077 10217 10995 10132 10994 9641 11077 9637V7636L11777 7635V7715H11887V7634L13231 7632V7714H13340V7632L13774 7631 13776 8220Z'
    # Reopen the path at the far end and keep the old closing segment explicitly.
    # Leaving Z after moving the start would draw a new diagonal across the room.
    new = old.replace('M13812 8259 11363 10521', 'M11363 10521').removesuffix('Z') + 'L13812 8259'
    for element in root.iter():
        if element.get('d') == new:
            return False
        if element.get('d') == old:
            element.set('d', new)
            return True
    raise ValueError('B1 partition source path changed; review the demolition correction')


def furniture_edges(path, colors=('#7396aa',)):
    root = ET.parse(path).getroot()
    edges = []
    for element in root.iter():
        if element.get('stroke') not in colors:
            continue
        transform = list(map(float, re.findall(r'-?(?:\d*\.)?\d+', element.get('transform', ''))))
        if len(transform) != 6:
            raise ValueError('Unexpected furniture transform')
        a, b, c, d, e, f = transform
        def convert(p):
            x, y = p
            return [round((a*x+c*y+e)*1800/842, 2), round((b*x+d*y+f)*1800/842, 2)]
        tokens = TOKEN.findall(element.get('d', ''))
        i, command, position, start = 0, None, None, None
        while i < len(tokens):
            if tokens[i].isalpha():
                command = tokens[i]
                i += 1
            if command == 'Z':
                if position != start:
                    edges.append(([convert(position), convert(start)], None))
                position = start
                continue
            count = {'M': 2, 'L': 2, 'C': 6, 'H': 1, 'V': 1}[command]
            values = list(map(float, tokens[i:i+count]))
            i += count
            if command == 'M':
                start = position = values
                command = 'L'
                continue
            end = values[-2:] if command in ('L', 'C') else [values[0], position[1]] if command == 'H' else [position[0], values[0]]
            curve = None
            if command == 'C':
                curve = [convert(p) for p in [position, values[:2], values[2:4], end]]
                points = [[round(sum(weight*p[k] for weight, p in zip(((1-t)**3, 3*(1-t)**2*t, 3*(1-t)*t*t, t**3), curve)), 2) for k in (0, 1)] for t in [j/8 for j in range(9)]]
            else:
                points = [convert(position), convert(end)]
            edges.append((points, curve))
            position = end
    return edges


def recover(geometry, edges, dining=False, accept=None):
    nodes, adjacency, bins = [], defaultdict(list), defaultdict(list)
    def node(point):
        key = tuple(math.floor(v/.2) for v in point)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for index in bins[key[0]+dx, key[1]+dy]:
                    if math.dist(nodes[index], point) <= .15:
                        return index
        index = len(nodes)
        nodes.append(point)
        bins[key].append(index)
        return index
    endpoints = []
    for index, (points, _) in enumerate(edges):
        a, b = node(points[0]), node(points[-1])
        endpoints.append((a, b))
        adjacency[a].append((b, index))
        adjacency[b].append((a, index))
    removed, tables, seen = [], [], set()
    table_edges = set()
    for match, (_, curve) in enumerate(edges):
        if curve is None:
            continue
        a, b = endpoints[match]
        queue, previous = deque([b]), {b: None}
        while queue and a not in previous:
            current = queue.popleft()
            for nxt, index in adjacency[current]:
                if index == match or nxt in previous:
                    continue
                previous[nxt] = (current, index)
                queue.append(nxt)
        if a not in previous:
            continue
        route, current = [], a
        while current != b:
            parent, index = previous[current]
            route.append((parent, current, index))
            current = parent
        route.reverse()
        cycle = frozenset([match]+[index for _, _, index in route])
        points = list(edges[match][0])
        for start, end, index in route:
            segment = edges[index][0]
            if endpoints[index][0] != start:
                segment = list(reversed(segment))
            points.extend(segment[1:])
        if math.dist(points[0], points[-1]) < .2:
            points.pop()
        area = abs(sum(p[0]*q[1]-q[0]*p[1] for p, q in zip(points, points[1:]+points[:1])))/2
        width = max(p[0] for p in points)-min(p[0] for p in points)
        height = max(p[1] for p in points)-min(p[1] for p in points)
        if accept is not None:
            if not accept(points):
                continue
        elif dining:
            cx = (max(p[0] for p in points)+min(p[0] for p in points))/2
            cy = (max(p[1] for p in points)+min(p[1] for p in points))/2
            # Only the owner-confirmed round restaurant tables, not small symbols elsewhere.
            if not (680 < cx < 890 and 450 < cy < 660 and 280 < area < 500 and 18 < width < 26 and 18 < height < 26):
                continue
        elif area < 400 or min(width, height) < 18 or max(width, height) < 35 or max(width, height) > 240:
            continue
        table_edges.update(cycle)
        if cycle not in seen:
            tables.append(points)
            seen.add(cycle)
    for door in geometry.get('doorSwings', []):
        if any(edges[i][1] and max(math.dist(a, b) for a, b in zip(door, edges[i][1])) < .12 for i in table_edges):
            removed.append(door)
    return {'excludedDoorCurves': removed, 'tables': tables}


if __name__ == '__main__':
    plan_path = ROOT/'atlas/studio-floor--1.svg'
    plan = ET.parse(plan_path)
    if correct_b1_plan(plan.getroot()):
        ET.register_namespace('', 'http://www.w3.org/2000/svg')
        plan_path.write_text(ET.tostring(plan.getroot(), encoding='unicode'), encoding='utf8')
    data = json.loads((ROOT/'atlas/official-data.json').read_text(encoding='utf8'))
    corrections = {}
    for floor in data['floors']:
        level = floor['level']
        def ground_floor_round_furniture(points):
            xs, ys = zip(*points)
            cx, cy = (min(xs)+max(xs))/2, (min(ys)+max(ys))/2
            width, height = max(xs)-min(xs), max(ys)-min(ys)
            # Only the cafe and reception seating confirmed on the annotated plan.
            in_cafe = 660 < cx < 830 and 700 < cy < 975
            in_lobby = 1060 < cx < 1210 and 765 < cy < 875
            return (in_cafe or in_lobby) and 8 < width < 18 and abs(width-height) < .2
        def other_floor_furniture(points):
            xs, ys = zip(*points)
            area = abs(sum(a[0]*b[1]-b[0]*a[1]
                for a,b in zip(points, points[1:]+points[:1])))/2
            # These floors were omitted from the original correction pass.
            # Include small round furniture and the large conference table;
            # the path must still be a closed, blue furniture contour.
            return area > 100 and min(max(xs)-min(xs), max(ys)-min(ys)) > 10 and max(max(xs)-min(xs), max(ys)-min(ys)) < 400
        corrections[level] = recover(
            floor['geometry'], furniture_edges(ROOT/f'atlas/studio-floor-{level}.svg'),
            dining=level == -1, accept=ground_floor_round_furniture if level == 0 else other_floor_furniture if level in (1,8) else None)
        item = corrections[level]
        if level == 8:
            # MEET 06 contains overlapping rounded and tapered blue outlines.
            # Follow the tapered contour's actual source edges; the graph's
            # shortest route otherwise switches outlines at their crossings.
            for i, points in enumerate(item['tables']):
                if points[0] == [412.44,543.74]:
                    if len(points) != 72 or points[38] != [415.45,505.71] or points[54] != [412.44,508.53]:
                        raise ValueError('Floor 8 MEET 06 contour changed; review the source')
                    item['tables'][i] = points[:28] + points[38:55]
        if level == 0:
            # The cafe symbols have concentric inner/outer paths. Keep one
            # surface per physical circle, using the outer outline.
            circles = []
            for points in sorted(item['tables'], key=lambda p: max(x for x,y in p)-min(x for x,y in p), reverse=True):
                center = lambda p: [(min(v[i] for v in p)+max(v[i] for v in p))/2 for i in (0, 1)]
                if not any(math.dist(center(points), center(other)) < .2 for other in circles):
                    circles.append(points)
            item['tables'] = circles
            # Follow the complete L-shaped reception desk outline from the source.
            item['counters'] = [[
                [1098.53,1029.04],[1055.89,982.92],[1068.9,971.0],
                [1100.65,1005.5],[1106.42,1000.11],[1117.2,1011.78],
            ]]
            # The two three-section sofas beside the coffee seating are seats.
            item['chairSeats'] = [points for points in floor['geometry']['tables']
                if 830 < sum(p[0] for p in points)/len(points) < 900
                and 760 < sum(p[1] for p in points)/len(points) < 830]
        if level == -1:
            # Exact parallel tabletop edges from the restaurant's source linework.
            item['tables'].extend([
                [[782.29,546.82],[836.23,596.52],[829.05,604.28],[775.11,554.58]],
                [[884.52,641.22],[938.39,690.99],[931.28,698.69],[877.34,648.98]],
            ])
            def within_table(point, polygon):
                sides = [(b[0]-a[0])*(point[1]-a[1])-(b[1]-a[1])*(point[0]-a[0]) for a, b in zip(polygon, polygon[1:]+polygon[:1])]
                return min(sides) >= -.2 or max(sides) <= .2
            item['excludedWallSegments'] = [segment for segment in floor['geometry']['walls']
                if any(all(within_table(point, table) for point in segment) for table in item['tables'][-2:])]
            # The owner confirmed this partition no longer exists on site.
            item['excludedWallSegments'].append(B1_REMOVED_PARTITION)
            item['excludedPlanSegments'] = [B1_REMOVED_PARTITION]
            item['tables'].append(B1_ADDED_DINING_TABLE)
            # The owner-confirmed salad island is a closed U-shaped counter,
            # drawn in black in the source plan. Recover its rounded outline,
            # including the opening, without treating its sides as room walls.
            salad_edges = [edge for edge in furniture_edges(
                ROOT/'atlas/studio-floor--1.svg', colors=('#b7c6d0',))
                if all(740 < x < 845 and 635 < y < 735 for x, y in edge[0])]
            salad = recover(floor['geometry'], salad_edges)
            if len(salad['tables']) != 1:
                raise ValueError('Expected one closed salad-bar island in B1')
            serving_counter = [[712.33,740.69],[776.71,740.69],[776.71,753.33],[712.33,753.33]]
            item['counters'] = salad['tables'] + [serving_counter]
            item['excludedDoorCurves'].extend(salad['excludedDoorCurves'])
            for segment in floor['geometry']['walls']:
                on_island = any(not curve and (
                    max(math.dist(a, b) for a, b in zip(segment, points)) < .12 or
                    max(math.dist(a, b) for a, b in zip(reversed(segment), points)) < .12
                ) for points, curve in salad_edges)
                if on_island or all(within_table(point, serving_counter) for point in segment):
                    item['excludedWallSegments'].append(segment)
            item['chairSeats'] = [points for points in floor['geometry']['tables']
                if 650 < sum(p[0] for p in points)/len(points) < 1000
                and 530 < sum(p[1] for p in points)/len(points) < 725]
        print(f"Floor {level}: {len(item['excludedDoorCurves'])} furniture arcs, {len(item['tables'])} curved tables")
    target = ROOT/'atlas/map-furniture.js'
    target.write_text('// Generated by tools/build_curved_tables.py from source furniture paths.\nconst corrections = '+json.dumps(corrections, separators=(',', ':'))+';\n\nconst without = (items, excluded) => excluded.size ? (items || []).filter(item => !excluded.has(JSON.stringify(item))) : items || [];\n\nexport function applyFurnitureCorrections(data) {\n  for (const floor of data.floors) {\n    const correction = corrections[floor.level];\n    if (!correction) continue;\n    const excluded = new Set(correction.excludedDoorCurves.map(curve => JSON.stringify(curve)));\n    floor.geometry.doorSwings = without(floor.geometry.doorSwings, excluded);\n    const tableEdges = new Set((correction.excludedWallSegments || []).map(segment => JSON.stringify(segment)));\n    floor.geometry.walls = without(floor.geometry.walls, tableEdges);\n    const removedPlan = new Set((correction.excludedPlanSegments || []).map(segment => JSON.stringify(segment)));\n    floor.geometry.planLinework = without(floor.geometry.planLinework, removedPlan);\n    floor.geometry.curvedTables = correction.tables;\n    if (correction.counters) floor.geometry.counters = correction.counters;\n    if (correction.chairSeats) {\n      const chairs = new Set(correction.chairSeats.map(points => JSON.stringify(points)));\n      floor.geometry.tables = without(floor.geometry.tables, chairs);\n      floor.geometry.chairSeats = correction.chairSeats;\n    }\n  }\n}\n', encoding='utf8')
