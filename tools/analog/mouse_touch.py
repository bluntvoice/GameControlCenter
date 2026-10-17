"""Merge mouse gestures with controller fingers in one touch snapshot."""
from collections import deque
import math
from pad_core import normalized

MOUSE_ID=20

def fit_rect(rect,width,height):
    x,y,w,h=rect
    scale=min(w/width,h/height);cw=width*scale;ch=height*scale
    return round(x+(w-cw)/2),round(y+(h-ch)/2),round(cw),round(ch)

class MouseTouch:
    def __init__(self):self.reset()
    def reset(self):
        self.queue=deque();self.point=None;self.down_at=0;self.received=0
    def event(self,kind,x,y,width,height):
        if width<=0 or height<=0:return
        point=normalized((x/width,y/height))
        if kind=='move' and self.queue and self.queue[-1][0]=='move':self.queue[-1]=(kind,point)
        elif len(self.queue)<64:self.queue.append((kind,point))
        self.received+=1
    def frame(self,now):
        if self.queue:
            kind,point=self.queue[0]
            if kind=='up' and self.point is not None and now-self.down_at<.04:return self.point
            self.queue.popleft()
            if kind=='down':self.point=point;self.down_at=now
            elif kind=='move' and self.point is not None:self.point=point
            elif kind=='up':self.point=None
        return self.point

def merge(points,mouse):
    if mouse is None:return dict(points)
    if isinstance(mouse,dict):return dict(list(points.items())[:max(0,10-len(mouse))]+list(mouse.items())[:10])
    return dict(list(points.items())[:9]+[(MOUSE_ID,mouse)])

class MouseChannels:
    """Two mouse buttons; unbound left keeps the accepted free click/drag behavior."""
    def __init__(self):
        self.left=MouseTouch();self.right=MouseTouch();self.targets={};self.behaviors={};self.coverage=[];self.received=0;self.gesture_offset=None;self.aim_origins={}
    @property
    def point(self):return self.left.point or self.right.point
    def configure(self,controls):
        self.targets={c['name']:(c['x'],c['y']) for c in controls if c['name'] in ('鼠标左键','鼠标右键')}
        self.behaviors={c['name']:c for c in controls if c['name'] in self.targets}
        self.coverage=[c for c in controls if c.get('hit_radius',0)>0 and c['name'] not in ('左摇杆','右摇杆','鼠标左键','鼠标右键')]
        self.reset()
    def reset(self):self.left.reset();self.right.reset();self.received=0;self.gesture_offset=None;self.aim_origins={}
    def event(self,kind,x,y,width,height,button='left'):
        name='鼠标左键' if button=='left' else '鼠标右键'
        if button=='right' and name not in self.targets:return
        if name in self.targets:
            if width<=0 or height<=0:return
            target=self.targets[name];behavior=self.behaviors[name]
            if behavior.get('mode','once')=='aim':
                if kind=='down':self.aim_origins[button]=(x/width,y/height)
                origin=self.aim_origins.get(button,(x/width,y/height))
                dx=x/width-origin[0];dy=y/height-origin[1]
                distance=math.hypot(dx*width,dy*height);radius=behavior.get('radius',75)*height/1200
                scale=min(1,radius/distance) if distance else 1
                x,y=target[0]+dx*scale,target[1]+dy*scale
                if kind=='up':self.aim_origins.pop(button,None)
            else:
                if kind=='move':return
                x,y=target
            width=height=1
        elif button=='left' and width>0 and height>0:
            if kind=='down':
                self.gesture_offset=None;hits=[]
                for control in self.coverage:
                    distance=math.hypot(x-control['x']*width,y-control['y']*height)
                    if distance<=control['hit_radius']*height/1200:
                        hits.append((distance,control))
                if hits:
                    target=min(hits,key=lambda pair:pair[0])[1]
                    self.gesture_offset=(target['x']-x/width,target['y']-y/height)
            if self.gesture_offset:
                x=x/width+self.gesture_offset[0];y=y/height+self.gesture_offset[1];width=height=1
            if kind=='up':self.gesture_offset=None
        (self.left if button=='left' else self.right).event(kind,x,y,width,height)
        self.received+=1
    def frame(self,now):
        points={}
        # Companion accepts ids 1..20; gamepad uses 1..18, mouse owns 19/20.
        for ident,name,channel in ((20,'鼠标左键',self.left),(19,'鼠标右键',self.right)):
            point=channel.frame(now)
            if point is None:continue
            if name in self.targets:
                behavior=self.behaviors[name];mode=behavior.get('mode','once');age=now-channel.down_at
                if mode=='once' and age>=.05:continue
                if mode=='repeat':
                    period=1/behavior.get('hz',10)
                    if age%period>=min(.05,period*.5):continue
            points[ident]=point
        return points
