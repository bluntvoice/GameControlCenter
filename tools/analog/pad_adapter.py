"""Visible, scoped XInput-to-multitouch companion for the calibrated sample."""
import configparser
import ctypes as C
from ctypes import wintypes as W
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

from pad_core import Mapper,recenter_axis_pair
from mouse_touch import MouseTouch,MouseChannels,fit_rect,merge
from pad_transport import ROOT,PHASE,Transport,touches_none,NeutralRequired,run_command,COMMAND_CONTEXT
from touch_queue import TouchQueue

from app_config import load_config
CONFIG=load_config()
LIVE=Path(CONFIG['gamescrcpy']).parent/'keymap/超燃竞技场-三技能.json'
USER_INI=LIVE.parents[1]/'config/userdata.ini'
STATUS=PHASE/'analog/status.json'
ANTIMICROX_INI=Path(CONFIG['antimicrox_settings'])
# How long the touch worker tolerates no UI update before assuming the Tk thread is
# wedged. Kept well above any normal scheduling stall so brief hiccups cannot end a
# session, while still catching a genuinely dead UI.
WATCHDOG_SECONDS=2.0
HEARTBEAT_SECONDS=.05

def frame_due(points,previous,now,last_sent):
    # Unchanged positions need a heartbeat, not 120 identical touch MOVE/ACKs.
    return previous is None or points!=previous or now-last_sent>=HEARTBEAT_SECONDS

class Gamepad(C.Structure):
    _fields_=[('buttons',W.WORD),('lt',C.c_ubyte),('rt',C.c_ubyte),
              ('lx',C.c_short),('ly',C.c_short),('rx',C.c_short),('ry',C.c_short)]
class State(C.Structure):
    _fields_=[('packet',W.DWORD),('pad',Gamepad)]
MASKS={'UP':1,'DOWN':2,'LEFT':4,'RIGHT':8,'START':16,'BACK':32,
       'LS':64,'RS':128,'LB':256,'RB':512,'A':4096,'B':8192,'X':16384,'Y':32768}
class XInput:
    def __init__(self):
        self.dll=C.WinDLL('xinput1_4.dll')
        self.dll.XInputGetState.argtypes=[W.DWORD,C.POINTER(State)]
        self.dll.XInputGetState.restype=W.DWORD
        self.index=None
        self.right_center=(0,0)
    def read(self):
        indices=[self.index] if self.index is not None else range(4)
        for index in indices:
            s=State()
            if self.dll.XInputGetState(index,C.byref(s))==0:
                self.index=index; p=s.pad
                axis=lambda value:max(-1.0,min(1.0,value/32767.0))
                buttons={name for name,mask in MASKS.items() if p.buttons&mask}
                if p.lt>40: buttons.add('LT')
                if p.rt>40: buttons.add('RT')
                hardware_right=(axis(p.rx),-axis(p.ry))
                return dict(left=(axis(p.lx),-axis(p.ly)),right=recenter_axis_pair(hardware_right,self.right_center),hardware_right=hardware_right,
                            buttons=sorted(buttons),packet=s.packet,index=index)
        self.index=None
        return None

user32=C.WinDLL('user32',use_last_error=True)
user32.GetForegroundWindow.restype=W.HWND
user32.GetAncestor.argtypes=[W.HWND,W.UINT]; user32.GetAncestor.restype=W.HWND
user32.GetWindowRect.argtypes=[W.HWND,C.POINTER(W.RECT)]
user32.GetClassNameW.argtypes=[W.HWND,W.LPWSTR,C.c_int]
user32.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
user32.IsIconic.argtypes=[W.HWND]
user32.IsWindow.argtypes=[W.HWND]
user32.IsWindowVisible.argtypes=[W.HWND]
user32.GetWindowTextW.argtypes=[W.HWND,W.LPWSTR,C.c_int]
user32.SetForegroundWindow.argtypes=[W.HWND]
user32.SetWindowPos.argtypes=[W.HWND,W.HWND,C.c_int,C.c_int,C.c_int,C.c_int,W.UINT]
ENUMPROC=C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
user32.EnumWindows.argtypes=[ENUMPROC,W.LPARAM]

def process_path(hwnd):
    pid=W.DWORD(); user32.GetWindowThreadProcessId(hwnd,C.byref(pid))
    kernel=C.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD]; kernel.OpenProcess.restype=W.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,C.POINTER(W.DWORD)]
    kernel.CloseHandle.argtypes=[W.HANDLE]
    handle=kernel.OpenProcess(0x1000,False,pid.value)
    if not handle: return ''
    try:
        path=C.create_unicode_buffer(32768); size=W.DWORD(len(path))
        return path.value if kernel.QueryFullProcessImageNameW(handle,0,path,C.byref(size)) else ''
    finally: kernel.CloseHandle(handle)

def find_video():
    found=[]
    def visit(hwnd,_):
        name=C.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd,name,256)
        title=C.create_unicode_buffer(256); user32.GetWindowTextW(hwnd,title,256)
        if (name.value.startswith('Qt') and title.value=='Phone - '+CONFIG['serial'] and
            user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd) and
            process_path(hwnd).lower()==CONFIG['gamescrcpy'].lower()):
            found.append(hwnd)
        return True
    user32.EnumWindows(ENUMPROC(visit),0)
    if len(found)!=1: raise RuntimeError('请保持唯一的 GameScrcpy 投屏窗口可见，退出最小化')
    return found[0]

