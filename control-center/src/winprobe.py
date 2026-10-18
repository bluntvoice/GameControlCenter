"""Read-only Windows process/window/controller observations."""
import ctypes as C
from ctypes import wintypes as W
from pathlib import Path

kernel=C.WinDLL('kernel32',use_last_error=True)
user=C.WinDLL('user32',use_last_error=True)
class Entry(C.Structure):
    _fields_=[('size',W.DWORD),('usage',W.DWORD),('pid',W.DWORD),('heap',C.c_size_t),
              ('module',W.DWORD),('threads',W.DWORD),('parent',W.DWORD),
              ('priority',W.LONG),('flags',W.DWORD),('exe',W.WCHAR*260)]
kernel.CreateToolhelp32Snapshot.argtypes=[W.DWORD,W.DWORD]; kernel.CreateToolhelp32Snapshot.restype=W.HANDLE
kernel.Process32FirstW.argtypes=[W.HANDLE,C.POINTER(Entry)]
kernel.Process32NextW.argtypes=[W.HANDLE,C.POINTER(Entry)]
kernel.CloseHandle.argtypes=[W.HANDLE]
kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD]; kernel.OpenProcess.restype=W.HANDLE
kernel.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,C.POINTER(W.DWORD)]
kernel.GetExitCodeProcess.argtypes=[W.HANDLE,C.POINTER(W.DWORD)]
kernel.GetProcessTimes.argtypes=[W.HANDLE,C.POINTER(W.FILETIME),C.POINTER(W.FILETIME),C.POINTER(W.FILETIME),C.POINTER(W.FILETIME)]
ENUM=C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
user.EnumWindows.argtypes=[ENUM,W.LPARAM]
user.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
user.GetWindowTextW.argtypes=[W.HWND,W.LPWSTR,C.c_int]
user.IsWindowVisible.argtypes=[W.HWND]
user.IsIconic.argtypes=[W.HWND]
user.ShowWindow.argtypes=[W.HWND,C.c_int]
user.SetForegroundWindow.argtypes=[W.HWND]
user.SendMessageTimeoutW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM,W.UINT,W.UINT,C.POINTER(C.c_size_t)]
user.SendMessageTimeoutW.restype=C.c_ssize_t

class Process:
    def __init__(self,pid):
        self.pid=pid; self.handle=kernel.OpenProcess(0x1000,False,pid)
        self.path=''; self.created=0
        if self.handle:
            text=C.create_unicode_buffer(32768); length=W.DWORD(len(text))
            if kernel.QueryFullProcessImageNameW(self.handle,0,text,C.byref(length)): self.path=text.value
            times=[W.FILETIME() for _ in range(4)]
            if kernel.GetProcessTimes(self.handle,*[C.byref(t) for t in times]):
                self.created=((times[0].dwHighDateTime<<32)|times[0].dwLowDateTime)/1e7-11644473600
    def exit_code(self):
        code=W.DWORD()
        if not self.handle or not kernel.GetExitCodeProcess(self.handle,C.byref(code)): return None
        return code.value
    def alive(self): return self.exit_code()==259
    def close(self):
        if self.handle: kernel.CloseHandle(self.handle); self.handle=None
    def __del__(self): self.close()

def process_list(names):
    handle=kernel.CreateToolhelp32Snapshot(2,0)
    if handle==W.HANDLE(-1).value: raise C.WinError(C.get_last_error())
    result=[]
    try:
        item=Entry(); item.size=C.sizeof(Entry)
        valid=kernel.Process32FirstW(handle,C.byref(item))
        while valid:
            if item.exe.lower() in names: result.append((item.pid,item.exe))
            valid=kernel.Process32NextW(handle,C.byref(item))
    finally: kernel.CloseHandle(handle)
    return result

def windows():
    result=[]
    def visit(hwnd,_):
        pid=W.DWORD(); user.GetWindowThreadProcessId(hwnd,C.byref(pid))
        title=C.create_unicode_buffer(512); user.GetWindowTextW(hwnd,title,len(title))
        if title.value: result.append(dict(hwnd=hwnd,pid=pid.value,title=title.value,
                                          visible=bool(user.IsWindowVisible(hwnd)),minimized=bool(user.IsIconic(hwnd))))
        return True
    user.EnumWindows(ENUM(visit),0)
    return result

