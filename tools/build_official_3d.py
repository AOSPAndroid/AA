"""Extract simplified 3D furniture and wall geometry directly from official PDFs."""
from pathlib import Path
import fitz,json
root=Path(__file__).resolve().parents[1]/'atlas'
data=json.loads((root/'official-data.json').read_text())
common=[[14,629],[183,453],[438,453],[722,191],[969,453],[1259,453],[1423,311],[1778,711],[1391,937],[1457,994],[14,994]]
for floor in data['floors']:
 page=fitz.open(root/f"official-floor-{floor['level']}.pdf")[0];factor=1800/page.rect.width
 cv=lambda p:[round(p.x*factor,2),round(p.y*factor,2)]
 walls=[];furniture=[]
 for d in page.get_drawings():
  color=d.get('color');rect=d['rect']
  if rect.y1>550 or not color:continue
  if color[0]>.6 and color[1]<.6 and color[2]<.6:
   for item in d['items']:
    if item[0]=='l' and abs(item[1]-item[2])>2:walls.append([cv(item[1]),cv(item[2])])
  if color!=(0,0,1):continue
  pts=[]
  if len(d['items'])==1 and d['items'][0][0]=='re':
   r=d['items'][0][1];pts=[r.tl,r.tr,r.br,r.bl]
  elif len(d['items'])==4 and all(i[0]=='l' for i in d['items']):
   if abs(d['items'][-1][2]-d['items'][0][1])<.1:pts=[i[1] for i in d['items']]
  if pts and 6<rect.width<65 and 6<rect.height<65:furniture.append([cv(p) for p in pts])
 floor['geometry'].update(outline=common if floor['level'] in [3,4,5,6] else floor['geometry']['outline'],walls=walls,tables=furniture,stairs=[],furniture=[])
(root/'official-data.json').write_text(json.dumps(data,ensure_ascii=False))
print('Extracted',sum(len(f['geometry']['tables']) for f in data['floors']),'furniture polygons')
