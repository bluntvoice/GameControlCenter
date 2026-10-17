"""Resizable, non-activating status strip with remembered geometry."""
import ctypes as C
from ctypes import wintypes as W
import tkinter as tk
import winprobe

BG='#172A40';FG='#F2F7FC';MUTED='#A9C1D5';WARN='#FFD099'

class MiniSelect(tk.Menubutton):
    """Read-only scheme picker with the same surface and menu palette as the strip."""
    def __init__(self,parent,variable,command):
        super().__init__(parent,textvariable=variable,bg=BG,fg=FG,activebackground='#29445D',activeforeground=FG,
            font=('Microsoft YaHei UI',8),relief='flat',bd=0,padx=6,pady=0,indicatoron=True,direction='below',
            width=20,highlightthickness=1,highlightbackground='#355268',highlightcolor='#72D8CB',anchor='w',cursor='hand2')
        self.variable=variable;self.command=command;self.values=[]
        self.popup=tk.Menu(self,tearoff=False,bg=BG,fg=FG,activebackground='#29445D',activeforeground='#98F1DA',
            selectcolor='#72D8CB',disabledforeground=MUTED,font=('Microsoft YaHei UI',9),bd=1,relief='solid')
        super().configure(menu=self.popup)
    def configure(self,cnf=None,**kw):
        values=kw.pop('values',None)
        if values is not None and list(values)!=self.values:
            self.values=list(values);self.popup.delete(0,'end')
            for value in self.values:
                self.popup.add_radiobutton(label=value,variable=self.variable,value=value,command=self.command)
        if kw.get('state')=='readonly':kw['state']='normal'
        return super().configure(cnf,**kw)