FOCUS_OK='ok'; FOCUS_LEFT='left'
FOCUS_GRACE_TICKS=3; FOCUS_GRACE_SECONDS=0.5


def focus_verdict(foreground_hwnd,shield_hwnd,video_hwnd):
    """Pure judgement: is the foreground still inside the casting session?

    'ok'   - the foreground is our shield or the GameScrcpy video window. The
             shield is a transparent overrideredirect top-level window laid over
             the video, so Windows may refuse SetForegroundWindow(shield) and
             leave focus on the video window itself. That still means the user
             did NOT switch away, so the video window counts as inside. Treating
             it as 'left' was the misfire that kept pausing the adapter during
             enable.
    'left' - the foreground is any third window, or None (no foreground at all).
             Only this case may release the touches.

    Deliberately narrow: this is NOT "any window is ok". A third-party window and
    a missing hwnd both report 'left'.
    """
    if not foreground_hwnd: return FOCUS_LEFT
    if shield_hwnd and foreground_hwnd==shield_hwnd: return FOCUS_OK
    if video_hwnd and foreground_hwnd==video_hwnd: return FOCUS_OK
    return FOCUS_LEFT

class FocusWatch:
    """Short debounce so a momentary focus blip does not release the touches.

    The foreground window is sampled once per tick (~8ms), so a burst of
    'left' verdicts is confirmed only after FOCUS_GRACE_TICKS consecutive ones
    - which is also bounded by FOCUS_GRACE_SECONDS as a CEILING: a sustained
    switch away must release the touches no later than that, whatever the tick
    rate. The grace is capped at 0.5s, so safety is never traded away for
    stability. Any 'ok' verdict clears the streak immediately, and observe() is
    the ONLY way to reach the release path - an unconfirmed blip can never
    release the touches.
    """
    def __init__(self,ticks=FOCUS_GRACE_TICKS,seconds=FOCUS_GRACE_SECONDS):
        self.ticks=ticks; self.seconds=seconds; self.streak=0; self.since=None
    def reset(self):
        self.streak=0; self.since=None
    def observe(self,verdict,now):
        if verdict==FOCUS_OK:
            self.reset(); return False
        self.streak+=1
        if self.since is None: self.since=now
        # Tick count is the primary trigger; the elapsed-time ceiling guarantees
        # release even if ticks are so sparse that the count is slow to accrue.
        return self.streak>=self.ticks or now-self.since>=self.seconds

def antimicrox_processes():
    """Return [{'pid':int,'path':str,'windows':int,'visible':int}] for running AntiMicroX.

    Read natively so the gate still works when the UIA snapshot cannot see a
    tray/hidden main window (AutomationElement.RootElement omits hidden windows).
    """
    import subprocess
    ps=Path(CONFIG['powershell'])
    # $ErrorActionPreference must be reset here: pwsh exits non-zero when Get-Process
    # reports a missing name, which would otherwise crash the gate instead of
    # letting it conclude STOPPED.
    expression=("[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); "
                "$ErrorActionPreference='SilentlyContinue'; "
                "$rows=@(Get-Process -Name antimicrox -ErrorAction SilentlyContinue | "
                "ForEach-Object { [pscustomobject]@{pid=$_.Id;path=$_.Path;"
                "windows=$_.MainWindowHandle.ToInt64();visible=$($_.MainWindowHandle -ne 0)} }); "
                "if($rows.Count -eq 0){exit 0}; "
                "$rows | ConvertTo-Json -Compress -AsArray")
    p=run_command([str(ps),'-NoProfile','-Command',expression],capture_output=True,
        encoding='utf-8',errors='replace',creationflags=subprocess.CREATE_NO_WINDOW,timeout=15)
    text=p.stdout.strip()
    if p.returncode: raise RuntimeError('无法检查 AntiMicroX 进程；已停止启用以避免重复输入')
    if not text: return []
    rows=json.loads(text)
    if isinstance(rows,dict): rows=[rows]
    return rows

def antimicrox_selection():
    """Read the native AntiMicroX config combo via UIA. Returns (state,value).

    state is 'read' when the combo Box was reachable, 'unreadable' when the
    process is hidden so no window is enumerated, or 'no-process'.
    """
    import subprocess
    script=ROOT/'tools/phase2a_ui.ps1'
    ps=Path(CONFIG['powershell'])
    expression=("[Console]::InputEncoding=[Text.UTF8Encoding]::new($false); "
                "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); $OutputEncoding=[Console]::OutputEncoding; "
                f"& '{script}' -ProcessName antimicrox -Action snapshot | ConvertFrom-Json | "
                "Where-Object { $_.Id -like '*configBox' } | Select-Object -ExpandProperty Value")
    try:
        p=run_command([str(ps),'-NoProfile','-Command',expression],capture_output=True,
            encoding='utf-8',errors='replace',creationflags=subprocess.CREATE_NO_WINDOW,timeout=20)
    except subprocess.TimeoutExpired:
        return 'unreadable',''
    except OSError:
        return 'unreadable',''
    if p.returncode!=0: return 'unreadable',''
    value=p.stdout.strip()
    if not value: return 'unreadable',''
    return 'read',value

