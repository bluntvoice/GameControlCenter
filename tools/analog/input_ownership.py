"""One owner for ALL gamepad touch input, including keyboard-emitting bridges."""
from pathlib import Path
import xml.etree.ElementTree as ET

def inspect_profile(path):
    try:
        root=ET.parse(Path(path)).getroot()
        if root.tag.split('}')[-1]!='gamecontroller': raise ValueError('Unexpected profile type')
        name=next(((n.text or '').strip() for n in root.iter() if n.tag.split('}')[-1]=='profilename'),'')
        slots=[n for n in root.iter() if n.tag.split('}')[-1]=='slot']
        modes=sorted({(n.text or '').strip() for slot in slots for n in slot.iter()
                      if n.tag.split('}')[-1]=='mode'})
        return dict(valid=True,name=name,slot_count=len(slots),modes=modes)
    except (OSError,ET.ParseError,ValueError) as ex:
        return dict(valid=False,error=str(ex))

def decide(processes,selection,blank_info):
    if not processes:
        return dict(allow=True,state='STOPPED',pid=None,hidden=False,
                    reason='AntiMicroX 未运行，触控由适配器独立处理',detail='进程检查未发现备用映射器')
    pid=processes[0].get('pid'); hidden=any(not p.get('visible') for p in processes)
    base=dict(pid=pid,hidden=hidden)
    state,value=selection
    if state=='read' and value=='<新>':
        return dict(**base,allow=True,state='CLEAR',reason='AntiMicroX 选择为空方案',detail='读取到当前界面的 <新>')
    if (state=='read' and blank_info.get('valid') and blank_info.get('slot_count')==0
            and value==blank_info.get('name')=='空白方案-无映射-右摇杆归适配器'):
        return dict(**base,allow=True,state='SAFE_BLANK',reason='AntiMicroX 当前为空白无映射方案',
                    detail='界面名称与专用空白文件一致，XML 中不存在任何输出 slot')
    reason=('备用映射器状态无法从当前界面确认' if state!='read' else
            '备用映射器加载了其他方案，可能与适配器重复输出键鼠或触控')
    return dict(**base,allow=False,state='UNVERIFIED' if state!='read' else 'COMPETING_PROFILE',
                reason=reason+'；请退出 AntiMicroX，或选择 <新> / 专用空白方案',
                detail=f'当前界面读取结果：{value or "不可读取"}；不使用持久化 ini 推断当前内存中的方案')