def responds(hwnd,timeout=180):
    output=C.c_size_t()
    return bool(user.SendMessageTimeoutW(hwnd,0,0,0,2,timeout,C.byref(output)))

def show(hwnd):
    user.ShowWindow(hwnd,9); return bool(user.SetForegroundWindow(hwnd))

class MonitorInfo(C.Structure):
    _fields_=[('size',W.DWORD),('monitor',W.RECT),('work',W.RECT),('flags',W.DWORD)]

user.GetWindowRect.argtypes=[W.HWND,C.POINTER(W.RECT)]
user.GetClientRect.argtypes=[W.HWND,C.POINTER(W.RECT)]
user.IsZoomed.argtypes=[W.HWND]
user.MonitorFromRect.argtypes=[C.POINTER(W.RECT),W.DWORD];user.MonitorFromRect.restype=W.HANDLE
user.GetMonitorInfoW.argtypes=[W.HANDLE,C.POINTER(MonitorInfo)]
user.SetWindowPos.argtypes=[W.HWND,W.HWND,C.c_int,C.c_int,C.c_int,C.c_int,W.UINT]
user.GetDpiForWindow.argtypes=[W.HWND];user.GetDpiForWindow.restype=W.UINT

def video_geometry(hwnd,saved=None):
    rect=W.RECT();client=W.RECT()
    if not user.GetWindowRect(hwnd,C.byref(rect)) or not user.GetClientRect(hwnd,C.byref(client)):return None
    if rect.right<=rect.left or rect.bottom<=rect.top or client.right<=0 or client.bottom<=0:return None
    info=MonitorInfo();info.size=C.sizeof(info)
    if not user.GetMonitorInfoW(user.MonitorFromRect(C.byref(rect),2),C.byref(info)):return None
    m=info.monitor
    fullscreen=rect.left<=m.left+2 and rect.top<=m.top+2 and rect.right>=m.right-2 and rect.bottom>=m.bottom-2
    normal=bool(user.IsWindowVisible(hwnd)) and not (user.IsIconic(hwnd) or user.IsZoomed(hwnd) or fullscreen)
    dpi=user.GetDpiForWindow(hwnd) or 96
    if saved:
        sx,sy,sw,sh=saved['rect'];target=W.RECT(round(sx),round(sy),round(sx+sw),round(sy+sh))
        monitor=user.MonitorFromRect(C.byref(target),2)
        if user.GetMonitorInfoW(monitor,C.byref(info)):
            try:
                dx=W.UINT();dy=W.UINT();shcore=C.WinDLL('shcore')
                shcore.GetDpiForMonitor.argtypes=[W.HANDLE,C.c_int,C.POINTER(W.UINT),C.POINTER(W.UINT)]
                if shcore.GetDpiForMonitor(monitor,0,C.byref(dx),C.byref(dy))==0:dpi=dx.value
            except (OSError,AttributeError):pass
    w=info.work
    return dict(rect=[rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top],
                client=[client.right,client.bottom],work=[w.left,w.top,w.right-w.left,w.bottom-w.top],dpi=dpi,normal=normal)

def restore_video_geometry(hwnd,rect):
    # NOZORDER | NOACTIVATE: restore without stealing focus or making it topmost.
    return bool(user.SetWindowPos(hwnd,None,*rect,0x14))

class Pad(C.Structure):
    _fields_=[('buttons',W.WORD),('lt',C.c_ubyte),('rt',C.c_ubyte),
              ('lx',C.c_short),('ly',C.c_short),('rx',C.c_short),('ry',C.c_short)]
class PadState(C.Structure):
    _fields_=[('packet',W.DWORD),('pad',Pad)]
class Controller:
    def __init__(self):
        self.dll=C.WinDLL('xinput1_4.dll')
        self.dll.XInputGetState.argtypes=[W.DWORD,C.POINTER(PadState)]
        self.dll.XInputGetState.restype=W.DWORD
    def read(self):
        found=[]
        for index in range(4):
            state=PadState()
            if self.dll.XInputGetState(index,C.byref(state))==0:
                p=state.pad
                found.append(dict(index=index+1,left=[p.lx/32768,-p.ly/32768],
                                  right=[p.rx/32768,-p.ry/32768],buttons=p.buttons,
                                  triggers=[p.lt,p.rt]))
        return found
