"""Windows notification-area icon, handled on Tk's existing UI message thread."""
import ctypes as C
from ctypes import wintypes as W
import os
import queue

user=C.WinDLL('user32',use_last_error=True);shell=C.WinDLL('shell32',use_last_error=True);kernel=C.WinDLL('kernel32',use_last_error=True)
PROC=C.WINFUNCTYPE(C.c_ssize_t,W.HWND,W.UINT,W.WPARAM,W.LPARAM)
class WindowClass(C.Structure):
    _fields_=[('style',W.UINT),('proc',PROC),('cls_extra',C.c_int),('wnd_extra',C.c_int),('instance',W.HINSTANCE),('icon',W.HICON),('cursor',W.HANDLE),('background',W.HBRUSH),('menu',W.LPCWSTR),('name',W.LPCWSTR)]
class IconData(C.Structure):
    _fields_=[('size',W.DWORD),('hwnd',W.HWND),('ident',W.UINT),('flags',W.UINT),('message',W.UINT),('icon',W.HICON),('tip',W.WCHAR*128),('state',W.DWORD),('mask',W.DWORD),('info',W.WCHAR*256),('version',W.UINT),('title',W.WCHAR*64),('info_flags',W.DWORD),('guid',C.c_ubyte*16),('balloon',W.HICON)]
kernel.GetModuleHandleW.argtypes=[W.LPCWSTR];kernel.GetModuleHandleW.restype=W.HMODULE
user.RegisterClassW.argtypes=[C.POINTER(WindowClass)]
user.CreateWindowExW.argtypes=[W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,C.c_int,C.c_int,C.c_int,C.c_int,W.HWND,W.HMENU,W.HINSTANCE,C.c_void_p];user.CreateWindowExW.restype=W.HWND
user.DefWindowProcW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM];user.DefWindowProcW.restype=C.c_ssize_t
user.LoadImageW.argtypes=[W.HINSTANCE,W.LPCWSTR,W.UINT,C.c_int,C.c_int,W.UINT];user.LoadImageW.restype=W.HANDLE
user.DestroyIcon.argtypes=[W.HICON];user.DestroyWindow.argtypes=[W.HWND]
user.CreatePopupMenu.restype=W.HMENU;user.AppendMenuW.argtypes=[W.HMENU,W.UINT,C.c_size_t,W.LPCWSTR]
user.TrackPopupMenu.argtypes=[W.HMENU,W.UINT,C.c_int,C.c_int,C.c_int,W.HWND,C.c_void_p];user.TrackPopupMenu.restype=W.UINT
user.DestroyMenu.argtypes=[W.HMENU];user.SetForegroundWindow.argtypes=[W.HWND]
user.PostMessageW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM]
user.GetCursorPos.argtypes=[C.POINTER(W.POINT)];user.RegisterWindowMessageW.argtypes=[W.LPCWSTR]
user.UnregisterClassW.argtypes=[W.LPCWSTR,W.HINSTANCE]
shell.Shell_NotifyIconW.argtypes=[W.DWORD,C.POINTER(IconData)];shell.Shell_NotifyIconW.restype=W.BOOL

