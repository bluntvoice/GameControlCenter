"""Render the bundled Lucide gamepad-2 SVG into Windows icon sizes, offline."""
from pathlib import Path
from xml.etree import ElementTree
from PIL import Image,ImageDraw
from fontTools.pens.basePen import BasePen
from fontTools.svgLib.path import parse_path

home=Path(__file__).resolve().parents[1]
assets=home/'assets';assets.mkdir(parents=True,exist_ok=True)
size=1024;scale=size/32;offset=4*scale
image=Image.new('RGBA',(size,size),(0,0,0,0));draw=ImageDraw.Draw(image)
draw.rounded_rectangle((scale,scale,size-scale,size-scale),radius=6*scale,fill='#172A40')

def stroke(points):
    points=[(offset+x*scale,offset+y*scale) for x,y in points]
    width=round(2*scale);radius=width/2
    draw.line(points,fill='#E7EDF3',width=width,joint='curve')
    for x,y in points:draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill='#E7EDF3')

class Outline(BasePen):
    def __init__(self):super().__init__(None);self.points=[]
    def _moveTo(self,point):
        if self.points:stroke(self.points)
        self.points=[point]
    def _lineTo(self,point):self.points.append(point)
    def _curveToOne(self,p1,p2,p3):
        p0=self.points[-1]
        for index in range(1,25):
            t=index/24;u=1-t
            self.points.append(tuple(u**3*p0[i]+3*u*u*t*p1[i]+3*u*t*t*p2[i]+t**3*p3[i] for i in (0,1)))
    def _closePath(self):
        self.points.append(self.points[0]);stroke(self.points);self.points=[]
    def _endPath(self):stroke(self.points);self.points=[]

svg=ElementTree.parse(assets/'lucide/gamepad-2.svg').getroot()
for node in svg:
    if node.tag.endswith('line'):
        stroke([(float(node.attrib[f'x{i}']),float(node.attrib[f'y{i}'])) for i in (1,2)])
    elif node.tag.endswith('path'):parse_path(node.attrib['d'],Outline())
image=image.resize((256,256),Image.Resampling.LANCZOS)
image.save(assets/'center.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
image.save(assets/'center.png')
print(assets/'center.ico')