def antimicrox_ini_state():
    """Infer which profile AntiMicroX would have auto-loaded, from its settings.ini.

    AutoOpenLastProfile=1 makes AntiMicroX load LastSelected at startup; when that
    is empty (the state the launcher leaves behind) no profile is loaded at all.
    """
    ini=configparser.ConfigParser(interpolation=None,strict=False)
    try:
        if not ini.read(ANTIMICROX_INI,encoding='utf-8'): return dict(loaded=None,reason='未找到 antimicrox_settings.ini')
    except (OSError,configparser.Error) as ex:
        return dict(loaded=None,reason=f'读取 antimicrox_settings.ini 失败：{ex}')
    auto=ini.get('General','AutoOpenLastProfile',fallback='0').strip()
    last=''; config=''; name=''
    for section in ini.sections():
        if not section.startswith('Controllers'): continue
        for key,value in ini.items(section):
            value=value.strip()
            if key.endswith('LastSelected') and value: last=value
            elif key.endswith('ConfigFile1') and value: config=value
            elif key.endswith('ProfileName1') and value: name=value
    if auto not in ('1','true','True'): return dict(loaded=None,reason=f'AutoOpenLastProfile={auto or "0"}，启动时不自动载入方案')
    if last: return dict(loaded=last,reason=f'LastSelected={last}')
    if config:
        return dict(loaded=config,reason=f'LastSelected 为空，但 ConfigFile1 指向 {name or config}（启动时不会载入）')
    return dict(loaded=None,reason='LastSelected 为空且无 ConfigFile1，启动时不会载入任何方案')

def amgp_injects_mouse(path):
    """True when an .amgp maps any stick onto mouse movement (duplicate input)."""
    import xml.etree.ElementTree as ET
    try: root=ET.parse(path).getroot()
    except (OSError,ET.ParseError): return None
    for node in root.iter():
        tag=node.tag.split('}')[-1]
        if tag in ('stick','stickbutton','trigger','button','dpad','dpadbutton'):
            for mode in node.iter('mode'):
                if (mode.text or '').strip() in ('mousemovement','mousebuttons'): return True
    return False

def resolve_selected_profile(name):
    """Resolve the AntiMicroX combo selection to the .amgp file actually in use.

    The UIA configBox exposes only a display name. That name is NOT unique: the
    merged profile and the original stub share the same <profilename>, so matching
    on it alone would pick the wrong file and misjudge the gate. settings.ini is
    the authoritative record of which FILE is loaded, so it wins; the name is only
    used as a fallback when settings.ini tells us nothing.
    Returns a path string, or None when it cannot be resolved.
    """
    raw=(name or '').strip()
    # 1) A full path in the combo is already authoritative.
    if raw.lower().endswith('.amgp') and Path(raw).exists():
        return raw
    # 2) settings.ini records the file AntiMicroX actually loaded - authoritative.
    ini=antimicrox_ini_state()
    from_ini=''
    try:
        text=ANTIMICROX_INI.read_text(encoding='utf-8-sig')
        for line in text.splitlines():
            if '=' not in line: continue
            key,_,value=line.partition('=')
            key=key.strip(); value=value.strip()
            if not value: continue
            if key.endswith('ConfigFile1') or key.endswith('LastSelected'):
                if Path(value).exists():
                    from_ini=value
                    if key.endswith('ConfigFile1'): break
    except OSError:
        pass
    if from_ini:
        return from_ini
    loaded=ini.get('loaded') or ''
    if loaded and Path(loaded).exists():
        return loaded
    # 3) Last resort: match the display name against each file's <profilename>.
    if not raw or raw=='<新>':
        return None
    folders={PHASE/'profiles/number-bridge-20261015-203453',
             PHASE/'profiles/rightstick-merged-20261015'}
    for folder in folders:
        for path in sorted(folder.glob('*.amgp')):
            try: head=path.read_text(encoding='utf-8',errors='replace')[:2000]
            except OSError: continue
            if f'<profilename>{raw}</profilename>' in head:
                return str(path)
    return None

def antimicrox_gate():
    """The direct adapter owns buttons and both sticks; keyboard slots also conflict."""
    from input_ownership import decide,inspect_profile
    processes=antimicrox_processes()
    selection=antimicrox_selection() if processes else ("no-process","")
    blank=PHASE/"profiles/blank-no-keys/blank.amgp"
    return decide(processes,selection,inspect_profile(blank))

def antimicrox_clear():
    # Native current selection must be blank OR provably non-injecting. The launcher
    # unloads it before use; this independent read protects later launches from
    # duplicate input, including the tray/hidden case where UIA sees no window.
    return antimicrox_gate()['allow']