class TrayIcon:
    CALLBACK=0x8000+21
    SHOW_MESSAGE=0x8000+22
    def __init__(self,app):
        self.app=app;self.closed=False;self.last_tip='';self.added=False
        self.commands=queue.Queue();self.last_error=None
        self.name='GameControlCenterTray_'+str(os.getpid());self.instance=kernel.GetModuleHandleW(None)
        self.proc=PROC(self.window_proc)
        wc=WindowClass();wc.proc=self.proc;wc.instance=self.instance;wc.name=self.name
        if not user.RegisterClassW(C.byref(wc)):raise C.WinError(C.get_last_error())
        self.hwnd=user.CreateWindowExW(0,self.name,'GameControlCenterTray',0,0,0,0,0,None,None,self.instance,None)
        if not self.hwnd:raise C.WinError(C.get_last_error())
        self.icon=user.LoadImageW(None,str(app.backend.home/'assets/center.ico'),1,0,0,0x10|0x40)
        if not self.icon:raise C.WinError(C.get_last_error())
        self.restart=user.RegisterWindowMessageW('TaskbarCreated')
        self.data=IconData();self.data.size=C.sizeof(IconData);self.data.hwnd=self.hwnd;self.data.ident=1
        self.data.flags=1|2|4;self.data.message=self.CALLBACK;self.data.icon=self.icon
        self.data.tip='手机游戏控制台 · 连接与帧率监测'
        self.add()
    def add(self):
        self.added=bool(shell.Shell_NotifyIconW(0,C.byref(self.data)))
        if not self.added:raise C.WinError(C.get_last_error())
        self.data.version=4;shell.Shell_NotifyIconW(4,C.byref(self.data))
    def window_proc(self,hwnd,message,wparam,lparam):
        try:
            if message==self.SHOW_MESSAGE:self.commands.put('show');return 0
            if message==getattr(self,'restart',-1) and not self.closed:self.add();return 0
            if message==self.CALLBACK:
                event=lparam&0xffff
                if event in (0x202,0x400,0x401):self.commands.put('show')
                elif event in (0x7b,0x205):self.popup()
                return 0
        except Exception as ex:
            self.last_error=str(ex)
        return user.DefWindowProcW(hwnd,message,wparam,lparam)
    def popup(self):
        menu=user.CreatePopupMenu();point=W.POINT();user.GetCursorPos(C.byref(point))
        try:
            user.AppendMenuW(menu,0,100,'显示控制台');user.AppendMenuW(menu,0,101,'最小化控制台')
            user.AppendMenuW(menu,8 if self.app.mini_visible else 0,102,'状态悬浮窗')
            with self.app.backend.lock:labels=bool(self.app.backend.local.get('labels',{}).get('running'))
            user.AppendMenuW(menu,(8 if labels else 0)|(1 if self.app.backend.busy else 0),103,'按键标识')
            user.AppendMenuW(menu,0x800,0,None);user.AppendMenuW(menu,0,199,'退出控制台')
            user.SetForegroundWindow(self.hwnd)
            command=user.TrackPopupMenu(menu,0x100|2,point.x,point.y,0,self.hwnd,None)
            user.PostMessageW(self.hwnd,0,0,0)
            actions={100:'show',101:'hide',102:'mini',103:'labels',199:'quit'}
            if command in actions:self.commands.put(actions[command])
        finally:user.DestroyMenu(menu)
    def drain(self):
        # Tk calls must run from a normal Tk timer, never from a ctypes WNDPROC
        # callback nested inside Tcl's Windows message pump (GIL re-entry hazard).
        if self.last_error:self.app.toast.set('托盘操作失败：'+self.last_error);self.last_error=None
        while True:
            try:command=self.commands.get_nowait()
            except queue.Empty:return True
            if command=='show':self.app.show_main()
            elif command=='hide':self.app.minimize_main()
            elif command=='mini':self.app.toggle_mini()
            elif command=='labels':self.app.action('切换手柄提示',self.app.backend.toggle_labels)
            elif command=='quit':self.app.quit();return False
    def update(self,local,phone):
        battery=(phone.get('battery') or {}).get('percent');pad='手柄已连' if local.get('controllers') else '手柄未连'
        state=local.get('adapter',{}).get('state','读取中');fps=local.get('screen_fps')
        tip=f'手机游戏控制台\n{state} · {pad}\n手机 {battery if battery is not None else "—"}% · 投屏 FPS {fps if fps is not None else "—"}'
        if tip!=self.last_tip:
            self.data.tip=tip[:127];self.data.flags=4
            shell.Shell_NotifyIconW(1,C.byref(self.data));self.data.flags=1|2|4;self.last_tip=tip
    def close(self):
        if self.closed:return
        self.closed=True
        if self.added:shell.Shell_NotifyIconW(2,C.byref(self.data))
        user.DestroyWindow(self.hwnd);user.DestroyIcon(self.icon);user.UnregisterClassW(self.name,self.instance)
