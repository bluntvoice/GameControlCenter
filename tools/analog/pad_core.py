"""Continuous gamepad-to-touch geometry; no keyboard or mouse synthesis."""
import math

def recenter_axis_pair(values,center=(0,0)):
    """Remove a measured resting offset while retaining both full endpoints."""
    if len(center)!=2 or any(not math.isfinite(c) or abs(c)>.25 for c in center):
        raise ValueError('Invalid measured stick center')
    return tuple(max(-1.0,min(1.0,(v-c)/(1-c if v>=c else 1+c))) for v,c in zip(values,center))

BUTTON_KEYS = {'A':'1','B':'2','X':'3','Y':'4','LB':'5','RB':'6',
               'LT':'7','RT':'8','UP':'9','DOWN':'0','LEFT':'Minus','RIGHT':'Equal',
               'LS':'BracketLeft','RS':'BracketRight','START':'Return','BACK':'Backspace'}
BUTTON_IDS = {name:i+3 for i,name in enumerate(BUTTON_KEYS)}

def radial(x,y,deadzone=0.12,power=1.0):
    radius=math.hypot(x,y)
    if radius <= deadzone:
        return 0.0,0.0
    length=(min(1.0,radius)-deadzone)/(1-deadzone)
    return x/radius*length**power,y/radius*length**power

def normalized(point):
    return tuple(max(0,min(65534,round(v*65535))) for v in point)

class Mapper:
    def __init__(self, profile, width, height, settings):
        self.width,self.height,self.settings=width,height,settings
        nodes=profile['keyMapNodes']
        self.wheel=next((n for n in nodes if n['type']=='KMT_STEER_WHEEL'),None)
        camera=next((n for n in nodes if n['type']=='KMT_CAMERA_MOVE'),None)
        self.camera=camera['pos'] if camera else None
        self.bindings={name:n for name,key in BUTTON_KEYS.items() for n in nodes if n.get('key')=='Key_'+key}
        aliases={'↑':'UP','↓':'DOWN','←':'LEFT','→':'RIGHT','Start':'START','Back':'BACK'}
        controls=profile.get('_adapter',{}).get('controls',[])
        self.behaviors={aliases.get(c['name'],c['name']):c for c in controls}
        self.reset()

    def reset(self):
        self.previous={}
        self.previous_buttons=set()
        self.pressed_at={}
        self.order={}
        self.tick=0
        self.camera_pos=None
        self.last_time=None
        self.last_aim=None
        self.blocked_buttons=set()

    def guard_resume(self,state):
        # Sticks are continuous directions. Resume them from fresh readings,
        # while buttons held across a suspension need a new release/press edge.
        self.reset()
        self.blocked_buttons=set(state['buttons'])

    def frame(self,state,now):
        dt=min(0.03,max(0.0,now-self.last_time)) if self.last_time is not None else 0.0
        self.last_time=now; self.tick+=1
        buttons=set(state['buttons'])
        self.blocked_buttons.intersection_update(buttons)
        buttons-=self.blocked_buttons
        for name in buttons-self.previous_buttons:
            self.pressed_at[name]=now; self.order[name]=self.tick
        self.previous_buttons=buttons
        left=radial(*state['left'],self.settings['left_deadzone'])
        right=radial(*state['right'],self.settings['right_deadzone'],self.settings['right_curve'])
        wanted={}; anchors={}
        if self.wheel and left != (0.0,0.0):
            c=self.wheel['centerPos']; anchors[1]=(c['x'],c['y'])
            ox=self.wheel['rightOffset'] if left[0]>=0 else self.wheel['leftOffset']
            oy=self.wheel['downOffset'] if left[1]>=0 else self.wheel['upOffset']
            wanted[1]=(c['x']+left[0]*ox,c['y']+left[1]*oy)
        aim_candidates=[name for name in self.bindings if name in buttons and
                        self.bindings[name]['type']=='KMT_FREE_LOOK']
        aim=max(aim_candidates,key=lambda name:(self.order.get(name,0),BUTTON_IDS[name])) if aim_candidates else None
        for name in self.bindings:
            if name not in buttons: continue
            behavior=self.behaviors.get(name,{})
            mode=behavior.get('mode','once' if name=='X' else 'hold')
            age=now-self.pressed_at[name]
            if mode=='once' and age>=0.050:continue
            if mode=='repeat':
                period=1/behavior.get('hz',10)
                if age%period>=min(.05,period*.5):continue
            node=self.bindings[name]; p=node.get('startPos',node['pos']); ident=BUTTON_IDS[name]
            anchors[ident]=(p['x'],p['y']); wanted[ident]=anchors[ident]
            if name==aim:
                radius=behavior.get('radius',self.settings['skill_radius_px'])
                # Editor ranges use a 1200px-high reference, scale with phone frame.
                radius=radius*self.height/1200 if behavior else radius
                wanted[ident]=(p['x']+right[0]*radius/self.width,p['y']+right[1]*radius/self.height)
        if self.camera and not aim and right != (0.0,0.0):
            anchor=(self.camera['x'],self.camera['y']); anchors[2]=anchor
            if 2 not in self.previous or self.camera_pos is None:
                self.camera_pos=anchor
            else:
                speed=self.settings['camera_px_per_sec']*self.behaviors.get('右摇杆',{}).get('radius',100)/100
                x=self.camera_pos[0]+right[0]*speed*dt/self.width
                y=self.camera_pos[1]+right[1]*speed*dt/self.height
                if not (0.08<x<0.92 and 0.10<y<0.90):
                    # Lift before reanchoring; a new DOWN must not jump the existing finger.
                    self.camera_pos=None
                else:
                    self.camera_pos=(x,y)
            if self.camera_pos is not None: wanted[2]=self.camera_pos
        else:
            self.camera_pos=None
        # A newly pressed finger starts at the calibrated center, then moves next tick.
        result={}
        for ident,point in wanted.items():
            if len(result)>=10: break
            point=anchors[ident] if ident not in self.previous else point
            result[ident]=normalized(point)
        self.previous=result
        self.last_aim=aim
        return result

    def neutral(self,state):
        return (not state['buttons'] and
                radial(*state['left'],self.settings['left_deadzone'])==(0.0,0.0) and
                radial(*state['right'],self.settings['right_deadzone'])==(0.0,0.0))