def antimicrox_gate_message(decision):
    """One-line, actionable refusal text carrying PID, visibility and evidence."""
    return (f"AntiMicroX 阻止启用：{decision['reason']}。"
            f"（PID={decision['pid']}，隐藏窗口={'是' if decision['hidden'] else '否'}；{decision['detail']}）")

def current_profile():
    from profile_store import ProfileStore
    store=ProfileStore(ROOT,LIVE.parent)
    if store.path.exists():return store.active_runtime()
    ini=configparser.ConfigParser(interpolation=None,strict=False)
    ini.read(USER_INI,encoding='utf-8')
    if ini.get(CONFIG['serial'].replace(':','_'),'KeyMap',fallback='')!=LIVE.name:
        raise RuntimeError('请先选择已校准的超燃竞技场手柄方案')
    data=LIVE.read_bytes()
    return json.loads(data),hashlib.sha256(data).hexdigest()

class Worker:
    def __init__(self,events):
        self.events=events; self.stop=threading.Event(); self.lock=threading.Lock()
        self.latest={}; self.updated=time.monotonic(); self.started=time.monotonic()
        self.snapshots=TouchQueue()
        self.frames=0; self.latency=0.0
        self.reset_pending=False
        self.thread=threading.Thread(target=self.run,daemon=True)
        self.thread.start()
    def update(self,points,active=True):
        with self.lock:
            self.latest=dict(points); self.updated=time.monotonic()
            self.snapshots.offer(points,self.updated,active=active and not self.reset_pending)
    def acknowledge_reset(self):
        with self.lock:
            self.latest={};self.reset_pending=False
            self.snapshots.offer({},time.monotonic(),active=False)
    def run(self):
        transport=None
        COMMAND_CONTEXT.cancel=self.stop
        try:
            # UI Automation must run off the Tk thread; its root enumeration may
            # query our own visible window and requires that thread to keep pumping.
            decision=antimicrox_gate()
            if not decision['allow']:
                raise RuntimeError(antimicrox_gate_message(decision))
            import subprocess
            surface_result=run_command([CONFIG['powershell'],
                '-NoProfile','-File',str(ROOT/'tools/analog/video_surface.ps1'),
                '-VideoHandle',str(find_video())],capture_output=True,encoding='utf-8',errors='replace',
                timeout=8,creationflags=subprocess.CREATE_NO_WINDOW)
            if surface_result.returncode:raise RuntimeError('无法确认鼠标投屏区域：'+surface_result.stderr.strip()[:180])
            surface=int(json.loads(surface_result.stdout)['handle'])
            case='gui-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f')
            transport=Transport(case); transport.start()
            self.updated=time.monotonic()
            self.events.put(('connected',dict(transport.info,surface=surface)))
            previous=None; last_sent=0
            while not self.stop.is_set():
                start=time.monotonic()
                with self.lock:
                    points={} if self.reset_pending else self.snapshots.take(start)
                    force_release=self.snapshots.release_barrier
                    age=start-self.updated
                # Watchdog for a genuinely wedged UI thread. The old 200ms limit was
                # tight enough that ordinary scheduler hiccups (window drag, a brief
                # GC pause, another process hogging the CPU) tripped it and tore the
                # session down mid-play. Allow a generous grace window instead: a
                # stuck UI is still caught, but transient stalls no longer kill play.
                if age>WATCHDOG_SECONDS:
                    raise RuntimeError('界面更新中断，已释放触点并暂停')
                if force_release or frame_due(points,previous,start,last_sent):
                    try:transport.frame(points)
                    except NeutralRequired:
                        with self.lock:
                            self.reset_pending=True;self.latest={}
                            self.snapshots.offer({},time.monotonic(),active=False)
                        self.events.put(('touch_reset',None))
                        previous=None;continue
                    self.frames+=1
                    with self.lock:self.snapshots.mark_sent(points,time.monotonic())
                    self.latency=(time.monotonic()-start)*1000
                    previous=points; last_sent=start
                self.stop.wait(max(0,1/120-(time.monotonic()-start)))
        except Exception as ex:
            self.events.put(('error',str(ex)))
        finally:
            COMMAND_CONTEXT.cancel=None
            try:
                if transport: transport.close()
            except Exception as ex:
                self.events.put(('error','触控通道清理失败：'+str(ex)))
            finally:
                # A failed release/ACK must never leave the UI holding a dead worker.
                self.events.put(('closed',None))

