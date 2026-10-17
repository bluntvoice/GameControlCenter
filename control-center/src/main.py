import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import queue
import statistics
import sys
import time
import tkinter as tk
from tkinter import ttk

from backend import Center,center_home,read_json
import winprobe
from mini_status import MiniStatus
from tray_icon import TrayIcon
from profile_editor import ProfileEditor
from version_info import running_version

BG='#E7EDF3'; INK='#172A40'; MUTED='#617286'; WHITE='#FFFFFF'; LINE='#CCD8E3'
BLUE='#256DB3'; TEAL='#167F79'; AMBER='#B55B20'; RED='#B53B4A'
TONES={'ok':TEAL,'warn':AMBER,'bad':RED,'muted':MUTED,'info':BLUE}
BODY=('Microsoft YaHei UI',10); SMALL=('Microsoft YaHei UI',9)

class App:
    def __init__(self):
        self.root=tk.Tk(); self.root.title('手机游戏控制台')
        height=min(1120,self.root.winfo_screenheight()-100)
        self.root.geometry(f'1060x{height}+70+45'); self.root.minsize(960,min(860,height)); self.root.configure(bg=BG)
        self.backend=Center(); self.cards={}; self.toast=tk.StringVar(value='正在读取当前连接……')
        icon=self.backend.home/'assets/center.ico'
        if icon.exists(): self.root.iconbitmap(str(icon))
        style=ttk.Style(); style.theme_use('clam')
        style.configure('TNotebook',background=BG,borderwidth=0)
        style.configure('TNotebook.Tab',font=BODY,padding=(15,8),background='#D7E1EB')
        style.map('TNotebook.Tab',background=[('selected',WHITE)],foreground=[('selected',INK)])
        style.configure('Treeview',font=SMALL,rowheight=27,background=WHITE,fieldbackground=WHITE,foreground=INK)
        style.configure('Treeview.Heading',font=SMALL,background=BG,foreground=INK)
        header=tk.Frame(self.root,bg=INK,height=88); header.pack(fill='x'); header.pack_propagate(False)
        tk.Label(header,text='手机游戏控制台',font=('Microsoft YaHei UI',20,'bold'),fg=WHITE,bg=INK).pack(anchor='w',padx=24,pady=(13,0))
        self.profile_heading=tk.StringVar(value='正在读取方案……')
        tk.Label(header,textvariable=self.profile_heading,font=SMALL,fg='#C0D4E5',bg=INK).pack(anchor='w',padx=26,pady=(3,0))
        version=running_version()
        self.version_label=tk.Label(header,text=('v'+version if version[0].isdigit() else version),font=('Bahnschrift',12),fg='#D5ECFF',bg=INK)
        self.version_label.place(relx=1,x=-24,y=24,anchor='e')
        tk.Label(header,text='连接 / 输入 / 帧率',font=('Bahnschrift',10),fg='#9FB8D0',bg=INK).place(relx=1,x=-24,y=49,anchor='e')
        bar=tk.Frame(self.root,bg=BG);bar.pack(fill='x',padx=18,pady=(12,8))
        for col in range(6):bar.columnconfigure(col,weight=1,uniform='actions')
        self.button(bar,'一键准备',lambda:self.action('一键准备',self.backend.prepare),BLUE).grid(row=0,column=0,sticky='ew',padx=(0,7))
        self.button(bar,'恢复自动控制',lambda:self.action('恢复自动控制',lambda:self.backend.request_pad('start')),TEAL).grid(row=0,column=1,sticky='ew',padx=(0,7))
        self.button(bar,'暂停控制',lambda:self.action('暂停控制',lambda:self.backend.request_pad('pause')),WHITE,INK).grid(row=0,column=2,sticky='ew',padx=(0,7))
        self.mini_button=self.button(bar,'显示悬浮窗',self.toggle_mini,WHITE,INK)
        self.mini_button.grid(row=0,column=3,sticky='ew',padx=(0,7))
        self.button(bar,'最小化',self.minimize_main,WHITE,INK).grid(row=0,column=4,sticky='ew',padx=(0,7))
        self.button(bar,'连接手机',lambda:self.action('连接手机',self.backend.connect_phone),WHITE,INK).grid(row=0,column=5,sticky='ew')
        self.chain=tk.Canvas(self.root,height=43,bg=BG,highlightthickness=0);self.chain.pack(fill='x',padx=18)
        schemebar=tk.Frame(self.root,bg=BG);schemebar.pack(fill='x',padx=18,pady=(0,6))
        tk.Label(schemebar,text='当前方案',font=SMALL,bg=BG,fg=INK).pack(side='left')
        self.scheme_name=tk.StringVar();self.scheme_combo=ttk.Combobox(schemebar,textvariable=self.scheme_name,width=29,state='readonly')
        self.scheme_combo.pack(side='left',padx=10);self.scheme_combo.bind('<<ComboboxSelected>>',lambda e:self.change_scheme(self.scheme_name.get()))
        self.button(schemebar,'制作 / 编辑方案',lambda:self.notebook.select(self.editor_tab),WHITE,BLUE).pack(side='left')
        tk.Label(self.root,textvariable=self.toast,bg=INK,fg=WHITE,font=SMALL,anchor='w',padx=18,pady=7).pack(side='bottom',fill='x')
        notebook=ttk.Notebook(self.root);self.notebook=notebook;notebook.pack(fill='both',expand=True,padx=18,pady=(3,10))
        live=tk.Frame(notebook,bg=BG);records=tk.Frame(notebook,bg=BG);self.editor_tab=tk.Frame(notebook,bg=BG)
        notebook.add(live,text='控制与监测');notebook.add(self.editor_tab,text='方案编辑');notebook.add(records,text='方案与记录')
        self.build_live(live);self.build_records(records)
        self.editor=ProfileEditor(self,self.editor_tab)
        self.mini=MiniStatus(self)
        self.mini_visible=bool(self.backend.config.get('mini_visible',True))
        self.mini.set_visible(self.mini_visible)
        self.mini_button.configure(text='隐藏悬浮窗' if self.mini_visible else '显示悬浮窗')
        self.tray=TrayIcon(self)
        self.root.protocol('WM_DELETE_WINDOW',self.hide_to_tray)
        self.backend.start(); self.root.after(250,self.tick)
    def button(self,parent,text,command,bg=WHITE,fg=WHITE):
        return tk.Button(parent,text=text,command=command,bg=bg,fg=fg,font=BODY,
             relief='flat',bd=0,padx=15,pady=7,activebackground='#C9DCEB' if bg==WHITE else '#1E577E',
             activeforeground=INK if bg==WHITE else WHITE,cursor='hand2',highlightthickness=1,
             highlightbackground=LINE if bg==WHITE else bg,highlightcolor=BLUE)
    def panel(self,parent): return tk.Frame(parent,bg=WHITE,highlightthickness=1,highlightbackground=LINE)
    def build_live(self,parent):
        top=tk.Frame(parent,bg=BG);top.pack(fill='x',pady=(10,9))
        top.columnconfigure(0,weight=3);top.columnconfigure(1,weight=2)
        programs=tk.Frame(top,bg=BG);programs.grid(row=0,column=0,sticky='nsew',padx=(0,10))
        for col in range(2): programs.columnconfigure(col,weight=1)
        for row in range(2):programs.rowconfigure(row,weight=1,uniform='programs')
        info=[('gamescrcpy','GameScrcpy','投屏软件'),('adapter','双摇杆适配器','连续方向与力度'),
              ('labels','手柄提示层','在投屏上显示手柄名称'),('antimicrox','AntiMicroX','仅作独立备用，打开前暂停主通路')]
        for i,(key,title,description) in enumerate(info):
            card=self.panel(programs);card.grid(row=i//2,column=i%2,sticky='nsew',padx=(0,7),pady=(0,7))
            card.columnconfigure(0,weight=1);card.rowconfigure(2,weight=1)
            tk.Label(card,text=title,bg=WHITE,fg=INK,font=('Microsoft YaHei UI',11,'bold'),anchor='w').grid(row=0,column=0,sticky='ew',padx=12,pady=(9,2))
            state=tk.Label(card,text='读取中',bg=WHITE,fg=MUTED,font=BODY,anchor='w');state.grid(row=1,column=0,sticky='ew',padx=12)
            detail=tk.Label(card,text=description,bg=WHITE,fg=MUTED,font=('Microsoft YaHei UI',8),wraplength=225,anchor='nw',justify='left',height=2)
            detail.grid(row=2,column=0,sticky='nsew',padx=12,pady=(2,3))
            if key=='labels':
                self.label_toggle=self.button(card,'显示提示',lambda:self.action('切换手柄提示',self.backend.toggle_labels),WHITE,BLUE)
                self.label_toggle.grid(row=3,column=0,sticky='w',padx=9,pady=(0,7))
            else:
                self.button(card,'打开窗口' if key!='antimicrox' else '打开备用',lambda k=key:self.action('打开'+k,lambda:self.backend.open_component(k)),WHITE,BLUE).grid(row=3,column=0,sticky='w',padx=9,pady=(0,7))
            self.cards[key]=(state,detail)
        device=self.panel(top);device.grid(row=0,column=1,sticky='nsew')
        heading=tk.Frame(device,bg=WHITE);heading.pack(fill='x',padx=14,pady=(10,0))
        tk.Label(heading,text='手机与手柄',bg=WHITE,fg=INK,font=('Microsoft YaHei UI',11,'bold')).pack(side='left')
        self.phone_state=tk.Label(heading,text='读取中',bg=WHITE,fg=MUTED,font=SMALL);self.phone_state.pack(side='right')
        row=tk.Frame(device,bg=WHITE);row.pack(fill='x',padx=14,pady=(6,0))
        self.battery=tk.Label(row,text='—',bg=WHITE,fg=INK,font=('Bahnschrift',32));self.battery.pack(side='left')
        self.battery_detail=tk.Label(row,text='电量读取中',bg=WHITE,fg=MUTED,font=SMALL,justify='left');self.battery_detail.pack(side='left',padx=16)
        self.pad_text=tk.Label(device,text='手柄读取中',bg=WHITE,fg=MUTED,font=SMALL);self.pad_text.pack(anchor='w',padx=14,pady=(12,6))
        tk.Label(device,text=self.backend.config['serial'],bg=WHITE,fg=MUTED,font=('Consolas',9)).pack(anchor='w',padx=14,pady=(0,9))
        events=self.panel(parent);events.pack(side='bottom',fill='x',pady=(8,0))
        self.latest=tk.Label(events,text='正在建立监测',bg=WHITE,fg=MUTED,font=SMALL,anchor='w',justify='left',wraplength=960)
        self.latest.pack(fill='x',padx=12,pady=8)
        chart_panel=self.panel(parent);chart_panel.pack(fill='both',expand=True)
        chart_heading=tk.Frame(chart_panel,bg=WHITE);chart_heading.pack(fill='x',padx=14,pady=(9,2))
        tk.Label(chart_heading,text='帧率波动',bg=WHITE,fg=INK,font=('Microsoft YaHei UI',11,'bold')).pack(side='left')
        self.fps_summary=tk.Label(chart_heading,text='等待真实样本',bg=WHITE,fg=MUTED,font=SMALL);self.fps_summary.pack(side='right')
        values=tk.Frame(chart_panel,bg=WHITE);values.pack(fill='x',padx=14)
        self.client_value=tk.Label(values,text='投屏 FPS  —',bg=WHITE,fg=BLUE,font=('Bahnschrift',16));self.client_value.pack(side='left')
        self.phone_value=tk.Label(values,text='游戏画面 FPS  —',bg=WHITE,fg=TEAL,font=('Bahnschrift',16));self.phone_value.pack(side='left',padx=25)
        tk.Label(chart_panel,text='蓝：GameScrcpy 原生解码 FPS   青：手机游戏画面合成 FPS   缺失数据留空；两者均不等于端到端延迟。',
            bg=WHITE,fg=MUTED,font=('Microsoft YaHei UI',8),anchor='w',wraplength=950,justify='left').pack(side='bottom',fill='x',padx=14,pady=(0,6))
        self.chart=tk.Canvas(chart_panel,height=133,bg=WHITE,highlightthickness=0);self.chart.pack(fill='both',expand=True,padx=8)
    def build_records(self,parent):
        profile=self.panel(parent);profile.pack(fill='x',pady=12)
        self.record_profile=tk.Label(profile,text='当前方案读取中',bg=WHITE,fg=INK,font=('Microsoft YaHei UI',13,'bold'));self.record_profile.pack(anchor='w',padx=16,pady=(14,7))
        tk.Label(profile,text='可从空白新建或复制现有方案；左杆死区 10%，右杆 12%。新方案需在对应模式下校对和试用。',bg=WHITE,fg=MUTED,font=BODY).pack(anchor='w',padx=16)
        self.cleanup_label=tk.Label(profile,text='归档状态读取中',bg=WHITE,fg=TEAL,font=BODY,wraplength=940,justify='left')
        self.cleanup_label.pack(anchor='w',padx=16,pady=(7,10))
        tools=tk.Frame(profile,bg=WHITE);tools.pack(fill='x',padx=12,pady=(0,12))
        self.button(tools,'打开运行记录',lambda:os.startfile(self.backend.session),WHITE,BLUE).pack(side='left')
        self.button(tools,'查看方案备份',lambda:os.startfile(self.backend.home/'backups'),WHITE,BLUE).pack(side='left',padx=8)
        self.button(tools,'使用说明',lambda:os.startfile(self.backend.home/'使用说明.md'),WHITE,BLUE).pack(side='left')
        tk.Label(parent,text='异常与操作记录',bg=BG,fg=INK,font=('Microsoft YaHei UI',11,'bold')).pack(anchor='w',pady=(0,8))
        table=tk.Frame(parent,bg=BG);table.pack(fill='both',expand=True)
        self.table=ttk.Treeview(table,columns=('time','kind','message'),show='headings')
        self.table.heading('time',text='时间');self.table.heading('kind',text='状态');self.table.heading('message',text='事件')
        self.table.column('time',width=165,stretch=False);self.table.column('kind',width=70,stretch=False);self.table.column('message',width=670)
        self.table.pack(side='left',fill='both',expand=True)
        scroll=ttk.Scrollbar(table,orient='vertical',command=self.table.yview);scroll.pack(side='right',fill='y');self.table.configure(yscrollcommand=scroll.set)
        tk.Label(parent,text='记录只在控制台运行时采集。进程退出≠已证实崩溃；无响应需连续多次探测，Windows 崩溃日志另外记载。',
                 bg=BG,fg=MUTED,font=SMALL,wraplength=980,anchor='w').pack(fill='x',pady=10)
    def action(self,name,function):
        if self.backend.busy:
            self.toast.set('正在'+self.backend.action+'，请稍候');return
        self.backend.action_async(name,function)
    def toggle_mini(self):
        self.mini_visible=not self.mini_visible
        self.mini.set_visible(self.mini_visible)
        self.backend.save_preference('mini_visible',self.mini_visible)
        self.mini_button.configure(text='隐藏悬浮窗' if self.mini_visible else '显示悬浮窗')
    def change_scheme(self,name):
        self.action('切换方案',lambda:self.backend.switch_profile(name))
    def refresh_schemes(self):
        try:
            catalog=self.backend.profiles.catalog();active=next(e for e in catalog['profiles'] if e['id']==catalog['active'])
            names=[e['name'] for e in catalog['profiles']]
            state='disabled' if self.backend.busy or self.backend.editing_profile else 'readonly'
            self.scheme_combo.configure(values=names,state=state);self.scheme_name.set(active['name'])
            self.mini.scheme_combo.configure(values=names,state=state);self.mini.scheme_name.set(active['name'])
            self.profile_heading.set(active['name']+' · 投屏前台自动控制 · 双摇杆与鼠标统一触控')
            self.record_profile.configure(text='当前方案：'+active['name']+' · '+active.get('status','待试用'))
        except (OSError,ValueError,KeyError,StopIteration):pass
    def tick(self):
        if not self.tray.drain():return
        try:
            while True:
                kind,value=self.backend.updates.get_nowait()
                if kind=='event':
                    labels={'ok':'正常','warn':'留意','bad':'异常','info':'记录','muted':'状态'}
                    self.table.insert('',0,values=(value['time'][5:19].replace('T',' '),labels.get(value['kind'],'记录'),value['message']))
                    children=self.table.get_children()
                    if len(children)>120:self.table.delete(children[-1])
                    self.latest.configure(text=value['time'][11:19]+'   '+value['message'],fg=TONES.get(value['kind'],MUTED))
                    self.toast.set(value['message'])
                elif kind=='action' and value:self.toast.set(value+'中……')
        except queue.Empty:pass
        with self.backend.lock:
            local=dict(self.backend.local);phone=dict(self.backend.phone);series=list(self.backend.series)
        self.mini.update(local,phone)
        self.refresh_schemes()
        self.tray.update(local,phone)
        for key,(state,detail) in self.cards.items():
            entry=local.get(key,{})
            state.configure(text=entry.get('state','读取中'),fg=TONES.get(entry.get('tone'),MUTED))
            if key=='adapter':
                text=entry.get('detail','启动后点击启用手柄')
                if entry.get('channel_ms') is not None:text+=f" · 通道 {entry['channel_ms']:.1f}ms"
            elif key=='gamescrcpy':text='投屏窗口已最小化' if local.get('video_minimized') else '投屏窗口已打开' if local.get('video_window') else '等待打开投屏窗口'
            elif key=='labels':
                enabled=entry.get('running',False)
                self.label_toggle.configure(text='隐藏提示' if enabled else '显示提示',state='disabled' if self.backend.busy else 'normal')
                if entry.get('tone') in ('ok','muted'):
                    state.configure(text='提示已开启' if enabled else '提示已关闭')
                text='跟随投屏自动显隐；不占任务栏' if enabled else '点击下方开启；记住你的开关选择'
            else:text='独立备用；不加入一键准备，不与主通路重复输出'
            detail.configure(text=text)
        self.phone_state.configure(text='手机已连接' if phone.get('connected') else '等待手机',fg=TEAL if phone.get('connected') else AMBER)
        battery=phone.get('battery') or {}
        self.battery.configure(text=str(battery['percent'])+'%' if 'percent' in battery else '—')
        battery_text=('充电中' if battery.get('charging') else '未充电') if battery else '等待电量'
        if battery.get('temperature') is not None:battery_text+=f"\n{battery['temperature']:.1f} °C"
        if battery and (not phone.get('connected') or time.time()-battery.get('at',0)>35):battery_text+='（上次）'
        self.battery_detail.configure(text=battery_text)
        self.draw_chain(local,phone);self.update_pad_status(local.get('controllers',[]));self.draw_chart(series,local,phone)
        cleanup=read_json(self.backend.home/'cleanup-result.json',{})
        self.cleanup_label.configure(text='原始迁移资料和旧候选保留在备份中；新制作的方案独立存入方案库。')
        self.root.after(350,self.tick)
    def draw_chain(self,local,phone):
        canvas=self.chain;canvas.delete('all');width=max(canvas.winfo_width(),850)
        stages=[('手机',bool(phone.get('connected'))),('投屏',bool(local.get('video_window'))),
                ('手柄',bool(local.get('controllers'))),('双摇杆控制',bool(local.get('adapter',{}).get('armed')))]
        span=(width-40)/len(stages)
        for i,(name,ready) in enumerate(stages):
            x=18+i*span
            if i<len(stages)-1:canvas.create_line(x+115,21,x+span-12,21,fill=LINE,width=2)
            color=TEAL if ready else MUTED
            canvas.create_oval(x,15,x+10,25,fill=color,outline='')
            canvas.create_text(x+18,20,text=name+(' · 就绪' if ready else ' · 可选' if i==2 else ' · 待连接' if i<3 else ' · 已暂停'),anchor='w',font=SMALL,fill=color)
    def update_pad_status(self,controllers):
        pad=controllers[0] if controllers else {}
        self.pad_text.configure(text=f"XInput 手柄 {pad.get('index')} 已连接 · 共 {len(controllers)} 个" if controllers else '未检测到手柄',fg=TEAL if controllers else AMBER)
    def draw_chart(self,rows,local,phone):
        fps=local.get('screen_fps'); game=phone.get('fps')
        self.client_value.configure(text='投屏 FPS  '+(str(fps) if fps is not None else '—'))
        self.phone_value.configure(text='游戏画面 FPS  '+(f'{game:.1f}' if game is not None else '—'))
        recent=[r for r in rows[-90:] if isinstance(r,dict)]
        valid=[r['screen_fps'] for r in recent
               if isinstance(r.get('screen_fps'),(int,float)) and not isinstance(r['screen_fps'],bool)]
        self.fps_summary.configure(text=f'近段平均 {statistics.mean(valid):.1f} · 最低 {min(valid):.0f}' if valid else '等待真实样本')
        canvas=self.chart;canvas.delete('all');width=max(800,canvas.winfo_width());height=max(65,canvas.winfo_height())
        left=38;right=width-14;top=12;bottom=height-23
        maximum=max([75]+[r[k] for r in recent for k in ['screen_fps','game_fps']
                         if isinstance(r.get(k),(int,float)) and not isinstance(r[k],bool)])
        for value in [0,30,60]:
            y=bottom-value/maximum*(bottom-top)
            canvas.create_line(left,y,right,y,fill='#E8EEF4');canvas.create_text(left-7,y,text=str(value),anchor='e',font=('Consolas',8),fill=MUTED)
        if len(recent)<2:
            canvas.create_text((left+right)/2,(top+bottom)/2,text='连接手机和投屏后，在这里记录帧率波动',fill=MUTED,font=BODY);return
        for key,color in [('screen_fps',BLUE),('game_fps',TEAL)]:
            segment=[]
            for index,row in enumerate(recent):
                value=row.get(key)
                if not isinstance(value,(int,float)) or isinstance(value,bool):value=None
                if value is None:
                    if len(segment)>=4:canvas.create_line(*segment,fill=color,width=2)
                    segment=[];continue
                x=left+index/(len(recent)-1)*(right-left);y=bottom-value/maximum*(bottom-top)
                segment.extend([x,y])
            if len(segment)>=4:canvas.create_line(*segment,fill=color,width=2)
        canvas.create_text(left,bottom+13,text=str(recent[0].get('time',''))[11:19],anchor='w',font=('Consolas',8),fill=MUTED)
        canvas.create_text(right,bottom+13,text=str(recent[-1].get('time',''))[11:19],anchor='e',font=('Consolas',8),fill=MUTED)
    def show_main(self):
        self.root.deiconify()
        winprobe.show(winprobe.user.GetAncestor(self.root.winfo_id(),2))
    def hide_to_tray(self):
        self.root.withdraw()
        self.mini.set_visible(self.mini_visible and not self.backend.editing_profile)
    def minimize_main(self):
        self.root.iconify()
        self.mini.set_visible(self.mini_visible and not self.backend.editing_profile)
    def quit(self):
        self.editor.shutdown()
        self.backend.close();self.tray.close();self.root.destroy()

def main():
    try:winprobe.user.SetProcessDpiAwarenessContext(C.c_void_p(-4))
    except (AttributeError,OSError):pass
    winprobe.kernel.CreateMutexW.argtypes=[C.c_void_p,W.BOOL,W.LPCWSTR];winprobe.kernel.CreateMutexW.restype=W.HANDLE
    mutex=winprobe.kernel.CreateMutexW(None,False,'Local\\GameControlProfiles_ControlCenter')
    if C.get_last_error()==183:
        for window in winprobe.windows():
            if window['title']=='GameControlCenterTray':
                winprobe.user.PostMessageW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM]
                winprobe.user.PostMessageW(window['hwnd'],TrayIcon.SHOW_MESSAGE,0,0);return
        for window in winprobe.windows():
            if window['title']=='手机游戏控制台':winprobe.show(window['hwnd']);return
        return
    from app_config import ensure_configuration
    if ensure_configuration():App().root.mainloop()

if __name__=='__main__':
    try:
        if '--verify-package' in sys.argv:
            from package_probe import run
            run()
        else:main()
    except Exception:
        import traceback
        folder=center_home()/'runtime';folder.mkdir(parents=True,exist_ok=True)
        error=folder/'console-error.log';error.write_text(traceback.format_exc(),encoding='utf-8')
        from tkinter import messagebox
        messagebox.showerror('控制台未能启动','请保留错误记录并反馈：\n'+str(error))
