"""Shared profile catalogue and normalized editor model. Never emits input."""
import copy
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import uuid

KEYS={'A':'Key_1','B':'Key_2','X':'Key_3','Y':'Key_4','LB':'Key_5','RB':'Key_6',
      'LT':'Key_7','RT':'Key_8','↑':'Key_9','↓':'Key_0','←':'Key_Minus','→':'Key_Equal',
      'LS':'Key_BracketLeft','RS':'Key_BracketRight','Start':'Key_Return','Back':'Key_Backspace',
      '鼠标左键':'LeftButton','鼠标右键':'RightButton'}
NAMES=list(KEYS)+['左摇杆','右摇杆']
MODES={'按住':'hold','单次点击':'once','连续点击':'repeat','按住瞄准':'aim'}
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def encode(data):return json.dumps(data,ensure_ascii=False,indent=2).encode('utf-8')
def digest(data):return hashlib.sha256(data).hexdigest()
def write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:temp.write_bytes(encode(data));os.replace(temp,path)
    finally:temp.unlink(missing_ok=True)

def validate_name(name):
    name=name.strip()
    if not name or len(name)>45 or re.search(r'[<>:"/\\|?*\x00-\x1f]',name) or name.endswith(('.', ' ')):
        raise ValueError('名称需为 1～45 个字符，不能包含文件名特殊字符')
    if name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
        raise ValueError('请换一个方案名称')
    return name

def validate_controls(controls):
    if not isinstance(controls,list):raise ValueError('按键数据格式错误')
    seen=set()
    for item in controls:
        name=item.get('name')
        if name not in NAMES or name in seen:raise ValueError('按键不支持或重复：'+str(name))
        seen.add(name)
        for axis in ('x','y'):
            if not isinstance(item.get(axis),(int,float)) or not math.isfinite(item[axis]) or not 0<=item[axis]<=1:
                raise ValueError('按键位置需要在投屏画面内')
        if item.get('mode','hold') not in {'hold','once','repeat','aim'}:raise ValueError('未知触发方式')
        radius=item.get('radius',75)
        if not isinstance(radius,(int,float)) or not math.isfinite(radius) or not 10<=radius<=400:
            raise ValueError('范围需要在 10～400 之间')
        if not 1<=item.get('hz',10)<=20:raise ValueError('连点频率需要在 1～20 次/秒之间')
        hit_radius=item.get('hit_radius',0)
        if not isinstance(hit_radius,(int,float)) or not math.isfinite(hit_radius) or not 0<=hit_radius<=400:
            raise ValueError('覆盖半径需要在 0～400 之间，0 表示关闭点击覆盖')

def controls_from_native(profile,metadata=None):
    metadata={c['name']:c for c in (metadata or [])};reverse={v:k for k,v in KEYS.items()};result=[]
    for node in profile['keyMapNodes']:
        kind=node['type'];name=reverse.get(node.get('key'));point=node.get('pos')
        if kind=='KMT_STEER_WHEEL':name='左摇杆';point=node['centerPos']
        elif kind=='KMT_CAMERA_MOVE':name='右摇杆'
        if not name or not point:continue
        item=dict(name=name,x=point['x'],y=point['y'],mode='aim' if kind=='KMT_FREE_LOOK' else 'once' if name=='X' else 'hold',radius=100 if name=='右摇杆' else 90 if kind=='KMT_FREE_LOOK' else 75,hz=10,hit_radius=0)
        if kind=='KMT_STEER_WHEEL':item['radius']=node['upOffset']*1200
        if name in metadata:item.update({k:v for k,v in metadata[name].items() if k not in ('x','y','name')})
        item['hz']=metadata.get(name,{}).get('hz',10) if item['mode']=='repeat' else 1
        result.append(item)
    return result

def native_from_controls(name,controls):
    validate_controls(controls);nodes=[]
    for item in controls:
        name_=item['name'];point=dict(x=item['x'],y=item['y']);mode=item.get('mode','hold')
        if name_=='左摇杆':
            radius=item.get('radius',75)
            node=dict(type='KMT_STEER_WHEEL',centerPos=point,leftKey='Key_A',rightKey='Key_D',upKey='Key_W',downKey='Key_S',
                leftOffset=radius/2608,rightOffset=radius/2608,upOffset=radius/1200,downOffset=radius/1200)
        elif name_=='右摇杆':node=dict(type='KMT_CAMERA_MOVE',key='Key_QuoteLeft',pos=point,speedRatioX=1.0,speedRatioY=1.0)
        elif mode=='aim':node=dict(type='KMT_FREE_LOOK',key=KEYS[name_],pos=point,startPos=point.copy(),speedRatioX=1.0,speedRatioY=1.0,resetViewOnRelease=False)
        else:
            script='if (mapi.isPress()) { mapi.click(); }' if mode=='once' else 'mapi.holdpress();'
            node=dict(type='KMT_SCRIPT',key=KEYS[name_],pos=point,script=script)
        nodes.append(node)
    return dict(switchKey='Key_QuoteLeft',keyMapNodes=nodes,migration=dict(source_name=name,source='控制台拖放编辑器',calibration_status='user_placed_pending_gameplay'))