class MiniStatus:
    def __init__(self,app):
        self.app=app;self.window=tk.Toplevel(app.root)
        self.window.title('手机游戏控制台 · 悬浮状态');self.window.overrideredirect(True)
        self.window.attributes('-toolwindow',True);self.window.attributes('-topmost',True)
        self.window.configure(bg=BG);self.window.withdraw();self.drag=None;self.resize=None
        screenw=app.root.winfo_screenwidth();screenh=app.root.winfo_screenheight()
        size=app.backend.config.get('mini_size',[680,60]);w=max(420,min(int(size[0]),screenw));h=max(self.min_height(w),min(int(size[1]),screenh))
        pos=app.backend.config.get('mini_position',[max(20,screenw-w-20),screenh-h-20])
        x=max(0,min(int(pos[0]),screenw-w));y=max(0,min(int(pos[1]),screenh-h))
        self.window.geometry(f'{w}x{h}+{x}+{y}')
        header=tk.Frame(self.window,bg=BG);header.pack(fill='x',padx=7,pady=(2,0))
        def button(text,command):
            return tk.Button(header,text=text,command=command,font=('Microsoft YaHei UI',8),bg=BG,fg=MUTED,
                activebackground='#29445D',activeforeground=FG,relief='flat',bd=0,padx=7,pady=0,takefocus=False)
        button('主界面',app.show_main).pack(side='left')
        self.labels_button=button('隐藏按键标识',lambda:app.action('切换手柄提示',app.backend.toggle_labels))
        self.labels_button.pack(side='left',padx=(5,0))
        self.scheme_name=tk.StringVar()
        self.scheme_combo=MiniSelect(header,self.scheme_name,lambda:app.change_scheme(self.scheme_name.get()))
        self.scheme_combo.pack(side='left',padx=(6,0))
        handle=tk.Label(header,text='',bg=BG,cursor='fleur');handle.pack(side='left',fill='x',expand=True)
        button('×',app.toggle_mini).pack(side='right')
        status_row=tk.Frame(self.window,bg=BG);status_row.pack(fill='both',expand=True,padx=12,pady=(0,5))
        self.adapter_button=tk.Button(status_row,text='读取中',command=lambda:app.action('恢复自动控制',lambda:app.backend.request_pad('start')),
            font=('Microsoft YaHei UI',9),bg=BG,fg=FG,activebackground='#29445D',activeforeground=FG,
            relief='flat',bd=0,padx=5,pady=0,cursor='hand2',takefocus=False)
        self.adapter_button.pack(side='right',padx=(5,0))
        self.body=tk.Label(status_row,text='正在读取状态…',bg=BG,fg=FG,font=('Microsoft YaHei UI',9),anchor='w',justify='left',cursor='fleur')
        self.body.pack(side='left',fill='both',expand=True)
        for widget in (handle,self.body):
            widget.bind('<ButtonPress-1>',self.drag_start);widget.bind('<B1-Motion>',self.drag_move);widget.bind('<ButtonRelease-1>',self.geometry_end)
        grip=tk.Label(self.window,text='◢',bg=BG,fg=MUTED,font=('Segoe UI',9),cursor='sizing')
        grip.place(relx=1,rely=1,x=-2,y=1,anchor='se')
        grip.bind('<ButtonPress-1>',self.resize_start);grip.bind('<B1-Motion>',self.resize_move);grip.bind('<ButtonRelease-1>',self.geometry_end)
        self.window.bind('<Configure>',self.configure)
        self.window.update_idletasks();user=winprobe.user
        user.GetAncestor.argtypes=[W.HWND,W.UINT];user.GetAncestor.restype=W.HWND
        user.GetWindowLongW.argtypes=[W.HWND,C.c_int];user.GetWindowLongW.restype=W.LONG
        user.SetWindowLongW.argtypes=[W.HWND,C.c_int,W.LONG]
        self.hwnd=user.GetAncestor(self.window.winfo_id(),2);self.set_no_activate()
    @staticmethod
    def min_height(width):return 60 if width>=620 else 84
    def configure(self,event):
        if event.widget is self.window:self.body.configure(wraplength=max(150,event.width-36-self.adapter_button.winfo_reqwidth()))
    def set_no_activate(self):
        user=winprobe.user;style=user.GetWindowLongW(self.hwnd,-20)
        user.SetWindowLongW(self.hwnd,-20,(style&~0x40000)|0x80|0x8000000)
    def set_visible(self,visible):
        if visible:self.set_no_activate();winprobe.user.ShowWindow(self.hwnd,8)
        else:self.window.withdraw()
    def drag_start(self,event):self.drag=(event.x_root,event.y_root,self.window.winfo_x(),self.window.winfo_y())
    def drag_move(self,event):
        if self.drag:
            x,y,wx,wy=self.drag;w=self.window.winfo_width();h=self.window.winfo_height()
            nx=max(0,min(wx+event.x_root-x,self.window.winfo_screenwidth()-w))
            ny=max(0,min(wy+event.y_root-y,self.window.winfo_screenheight()-h))
            self.window.geometry(f'+{nx}+{ny}')
    def resize_start(self,event):self.resize=(event.x_root,event.y_root,self.window.winfo_width(),self.window.winfo_height())
    def resize_move(self,event):
        if self.resize:
            x,y,w,h=self.resize;sw=self.window.winfo_screenwidth();sh=self.window.winfo_screenheight()
            width=max(420,min(w+event.x_root-x,sw-self.window.winfo_x()))
            height=max(self.min_height(width),min(h+event.y_root-y,sh-self.window.winfo_y()))
            self.window.geometry(f'{width}x{height}')
    def geometry_end(self,event):
        if self.drag or self.resize:
            self.drag=None;self.resize=None
            self.app.backend.save_preferences(dict(mini_position=[self.window.winfo_x(),self.window.winfo_y()],mini_size=[self.window.winfo_width(),self.window.winfo_height()]))
    def update(self,local,phone):
        battery=(phone.get('battery') or {}).get('percent')
        phone_text=('手机 '+str(battery)+'%' if battery is not None else '手机已连') if phone.get('connected') else '手机未连'
        pad='手柄已连' if local.get('controllers') else '手柄未连'
        adapter=local.get('adapter',{});projection=local.get('gamescrcpy',{})
        state=adapter.get('state','读取中');state={'发送挂起':'已挂起','手柄控制中':'控制中','输入控制中':'控制中','等待投屏前台':'自动等待'}.get(state,state)
        video='投屏未连接' if not local.get('video_window') else '投屏正常' if projection.get('tone')=='ok' else '投屏'+projection.get('state','读取中')
        fps=local.get('screen_fps');game=phone.get('fps')
        screen='—' if fps is None else str(fps);game_text='—' if game is None else f'{game:.0f}'
        good=phone.get('connected') and projection.get('tone')=='ok' and adapter.get('tone') not in ('bad','warn')
        self.body.configure(text=f'{phone_text} · {pad} · {video} · FPS {screen} / {game_text}',fg=FG if good else WARN)
        disabled=self.app.backend.busy or self.app.backend.editing_profile
        self.adapter_button.configure(text=state,state='disabled' if disabled else 'normal',fg=FG if adapter.get('tone') not in ('bad','warn') else WARN)
        self.labels_button.configure(text='隐藏按键标识' if local.get('labels',{}).get('running') else '显示按键标识',state='disabled' if self.app.backend.busy else 'normal')
