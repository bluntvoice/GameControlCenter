"""ADB observations. Missing samples remain missing, never invented zero FPS."""
import math
import re
import statistics
import subprocess
import time

def battery_parse(text):
    pairs=dict(re.findall(r'^\s*([A-Za-z ]+):\s*(.*?)\s*$',text,re.M))
    level=int(pairs['level']); scale=int(pairs.get('scale','100'))
    if not 0<=level<=scale or scale<=0: raise ValueError('Invalid battery level')
    return dict(percent=round(level/scale*100),charging=pairs.get('status') in ('2','5'),
                temperature=float(pairs['temperature'])/10 if 'temperature' in pairs else None,
                at=time.time())

def latency_parse(text,last_timestamp=0):
    values=[]
    for line in text.splitlines()[1:]:
        parts=line.split()
        if len(parts)!=3: continue
        try: present=int(parts[1])
        except ValueError: continue
        if 0<present<9_000_000_000_000_000_000: values.append(present)
    values=sorted(set(values))
    new=[t for t in values if t>last_timestamp]
    if not new: return dict(fps=None,p95_ms=None,last_timestamp=last_timestamp,new_frames=0)
    # Calculate within the available ring buffer, never across its overwritten gap.
    # Polling + ADB latency may exceed the 127-frame buffer's duration.
    if len(values)<3: return dict(fps=None,p95_ms=None,last_timestamp=new[-1],new_frames=len(new))
    intervals=[(b-a)/1e6 for a,b in zip(values,values[1:])]
    span=(values[-1]-values[0])/1e9
    fps=(len(values)-1)/span if span>0 else None
    p95=sorted(intervals)[min(len(intervals)-1,math.ceil(len(intervals)*.95)-1)]
    return dict(fps=round(fps,2) if fps is not None else None,p95_ms=round(p95,2),
                last_timestamp=new[-1],new_frames=len(new))

def layer_pick(text,package):
    candidates=[]
    for line in text.splitlines():
        if package not in line or 'SurfaceView[' not in line or '(BLAST)' not in line: continue
        # Android 17 wraps --list lines in RequestedLayerState{... parentId=...}.
        if line.startswith('RequestedLayerState{'):
            line=line[len('RequestedLayerState{'):].split(' parentId=')[0].rstrip('}')
        candidates.append(line.strip())
    return candidates[-1] if candidates else None

class Phone:
    def __init__(self,config):
        self.config=config; self.layer=None; self.layer_at=0; self.battery_at=0
        self.last_timestamp=0; self.battery=None
    def run(self,*args,timeout=3):
        p=subprocess.run([self.config['adb'],'-s',self.config['serial'],*args],
            capture_output=True,encoding='utf-8',errors='replace',timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if p.returncode: raise RuntimeError((p.stderr or p.stdout).strip()[:180])
        return p.stdout
    def sample(self):
        now=time.time()
        try:
            state=self.run('get-state',timeout=2).strip()
            if state!='device': raise RuntimeError(state or 'Phone unavailable')
        except (RuntimeError,subprocess.TimeoutExpired) as ex:
            self.layer=None; self.last_timestamp=0
            return dict(connected=False,error=str(ex),battery=self.battery,fps=None,p95_ms=None,at=now)
        errors=[]
        if now-self.battery_at>15:
            try:
                self.battery=battery_parse(self.run('shell','dumpsys battery'))
                self.battery_at=now
            except (RuntimeError,ValueError,KeyError,subprocess.TimeoutExpired) as ex: errors.append('电量读取失败：'+str(ex))
        if self.layer is None or now-self.layer_at>15:
            try:
                layer=layer_pick(self.run('shell','dumpsys SurfaceFlinger --list'),self.config['package'])
                if layer!=self.layer: self.last_timestamp=0
                self.layer=layer; self.layer_at=now
            except (RuntimeError,subprocess.TimeoutExpired) as ex: errors.append(str(ex))
        frames=dict(fps=None,p95_ms=None,new_frames=0)
        if self.layer:
            try:
                # Layer text is remote shell data. Quote single quotes correctly.
                quoted="'"+self.layer.replace("'","'\"'\"'")+"'"
                frames=latency_parse(self.run('shell','dumpsys SurfaceFlinger --latency '+quoted),self.last_timestamp)
                self.last_timestamp=frames['last_timestamp']
            except (RuntimeError,subprocess.TimeoutExpired) as ex: errors.append(str(ex))
        return dict(connected=True,battery=self.battery,layer=self.layer,at=now,
                    errors=errors,**frames)