class ProfileStore:
    def __init__(self,project,keymap):
        self.project=Path(project);self.keymap=Path(keymap)
        self.path=self.project/'phase2b-20261015/profiles/library.json'
        self.backups=self.project/'control-center/backups/profile-edits'
    def ensure(self):
        if self.path.exists():return self.catalog()
        legacy=self.keymap/'超燃竞技场-三技能.json'
        seeded=not legacy.exists()
        if seeded:
            self.keymap.mkdir(parents=True,exist_ok=True)
            write(legacy,read(self.project/'examples/超燃竞技场-三技能.json'))
        data=legacy.read_bytes()
        entry=dict(id='arena-3skills',name='超燃竞技场-三技能',path=str(legacy),status='待游戏校对',
            controls=controls_from_native(json.loads(data)),revision=1,legacy=True)
        if seeded:
            entry['controls']=read(self.project/'examples/超燃竞技场-三技能.controls.json')
            entry['legacy']=False
        write(self.path,dict(version=1,active=entry['id'],profiles=[entry]))
        return self.catalog()
    def catalog(self):
        value=read(self.path)
        if value.get('version')!=1:raise ValueError('方案库版本不支持')
        return value
    def entry(self,ident=None):
        catalog=self.catalog();ident=ident or catalog['active']
        for entry in catalog['profiles']:
            if entry['id']==ident or entry['name']==ident:return entry
        raise ValueError('方案不存在，请刷新列表')
    def load(self,ident=None):
        entry=copy.deepcopy(self.entry(ident));path=Path(entry['path'])
        if path.parent.resolve()!=self.keymap.resolve():raise ValueError('方案路径超出允许目录')
        data=path.read_bytes();entry['controls']=controls_from_native(json.loads(data),entry.get('controls'))
        entry['sha256']=digest(data);return entry
    def active_runtime(self):
        entry=self.load();data=read(entry['path']);data['_adapter']=dict(controls=[] if entry.get('legacy') else entry['controls'],profile_id=entry['id'],name=entry['name'])
        return data,digest(encode(data))
    def select(self,ident):
        entry=self.load(ident);catalog=self.catalog();catalog['active']=entry['id'];write(self.path,catalog);return entry
    def save(self,name,controls,ident=None,expected_sha=None):
        controls=copy.deepcopy(controls)
        for item in controls:item['hz']=item.get('hz',10) if item.get('mode')=='repeat' else 1
        name=validate_name(name);validate_controls(controls)
        if not controls:raise ValueError('先拖入至少一个按键或摇杆，再保存方案')
        catalog=self.catalog();old=self.entry(ident) if ident else None
        for entry in catalog['profiles']:
            if entry['name'].casefold()==name.casefold() and (not old or entry['id']!=old['id']):
                raise ValueError('已有同名方案，请换一个名称或编辑该方案')
        if old and old['name']!=name:raise ValueError('更名请使用“另存副本”，避免覆盖其他文件')
        target=Path(old['path']) if old else self.keymap/(name+'.json')
        if target.parent.resolve()!=self.keymap.resolve():raise ValueError('方案路径超出允许目录')
        before=target.read_bytes() if target.exists() else None
        if not old and before is not None:raise ValueError('投屏软件已存在同名配置，未覆盖原文件')
        if old and expected_sha and digest(before or b'')!=expected_sha:raise ValueError('方案已被外部修改，请重新载入后编辑')
        stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        backup=self.backups/stamp;backup.mkdir(parents=True,exist_ok=False)
        (backup/'library.json').write_bytes(self.path.read_bytes())
        if before is not None:(backup/target.name).write_bytes(before)
        entry=dict(id=old['id'] if old else uuid.uuid4().hex,name=name,path=str(target),status='待游戏验收',controls=copy.deepcopy(controls),revision=(old.get('revision',0) if old else 0)+1)
        profile=native_from_controls(name,controls)
        catalog['profiles']=[entry if e['id']==entry['id'] else e for e in catalog['profiles']]
        if not old:catalog['profiles'].append(entry)
        try:
            write(target,profile);write(self.path,catalog)
        except OSError:
            if before is not None:target.write_bytes(before)
            else:target.unlink(missing_ok=True)
            raise
        return self.load(entry['id'])
