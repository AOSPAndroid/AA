"""Build label-free styled artwork from official PDF vectors. Build-time PyMuPDF only."""
from pathlib import Path
import xml.etree.ElementTree as ET
import fitz
import copy
from build_curved_tables import correct_b1_plan
from plan_fixture_corrections import correct_floor2_cupboards
ROOT=Path(__file__).resolve().parents[1]/'atlas'
NS='http://www.w3.org/2000/svg'
ET.register_namespace('',NS)
# Outer building landmarks in the source PDF's coordinate frame, expressed at 1800px.
common=[(14,629),(183,453),(438,453),(722,191),(969,453),(1259,453),(1423,311),(1778,711),(1391,937),(1457,994),(14,994)]
seven=[(14,632),(183,455),(438,455),(722,191),(969,455),(1259,455),(1423,311),(1778,711),(1460,949),(1400,975),(25,985)]
def tag(s):return '{'+NS+'}'+s
for floor in range(-1,9):
 doc=fitz.open(ROOT/f'official-floor-{floor}.pdf');page=doc[0]
 root=ET.fromstring(page.get_svg_image(text_as_path=False));root.set('width','3368');root.set('height','2380')
 # Remove all technical text, including desk codes, while retaining true furniture paths.
 for parent in root.iter():
  for child in list(parent):
   if child.tag in [tag('text'),tag('image')]:parent.remove(child)
 # Remove border/title geometry by clipping just above the title strip.
 defs=next(root.iter(tag('defs')))
 ET.SubElement(ET.SubElement(defs,tag('clipPath'),{'id':'artwork'}),tag('rect'),{'x':'7','y':'0','width':'828','height':'554'})
 furniture=[]
 for parent in list(root.iter()):
  if parent.tag==tag('defs') or parent.tag==tag('clipPath'):continue
  for p in list(parent):
   if p.tag!=tag('path'):continue
   stroke=p.get('stroke','').lower();fill=p.get('fill','none')
   if not stroke:continue
   p.set('vector-effect','non-scaling-stroke')
   if stroke=='#0000ff':
    p.set('stroke','#7396aa');p.set('stroke-width','1.6')
    if p.get('d','').strip().lower().endswith('z'):
     p.set('fill','#d4e5ee');furniture.append(p)
   elif stroke=='#000000':
    p.set('stroke','#b7c6d0');p.set('stroke-width','1.2')
    if fill!='none':p.set('fill','#a6b8c4')
   elif stroke=='#00ffff':
    p.set('stroke','#ccd9df');p.set('stroke-width','.8')
    if fill!='none':p.set('fill','#d9e5eb')
   elif stroke in ['#ff7f7f','#ff0000','#dd0000','#b80000']:
    p.set('stroke','#90a9b8');p.set('stroke-width','2.8')
   else:
    p.set('stroke','#c2d0d9');p.set('stroke-width','1')
    if fill!='none':p.set('fill','#d9e4e9')
 for parent in list(root.iter()):
  for p in list(parent):
   if p in furniture:
    shadow=ET.Element(tag('g'),{'transform':'translate(0 2.1)'})
    shape=copy.deepcopy(p);shape.set('fill','#9fb9c8');shape.set('stroke','#9fb9c8');shadow.append(shape)
    parent.insert(list(parent).index(p),shadow)
 children=[x for x in list(root) if x.tag!=tag('defs')]
 for x in children:root.remove(x)
 g=ET.SubElement(root,tag('g'),{'clip-path':'url(#artwork)'})
 if floor in [3,4,5,6,7]:
  pts=seven if floor==7 else common
  coords=' '.join(f'{x*842/1800:.2f},{y*842/1800:.2f}' for x,y in pts)
  ET.SubElement(g,tag('polygon'),{'points':coords,'fill':'#bdcdd7','transform':'translate(0 5)'})
  ET.SubElement(g,tag('polygon'),{'points':coords,'fill':'#eaf1f5','stroke':'#b9cbd6','stroke-width':'1'})
 else:
  ET.SubElement(g,tag('rect'),{'x':'8','y':'3','width':'826','height':'550','rx':'6','fill':'#edf3f6'})
 for x in children:g.append(x)
 if floor == -1: correct_b1_plan(root)
 if floor == 2: correct_floor2_cupboards(root)
 (ROOT/f'studio-floor-{floor}.svg').write_text(ET.tostring(root,encoding='unicode'))
 print(floor,len(furniture))