class App:
    def __init__(self):
        self.root=tk.Tk(); self.root.title('双摇杆模拟触控 · 超燃竞技场样本')
        self.root.geometry('620x480+20+100'); self.root.configure(bg='#122333')
        self.events=queue.Queue(); self.worker=None; self.mapper=None; self.armed=False
        self.connecting=False; self.neutral_wait=False; self.profile_sha=None
        self.last_status=0; self.last_profile_check=0; self.history=[]; self.last_buttons=[]
        self.control_path=PHASE/'analog/control-request.json'
        self.last_control_check=0; self.last_control_id=None
        try: self.last_control_id=json.loads(self.control_path.read_text(encoding='utf-8')).get('id')
        except (OSError,ValueError): pass
        self.state=None; self.points={}; self.pad=XInput(); self.shield=None
        self.mouse=MouseChannels();self.mouse_rect=None;self.last_surface_check=0
        self.focus=FocusWatch()
        self.settings=json.loads((PHASE/'analog/settings.json').read_text(encoding='utf-8'))
        self.pad.right_center=tuple(self.settings.get('right_center',(0,0)))
        # When False (default) losing focus only SUSPENDS touches; the session keeps
        # running and resumes on its own. Set true in settings.json to restore the
        # old behaviour of pausing outright when focus leaves the casting window.
        self.pause_on_focus_loss=bool(self.settings.get('pause_on_focus_loss',False))
        self.focus_suspended=False
        self.resume_checking=False; self.session_token=0
        # Edge detection for the Start button toggle.
        self.start_was_down=False
        self.auto_foreground=bool(self.settings.get('auto_on_foreground',True))
        self.manual_pause=False;self.next_auto_attempt=0;self.last_auto_check=0
        self.recovery_pending=False;self.reconnects=0;self.last_error=''
        self.touch_resets=0
        self.last_draw=0
        self.status=tk.StringVar(value='等待投屏前台 · 自动控制' if self.auto_foreground else '已暂停')
        self.detail=tk.StringVar(value='左：连续方向与幅度；右：细微转向 / 按住技能时瞄准')
        ttk.Label(self.root,text='双摇杆模拟触控',font=('Microsoft YaHei UI',17,'bold')).pack(fill='x',padx=18,pady=(16,8))
        ttk.Label(self.root,textvariable=self.status,font=('Microsoft YaHei UI',11),wraplength=580).pack(fill='x',padx=18)
        self.canvas=tk.Canvas(self.root,width=580,height=190,bg='#122333',highlightthickness=0)
        self.canvas.pack(padx=15,pady=5)
        ttk.Label(self.root,textvariable=self.detail,wraplength=580).pack(fill='x',padx=18)
        ttk.Label(self.root,text='A/B/X/Y＝1/2/3/4   LB/RB＝5/6   LT/RT＝7/8\n↑/↓/←/→＝9/0/-/=；适配器直接发送触控，不发送这些键。',wraplength=580).pack(fill='x',padx=18,pady=8)
        buttons=ttk.Frame(self.root); buttons.pack(fill='x',padx=18,pady=8)
        self.start_button=ttk.Button(buttons,text='恢复自动控制',command=self.start); self.start_button.pack(side='left')
        ttk.Button(buttons,text='暂停自动控制',command=lambda:self.pause('手动暂停',manual=True)).pack(side='left',padx=8)
        ttk.Button(buttons,text='打开运行记录',command=lambda:__import__('os').startfile(PHASE/'analog')).pack(side='right')
        ttk.Label(self.root,text='投屏前台自动控制；切出释放，切回按当前摇杆方向继续。\n切回时已按住的按钮须松开再按；鼠标可同时点击和拖动。',wraplength=580).pack(fill='x',padx=18,pady=5)
        self.root.protocol('WM_DELETE_WINDOW',self.root.withdraw)
        self.root.after(8,self.tick)
    def start(self):
        self.manual_pause=False
        if self.worker or self.connecting: return
        try:
            self.video=find_video()
            profile,self.profile_sha=current_profile()
            self.mouse.configure(profile.get('_adapter',{}).get('controls',[]))
            self.settings=json.loads((PHASE/'analog/settings.json').read_text(encoding='utf-8'))
            self.pad.right_center=tuple(self.settings.get('right_center',(0,0)))
            # Startup remains paused until the connection and neutral gate complete.
            self.profile=profile; self.connecting=True; self.start_button.configure(state='disabled')
            self.session_token+=1; self.resume_checking=False; self.focus_suspended=False
            # A fresh enable must not inherit a stale 'left' streak from before.
            self.focus.reset()
            self.status.set('建立本地触控通道中……')
            if self.recovery_pending:self.reconnects+=1
            self.worker=Worker(self.events)
        except Exception as ex:
            self.pause(str(ex))
    def show_shield(self):
        shield=tk.Toplevel(self.root); shield.title('GameControlProfiles 手柄输入接管'); shield.overrideredirect(True)
        shield.withdraw()
        shield.configure(bg='black'); shield.attributes('-alpha',.035)
        shield.attributes('-topmost',True)
        self.shield=shield;self.mouse.reset();self.mouse_rect=None
        self.update_shield_bounds()
        # Clicking the casting area must NOT pause any more: reaching for the phone
        # view (or clicking Enable while it holds focus) fired the shield's press
        # handler and killed the session before it could ever run. Esc and leaving
        # the window remain the explicit ways to pause.
        shield.bind('<ButtonPress-1>',lambda event:self.mouse_event('down',event))
        shield.bind('<B1-Motion>',lambda event:self.mouse_event('move',event))
        shield.bind('<ButtonRelease-1>',lambda event:self.mouse_event('up',event))
        shield.bind('<ButtonPress-2>',lambda event:'break')
        shield.bind('<ButtonPress-3>',lambda event:self.mouse_event('down',event,'right'))
        shield.bind('<B3-Motion>',lambda event:self.mouse_event('move',event,'right'))
        shield.bind('<ButtonRelease-3>',lambda event:self.mouse_event('up',event,'right'))
        shield.bind('<KeyPress-Escape>',lambda event:self.pause('Esc 暂停',manual=True))
        # All other key presses belong to this shield while active, not GameScrcpy.
        shield.bind('<KeyPress>',lambda event:'break')
        shield.update_idletasks()
        self.shield=shield
        self.shield_hwnd=user32.GetAncestor(shield.winfo_id(),2)
        # Keep the control panel out of the game view; its taskbar entry stays usable.
        root_hwnd=user32.GetAncestor(self.root.winfo_id(),2)
        user32.SetWindowPos(root_hwnd,W.HWND(1),0,0,0,0,0x13)
        # A connection may finish after the user has switched to another app.
        # Only activate over a still-foreground projection, never steal late focus.
        if focus_verdict(user32.GetForegroundWindow(),self.shield_hwnd,self.video)==FOCUS_OK:
            self.shield_delivery(True)
        else:self.focus_suspended=True
    def update_shield_bounds(self):
        rect=W.RECT();surface=self.video_surface
        if not user32.IsWindow(surface) or user32.GetAncestor(surface,2)!=self.video:
            raise RuntimeError('投屏画面区域变化，请重新启用')
        if not user32.GetWindowRect(surface,C.byref(rect)):raise RuntimeError('投屏窗口已关闭')
        bounds=fit_rect((rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top),self.mapper.width,self.mapper.height)
        if bounds[2]<20 or bounds[3]<20:raise RuntimeError('投屏画面区域不可用')
        if bounds!=self.mouse_rect:
            self.mouse.reset();self.mouse_rect=bounds
            x,y,w,h=bounds;self.shield.geometry(f'{w}x{h}+{x}+{y}')
    def mouse_event(self,kind,event,button='left'):
        if self.armed and not self.focus_suspended and not self.neutral_wait and self.mouse_rect:
            self.mouse.event(kind,event.x,event.y,*self.mouse_rect[2:],button=button)
        return 'break'
    def shield_delivery(self,active):
        if not self.shield: return
        if active:
            self.shield.deiconify(); self.shield.attributes('-topmost',True)
            self.shield.lift(); self.shield.focus_force()
        else:
            # A topmost transparent input shield must not intercept other apps,
            # including the console's Pause button, after focus leaves the video.
            self.shield.attributes('-topmost',False); self.shield.withdraw()
    def pause(self,reason,manual=False):
        if manual:self.manual_pause=True
        self.recovery_pending=not self.manual_pause and self.auto_foreground
        if self.recovery_pending:self.last_error=reason
        try:
            with (STATUS.parent/'recovery-events.jsonl').open('a',encoding='utf-8') as log:
                log.write(json.dumps(dict(at=datetime.now().isoformat(),reason=reason,
                    manual_pause=self.manual_pause,recovery_pending=self.recovery_pending,
                    foreground=int(user32.GetForegroundWindow() or 0),
                    video=int(getattr(self,'video',0) or 0),shield=int(getattr(self,'shield_hwnd',0) or 0)),ensure_ascii=False)+'\n')
        except OSError:pass
        self.next_auto_attempt=time.monotonic()+1
        self.mouse.reset()
        self.session_token+=1; self.resume_checking=False; self.focus_suspended=False
        self.armed=False; self.connecting=False; self.points={}; self.neutral_wait=False
        # Paused input must not keep intercepting the user's desktop clicks while
        # the transport finishes closing. The Android watchdog releases stale touches.
        if self.shield:
            # Withdrawing the active shield otherwise returns focus to the app
            # that preceded it, even while the video remains visually on top.
            # Hand focus back only while OUR shield is foreground. Never activate
            # the video after the user has already switched to another app.
            if (user32.GetForegroundWindow()==self.shield_hwnd and
                user32.IsWindow(self.video) and not user32.IsIconic(self.video)):
                user32.SetForegroundWindow(self.video)
            self.shield_delivery(False)
        if self.worker:
            self.worker.update({},active=False); self.worker.stop.set()
        if self.mapper: self.mapper.reset()
        # Destroy the withdrawn shield after the worker has finished closing.
        self.status.set(('自动重连中 · ' if self.recovery_pending else '已暂停 · ')+reason)
        self.last_reason=reason
        if not self.worker: self.finish_pause()
    def finish_pause(self):
        if self.shield:
            self.shield.destroy(); self.shield=None
        self.start_button.configure(state='normal')
    def tick(self):
        now=time.monotonic()
        if now-self.last_control_check>.20:
            self.last_control_check=now
            try:
                request=json.loads(self.control_path.read_text(encoding='utf-8'))
                if request.get('id')!=self.last_control_id:
                    self.last_control_id=request.get('id')
                    if 0<=time.time()-float(request.get('at',0))<=8:
                        if request.get('command')=='pause': self.pause('控制台暂停',manual=True)
                        elif request.get('command')=='start':
                            if self.auto_foreground:
                                self.manual_pause=False;self.next_auto_attempt=0
                                if not self.armed:self.status.set('等待投屏前台 · 自动控制')
                            else:self.start()
                        elif request.get('command')=='show':
                            self.root.deiconify();user32.SetForegroundWindow(user32.GetAncestor(self.root.winfo_id(),2))
                        elif request.get('command')=='quit':self.close();return
            except (OSError,ValueError,TypeError): pass
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='connected':
                    if not self.connecting:
                        self.worker.stop.set(); continue
                    self.mapper=Mapper(self.profile,value['width'],value['height'],self.settings)
                    self.video_surface=value.get('surface',self.video)
                    self.show_shield(); self.connecting=False; self.armed=True
                    self.recovery_pending=False
                    self.neutral_wait=True; self.status.set('连接已就绪 · 准备恢复输入')
                    self.enable_at=now+.20
                elif kind=='error': self.pause(str(value))
                elif kind=='closed':
                    self.worker=None; self.armed=False; self.connecting=False
                    self.finish_pause()
                elif kind=='touch_reset' and self.armed:
                    self.mapper.reset();self.mouse.reset();self.points={}
                    self.neutral_wait=True;self.enable_at=now+.10;self.touch_resets+=1
                    self.worker.acknowledge_reset()
                    self.status.set('通信已恢复 · 准备恢复输入')
                elif kind=='ownership_resume':
                    token,decision=value
                    if token==self.session_token and self.armed:
                        self.resume_checking=False
                        if not decision['allow']: self.pause(antimicrox_gate_message(decision))
                        elif focus_verdict(user32.GetForegroundWindow(),self.shield_hwnd,self.video)==FOCUS_OK:
                            self.focus_suspended=False; self.mapper.reset()
                            self.neutral_wait=True; self.enable_at=now+.10
                            self.shield_delivery(True)
                            self.status.set('已切回投屏 · 准备恢复输入')
        except queue.Empty: pass
        except Exception as ex: self.pause(str(ex))
        was_connected=bool(self.state)
        self.state=self.pad.read()
        input_state=self.state or dict(left=(0,0),right=(0,0),buttons=[])
        if self.armed and was_connected!=bool(self.state):
            # Release only controller fingers; keep mouse gestures and transport.
            # A newly connected controller's held buttons need a fresh press.
            self.mapper.guard_resume(input_state)
        if input_state['buttons']!=self.last_buttons:
            self.last_buttons=input_state['buttons']
            self.history.append(dict(at=datetime.now().isoformat(),buttons=self.last_buttons))
            self.history=self.history[-40:]
        # Start button toggles the session: press to enable, press again to pause.
        # This is the single explicit control; nothing else pauses automatically.
        # Edge-triggered on the press transition so holding it does not repeat.
        start_down=bool(self.state) and 'START' in self.state['buttons']
        if not self.auto_foreground and start_down and not self.start_was_down:
            if self.armed or self.connecting: self.pause('手柄 Start 键暂停')
            else: self.start()
        self.start_was_down=start_down
        if self.auto_foreground and not self.manual_pause and not self.worker and not self.connecting and now>=self.next_auto_attempt and now-self.last_auto_check>.2:
            self.last_auto_check=now
            try:
                candidate=find_video()
                if user32.GetForegroundWindow()==candidate:
                    self.next_auto_attempt=now+4;self.start()
            except Exception:pass
        if self.armed:
            try:
                if not user32.IsWindow(self.video) or user32.IsIconic(self.video): raise RuntimeError('投屏不可见')
                if now-self.last_profile_check>.5:
                    _,sha=current_profile(); self.last_profile_check=now
                    if sha!=self.profile_sha: raise RuntimeError('键位已修改，请重新启用以读取新坐标')
                if self.shield and now-self.last_surface_check>.2:
                    self.last_surface_check=now;self.update_shield_bounds()
                # Focus is NOT used to end the session any more. Losing focus only
                # SUSPENDS delivery: no finger is left pressed on the phone, and
                # delivery resumes by itself when the casting window regains focus.
                # Start (or the Pause button, or Esc) is the explicit way to stop.
                verdict=focus_verdict(user32.GetForegroundWindow(),self.shield_hwnd,self.video)
                outside=self.focus.observe(verdict,now)
                if outside:
                    if not self.focus_suspended:
                        self.focus_suspended=True
                        self.mapper.reset(); self.neutral_wait=True
                        self.mouse.reset()
                        self.shield_delivery(False)
                        self.status.set('已暂停发送 · 焦点不在投屏，切回后自动恢复')
                    self.points={}
                elif self.focus_suspended:
                    self.points={}
                    if not self.resume_checking and verdict==FOCUS_OK:
                        self.resume_checking=True; token=self.session_token
                        def check_owner(check_token=token):
                            try: decision=antimicrox_gate()
                            except Exception as ex:
                                decision=dict(allow=False,reason=str(ex),pid=None,hidden=False,detail='恢复发送前检查失败')
                            self.events.put(('ownership_resume',(check_token,decision)))
                        threading.Thread(target=check_owner,daemon=True).start()
                elif self.neutral_wait:
                    self.points={}
                    if now>self.enable_at:
                        self.mapper.guard_resume(input_state)
                        self.neutral_wait=False; self.status.set('运行中 · 投屏前台自动控制' if self.auto_foreground else '运行中 · Start 键暂停')
                else:self.points=merge(self.mapper.frame(input_state,now),self.mouse.frame(now))
            except Exception as ex: self.pause(str(ex))
        if self.worker:self.worker.update(self.points if self.armed else {},active=bool(self.armed and not self.focus_suspended and not self.neutral_wait))
        if now-self.last_draw>=1/30 and self.root.state()=='normal':
            self.draw();self.last_draw=now
        if now-self.last_status>.5:
            self.last_status=now
            state=dict(pid=__import__('os').getpid(),control_request_id=self.last_control_id,channel_active=bool(self.worker),status=self.status.get(),armed=self.armed,neutral_wait=self.neutral_wait,
                       focus_suspended=self.focus_suspended,delivery_enabled=bool(self.armed and not self.focus_suspended and not self.neutral_wait),
                       auto_on_foreground=self.auto_foreground,manual_pause=self.manual_pause,
                       recovery_pending=self.recovery_pending,reconnects=self.reconnects,last_error=self.last_error,
                       touch_resets=self.touch_resets,
                       resume_blocked_buttons=sorted(self.mapper.blocked_buttons) if self.mapper else [],
                       pending_touch_edges=len(self.worker.snapshots.edges) if self.worker else 0,
                       expired_touch_edges=self.worker.snapshots.expired if self.worker else 0,
                       foreground_hwnd=int(user32.GetForegroundWindow() or 0),video_hwnd=int(getattr(self,'video',0) or 0),
                       mouse_events=self.mouse.received,mouse_active=self.mouse.point is not None,mouse_rect=self.mouse_rect,
                       raw=self.state,points=self.points,aim=self.mapper.last_aim if self.mapper else None,
                       frames=self.worker.frames if self.worker else 0,
                       last_round_trip_ms=round(self.worker.latency,2) if self.worker else None,
                       profile_sha256=self.profile_sha,profile_name=self.profile.get('_adapter',{}).get('name','超燃竞技场-三技能') if hasattr(self,'profile') else None,keyboard_synthesis=False,mouse_synthesis=False,
                       recent_buttons=self.history,at=datetime.now().isoformat())
            try:
                temporary=STATUS.with_suffix('.tmp'); temporary.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
                temporary.replace(STATUS)
            except OSError:
                # A Windows reader can briefly hold the destination without delete
                # sharing. Retry next heartbeat; never terminate the input tick.
                self.last_status=now-.4
        self.root.after(8,self.tick)
    def draw(self):
        self.canvas.delete('all')
        for label,axis,cx,color in [('左摇杆','left',145,'#89dfb4'),('右摇杆','right',435,'#89c6ff')]:
            cy=88; radius=58
            self.canvas.create_oval(cx-radius,cy-radius,cx+radius,cy+radius,outline=color,width=2)
            self.canvas.create_line(cx-radius,cy,cx+radius,cy,fill='#355268')
            self.canvas.create_line(cx,cy-radius,cx,cy+radius,fill='#355268')
            x,y=self.state[axis] if self.state else (0,0)
            px,py=cx+x*radius,cy+y*radius
            self.canvas.create_oval(px-7,py-7,px+7,py+7,fill=color,outline='')
            self.canvas.create_text(cx,cy+82,text=f'{label}  {min(1,math.hypot(x,y))*100:.0f}%',fill=color,font=('Microsoft YaHei UI',11))
        if self.state:
            pad=f"XInput {self.state['index']+1} · "+(' / '.join(self.state['buttons']) or '所有按钮已松开')
        else: pad='未连接 XInput 手柄'
        self.canvas.create_text(290,12,text=pad,fill='#e6f0f7',font=('Microsoft YaHei UI',10))
    def close(self):
        self.pause('关闭适配器')
        if self.worker:
            self.worker.thread.join(timeout=2)
        try:
            STATUS.write_text(json.dumps(dict(pid=__import__('os').getpid(),status='已关闭',armed=False,
                control_request_id=self.last_control_id,at=datetime.now().isoformat()),ensure_ascii=False),encoding='utf-8')
        except OSError:pass
        self.root.destroy()

if __name__=='__main__':
    import sys
    if '--verify-package' in sys.argv:
        from package_probe import run
        run()
        sys.exit(0)
    import os
    # Process-scoped DPI awareness: keep the shield in physical pixels.
    try: user32.SetProcessDpiAwarenessContext(C.c_void_p(-4))
    except (AttributeError,OSError): pass
    mutex=C.WinDLL('kernel32',use_last_error=True)
    mutex.CreateMutexW.argtypes=[C.c_void_p,W.BOOL,W.LPCWSTR]
    mutex.CreateMutexW.restype=W.HANDLE
    handle=mutex.CreateMutexW(None,False,'Local\\GameControlProfiles_Analog2B')
    if C.get_last_error()!=183:
        app=App()
        if '--paused' in __import__('sys').argv:app.pause('保持更新前的手动暂停',manual=True)
        if '--hidden' in __import__('sys').argv:app.root.withdraw()
        if '--start' in __import__('sys').argv:
            app.root.after(300,app.start)
        app.root.mainloop()
