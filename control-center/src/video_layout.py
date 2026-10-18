"""Remember normal projection windows; never keep moving a live game window."""
import math


def valid_layout(value):
    if not isinstance(value,dict):return False
    for key,count in [('rect',4),('work',4),('client',2)]:
        items=value.get(key)
        if not isinstance(items,(list,tuple)) or len(items)!=count:return False
        if any(isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) for n in items):return False
    return (value['rect'][2]>=160 and value['rect'][3]>=100 and
            value['work'][2]>0 and value['work'][3]>0 and min(value['client'])>0 and
            isinstance(value.get('dpi'),(int,float)) and not isinstance(value['dpi'],bool) and 48<=value['dpi']<=768)


def restore_rect(saved,current):
    """Use physical pixels, keep aspect, and fit the nearest available work area."""
    x,y,ww,wh=current['work'];dpi=current['dpi']
    if valid_layout(saved):
        ratio=dpi/saved['dpi'];sx,sy,sw,sh=saved['rect'];ox,oy,ow,oh=saved['work']
        width,height=sw*ratio,sh*ratio
        # Retain the position within this monitor even after its origin changes.
        left=x+(sx-ox)/ow*ww;top=y+(sy-oy)/oh*wh
    else:
        width=min(1100*dpi/96,ww*.65);height=wh*.7
        left=x+(ww-width)/2;top=y+(wh-height)/2
    client_w,client_h=current['client'];cw,ch=current['rect'][2:]
    frame_w=max(0,cw-client_w);frame_h=max(0,ch-client_h)
    # A phone rotation must fit inside the remembered box rather than stretch it.
    if not valid_layout(saved) or abs(client_w/client_h/(saved['client'][0]/saved['client'][1])-1)>.1:
        scale=min(max(1,width-frame_w)/client_w,max(1,height-frame_h)/client_h)
        width=client_w*scale+frame_w;height=client_h*scale+frame_h
    scale=min(1,ww/max(1,width),wh/max(1,height))
    width=max(1,round(width*scale));height=max(1,round(height*scale))
    return [round(min(max(left,x),x+ww-width)),round(min(max(top,y),y+wh-height)),width,height]


class VideoLayoutMemory:
    def __init__(self,saved=None):
        self.saved=saved if valid_layout(saved) else None
        self.handle=None;self.candidate=None;self.since=0;self.ready=0

    def observe(self,handle,snapshot,now):
        if not handle:
            self.handle=None;self.candidate=None
            return None
        if not snapshot or not snapshot.get('normal'):return None
        if handle!=self.handle:
            self.handle=handle;self.candidate=None;self.ready=now+2
            return ('restore',restore_rect(self.saved,snapshot))
        if now<self.ready:return None
        value={key:snapshot[key] for key in ('rect','work','client','dpi')}
        if not valid_layout(value):return None
        if value!=self.candidate:
            self.candidate=value;self.since=now
        elif now-self.since>=1 and value!=self.saved:
            self.saved=value
            return ('save',value)
        return None
