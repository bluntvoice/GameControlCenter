"""Drag controls from a floating palette onto a paused native video surface."""
import copy
import ctypes as C
from ctypes import wintypes as W
from datetime import datetime
import json
import queue
import threading
import traceback
import tkinter as tk
from tkinter import ttk
import winprobe
from backend import atomic_json
from mouse_touch import fit_rect
from profile_store import NAMES,MODES,validate_controls

BG='#E7EDF3';INK='#172A40';BLUE='#256DB3';TEAL='#167F79';WHITE='#FFFFFF'
FONT=('Microsoft YaHei UI',10);SMALL=('Microsoft YaHei UI',9)

winprobe.user.GetAncestor.argtypes=[W.HWND,W.UINT];winprobe.user.GetAncestor.restype=W.HWND
winprobe.user.GetWindow.argtypes=[W.HWND,W.UINT];winprobe.user.GetWindow.restype=W.HWND
winprobe.user.SetWindowPos.argtypes=[W.HWND,W.HWND,C.c_int,C.c_int,C.c_int,C.c_int,W.UINT]

def keep_editor_above(video,overlay,palette):
    """Repair relative stacking only when covered, without moving or focusing UI."""
    user=winprobe.user
    if not user.IsWindowVisible(palette):return False
    above=user.GetWindow(palette,3)  # GW_HWNDPREV: toward the top of the Z order.
    seen=set()
    while above and above not in seen:
        if above in (video,overlay):
            for handle in (overlay,palette):
                # HWND_TOPMOST; NOMOVE | NOSIZE | NOACTIVATE.
                if not user.SetWindowPos(handle,-1,0,0,0,0,0x13):raise C.WinError(C.get_last_error())
            return True
        seen.add(above);above=user.GetWindow(above,3)
    return False

def drop_position(bounds,x,y):
    bx,by,bw,bh=bounds
    if bw<=0 or bh<=0 or not (bx<=x<bx+bw and by<=y<by+bh):return None
    return round((x-bx)/bw,6),round((y-by)/bh,6)

def control_at(controls,width,height,x,y):
    hits=[]
    for item in controls:
        distance=((x-item['x']*width)**2+(y-item['y']*height)**2)**.5
        radius=item.get('radius',75) if item['name']=='左摇杆' else item.get('hit_radius',0)
        # The label remains selectable even with coverage disabled.
        label=abs(x-item['x']*width)<=45 and abs(y-(item['y']*height-30))<=14
        if distance<=max(22,radius*height/1200) or label:hits.append((distance,item['name']))
    return min(hits)[1] if hits else None

class ProfileEditor:
    def __init__(self,app,parent):
        self.app=app;self.backend=app.backend;self.store=self.backend.profiles
        self.frame=tk.Frame(parent,bg=BG);self.frame.pack(fill='both',expand=True)
        self.draft=None;self.cache={};self.overlay=None;self.palette=None;self.bounds=None
        self.dragging=None;self.selected=None;self.preparing=False;self.polling=queue.Queue();self.resume_after=False
        self.note=tk.StringVar(value='从空白新建，或复制现有方案。进入摆放后，从工具条拖到投屏即可。')
        self.name=tk.StringVar();self.load_name=tk.StringVar();self.mode=tk.StringVar(value='按住')
        self.radius=tk.StringVar(value='75');self.hit_radius=tk.StringVar(value='30');self.hz=tk.StringVar(value='1');self.selected_name=tk.StringVar(value='选择一个已放置的按键')
        self.frequency_caption=tk.StringVar(value='触发次数');self.frequency_input=None;self.palette_frequency_input=None
        self.range_caption=tk.StringVar(value='瞄准行程(px)')
        head=tk.Frame(self.frame,bg=BG);head.pack(fill='x',pady=(12,8))
        tk.Label(head,text='制作方案',font=('Microsoft YaHei UI',14,'bold'),bg=BG,fg=INK).pack(side='left')
        self.loader=ttk.Combobox(head,textvariable=self.load_name,state='readonly',width=25)
        self.loader.pack(side='left',padx=15);self.loader.bind('<<ComboboxSelected>>',lambda e:self.load_selected())
        self.button(head,'空白新建',self.new).pack(side='left',padx=4)
        self.button(head,'复制当前草稿',self.duplicate).pack(side='left',padx=4)
        self.button(head,'恢复暂存草稿',self.restore_draft).pack(side='left',padx=4)
        row=tk.Frame(self.frame,bg=WHITE);row.pack(fill='x')
        tk.Label(row,text='方案名称',bg=WHITE,fg=INK,font=FONT).pack(side='left',padx=12,pady=12)
        self.name_entry=ttk.Entry(row,textvariable=self.name,width=29,font=FONT);self.name_entry.pack(side='left')
        self.button(row,'开始在投屏摆放',self.begin,BLUE,WHITE).pack(side='left',padx=10)
        self.button(row,'保存方案',self.save).pack(side='left',padx=3)
        self.button(row,'使用此方案',self.use).pack(side='left',padx=3)
        tk.Label(self.frame,textvariable=self.note,font=SMALL,fg=TEAL,bg=BG,anchor='w',wraplength=980,justify='left').pack(fill='x',pady=10)
        palette=tk.Frame(self.frame,bg=WHITE);palette.pack(fill='x')
        tk.Label(palette,text='可用组件',font=('Microsoft YaHei UI',11,'bold'),bg=WHITE,fg=INK).pack(anchor='w',padx=12,pady=(10,2))
        tk.Label(palette,text='开始摆放后，把这些组件从浮动工具条拖到投屏；同一组件再拖一次即可改位置。',font=SMALL,bg=WHITE,fg='#617286').pack(anchor='w',padx=12,pady=(0,8))
        grid=tk.Frame(palette,bg=WHITE);grid.pack(fill='x',padx=10,pady=(0,10))
        for col in range(10):grid.columnconfigure(col,weight=1,uniform='keys')
        for i,name in enumerate(NAMES):
            self.button(grid,name,lambda n=name:self.hint(n)).grid(row=i//10,column=i%10,sticky='ew',padx=3,pady=3)
        body=tk.Frame(self.frame,bg=BG);body.pack(fill='both',expand=True,pady=(12,0))
        left=tk.Frame(body,bg=WHITE);left.pack(side='left',fill='both',expand=True)
        self.table=ttk.Treeview(left,columns=('key','mode','pos'),show='headings',selectmode='browse')
        for col,text,width in [('key','组件',110),('mode','触发方式',110),('pos','位置（百分比）',220)]:
            self.table.heading(col,text=text);self.table.column(col,width=width,stretch=col=='pos')
        self.table.pack(fill='both',expand=True);self.table.bind('<<TreeviewSelect>>',self.table_select)
        props=tk.Frame(body,bg=WHITE,width=275);props.pack(side='right',fill='y',padx=(12,0));props.pack_propagate(False)
        self.properties(props)
        tk.Label(self.frame,text='编辑时停止触控；保存后可在控制台或悬浮窗切换。位置按投屏有效画面比例保存，窗口缩放不会改变映射。',font=SMALL,bg=BG,fg='#617286',anchor='w',wraplength=980).pack(fill='x',pady=10)
        self.load(self.store.catalog()['active'])
        self.hit_radius.trace_add('write',self.preview_coverage)
        self.app.root.after(100,self.poll)
    def button(self,parent,text,command,bg=WHITE,fg=BLUE):
        return tk.Button(parent,text=text,command=command,font=SMALL,bg=bg,fg=fg,activebackground='#CCDDEB',relief='flat',padx=9,pady=6,cursor='hand2')
    def properties(self,parent):
        tk.Label(parent,textvariable=self.selected_name,font=('Microsoft YaHei UI',10,'bold'),bg=WHITE,fg=INK,wraplength=245).pack(anchor='w',padx=12,pady=(12,8))
        grid=tk.Frame(parent,bg=WHITE);grid.pack(fill='x',padx=12)
        for row,(label,var) in enumerate([('触发方式',self.mode),('点击覆盖半径',self.hit_radius),('摇杆/瞄准范围',self.radius),('连点次数/秒',self.hz)]):
            options=dict(textvariable=self.frequency_caption) if var is self.hz else dict(textvariable=self.range_caption) if var is self.radius else dict(text=label)
            tk.Label(grid,**options,font=SMALL,bg=WHITE,fg=INK).grid(row=row,column=0,sticky='w',pady=5)
            if row==0:
                widget=ttk.Combobox(grid,textvariable=var,values=list(MODES),state='readonly',width=12)
                widget.bind('<<ComboboxSelected>>',lambda e:self.change_mode())
            elif row==1:widget=ttk.Spinbox(grid,textvariable=var,from_=0,to=400,increment=5,width=12)
            else:widget=ttk.Entry(grid,textvariable=var,width=14)
            widget.grid(row=row,column=1,sticky='e',padx=(7,0),pady=5)
            if var is self.hz:self.frequency_input=widget
        self.button(parent,'应用属性',self.apply_properties).pack(anchor='w',padx=12,pady=8)
        self.button(parent,'移除选中组件',self.remove,WHITE,'#B53B4A').pack(anchor='w',padx=12)
        tk.Label(parent,text='覆盖半径只影响鼠标命中与编辑选中。\n左杆行程决定推到底时的触控距离，勿与覆盖半径混淆。\n像素数以画面高度 1200 为参考。\n右杆数值是速度百分比，100 为默认。\n瞄准：手柄用右杆调整；鼠标按住拖动调整。',bg=WHITE,fg='#617286',font=('Microsoft YaHei UI',8),justify='left',wraplength=245).pack(anchor='w',padx=12,pady=12)
    def remember(self):
        if self.draft:
            self.draft['name']=self.name.get();self.cache[self.draft['id'] or 'new']=copy.deepcopy(self.draft)
    def load(self,ident):
        self.remember();draft=self.store.load(ident);cached=self.cache.get(draft['id'])
        self.draft=cached if cached and cached.get('sha256')==draft['sha256'] else draft
        self.name.set(self.draft['name']);self.load_name.set(draft['name']);self.selected=None
        self.name_entry.configure(state='readonly');self.refresh()
    def load_selected(self):
        if self.overlay:self.note.set('先结束投屏摆放，再载入其他方案');return
        try:self.load(self.load_name.get())
        except Exception as ex:self.note.set(str(ex))
    def new(self):
        if self.overlay:self.note.set('先结束投屏摆放，再新建方案');return
        self.remember();self.draft=dict(id=None,name='新方案-'+datetime.now().strftime('%H%M%S'),controls=[],sha256=None)
        self.name.set(self.draft['name']);self.name_entry.configure(state='normal');self.selected=None;self.refresh()
        self.note.set('空白方案已就绪。点“开始在投屏摆放”，把需要的按键拖入画面。')
    def duplicate(self):
        if self.overlay:self.note.set('先结束投屏摆放，再复制方案');return
        controls=copy.deepcopy(self.draft['controls']);name=self.name.get()+'-副本'
        self.new();self.draft['controls']=controls;self.name.set(name);self.refresh()
    def restore_draft(self):
        if self.overlay:return
        try:
            draft=json.loads((self.backend.runtime/'editor-draft.json').read_text(encoding='utf-8'))
            validate_controls(draft['controls']);self.draft=draft;self.name.set(draft['name'])
            self.name_entry.configure(state='readonly' if draft.get('id') else 'normal');self.selected=None;self.refresh()
            self.note.set('已恢复上次暂存草稿；保存前仍会检查外部修改。')
        except (OSError,ValueError,KeyError) as ex:self.note.set('无法恢复草稿：'+str(ex))
    def refresh(self):
        self.loader.configure(values=[e['name'] for e in self.store.catalog()['profiles']])
        for row in self.table.get_children():self.table.delete(row)
        reverse={v:k for k,v in MODES.items()}
        for item in self.draft['controls']:
            self.table.insert('', 'end',iid=item['name'],values=(item['name'],reverse.get(item.get('mode','hold'),'按住'),f"{item['x']*100:.1f}% , {item['y']*100:.1f}%"))
        self.sync_frequency();self.draw()
    def table_select(self,event=None):
        rows=self.table.selection()
        if rows:self.select(rows[0])
    def select(self,name):
        self.selected=name;item=next((c for c in self.draft['controls'] if c['name']==name),None)
        if not item:return
        self.selected_name.set(name);self.mode.set(next((k for k,v in MODES.items() if v==item.get('mode','hold')),'按住'))
        self.radius.set(str(round(item.get('radius',75),2)));self.hit_radius.set(str(item.get('hit_radius',0)))
        self.hz.set(str(item.get('hz',10)) if item.get('mode')=='repeat' else '1');self.sync_frequency();self.draw()
    def sync_frequency(self):
        self.range_caption.set('左杆行程(px)' if self.selected=='左摇杆' else '右杆速度(%)' if self.selected=='右摇杆' else '瞄准行程(px)')
        repeat=self.selected is not None and self.mode.get()=='连续点击'
        self.frequency_caption.set('连点次数/秒' if repeat else '触发次数')
        if not repeat:self.hz.set('1')
        for widget in (self.frequency_input,self.palette_frequency_input):
            if widget is not None and widget.winfo_exists():widget.configure(state='normal' if repeat else 'disabled')
    def change_mode(self):
        item=next((c for c in self.draft['controls'] if c['name']==self.selected),None)
        if item and MODES.get(self.mode.get())!=item.get('mode','hold'):
            self.hz.set('10' if self.mode.get()=='连续点击' else '1')
        self.apply_properties();self.sync_frequency()
    def apply_properties(self):
        item=next((c for c in self.draft['controls'] if c['name']==self.selected),None)
        if not item:return True
        try:
            mode=MODES[self.mode.get()]
            value=dict(item,mode=mode,radius=float(self.radius.get()),hit_radius=float(self.hit_radius.get()),hz=float(self.hz.get()) if mode=='repeat' else 1)
            validate_controls([value]);item.update(value);self.snapshot();self.refresh()
            return True
        except (ValueError,KeyError) as ex:self.note.set(str(ex));return False
    def preview_coverage(self,*args):
        item=next((c for c in self.draft['controls'] if c['name']==self.selected),None)
        if not item:return
        try:
            value=float(self.hit_radius.get());validate_controls([dict(item,hit_radius=value)])
        except (ValueError,KeyError):return  # Allow an empty or partial number while typing.
        if item.get('hit_radius',0)==value:return
        item['hit_radius']=value;self.snapshot();self.draw()
        self.note.set(f"{item['name']} 覆盖半径：{value:g}；预览已更新，保存方案后用于控制。")
    def remove(self):
        self.draft['controls']=[c for c in self.draft['controls'] if c['name']!=self.selected]
        self.selected=None;self.selected_name.set('选择一个已放置的按键');self.snapshot();self.refresh()
    def hint(self,name):
        self.note.set('点“开始在投屏摆放”，再从浮动工具条拖入 '+name)
    def begin(self):
        if self.overlay:self.palette.lift();return
        if self.preparing or self.backend.busy:self.note.set('正在处理，请稍候');return
        self.preparing=True;self.backend.editing_profile=True
        self.note.set('正在暂停触控并读取有效投屏区域……')
        self.backend.event('正在启动投屏摆放；暂停触控并读取画面','info')
        status_path=self.backend.analog/'status.json'
        try:status=json.loads(status_path.read_text(encoding='utf-8'));self.resume_after=not status.get('manual_pause',False)
        except (OSError,ValueError):self.resume_after=True
        def worker():
            try:self.polling.put(('ready',self.backend.editor_surface()))
            except Exception as ex:self.polling.put(('error',(str(ex),traceback.format_exc())))
        threading.Thread(target=worker,daemon=True).start()
    def poll(self):
        try:
            while True:
                kind,value=self.polling.get_nowait();self.preparing=False
                if kind=='ready':
                    try:
                        self.surface=value;self.open_overlay()
                        if self.overlay:self.backend.event('投屏摆放已启动；编辑期间触控保持暂停','ok',bounds=self.bounds)
                    except Exception as ex:self.fail('投屏摆放启动失败：'+str(ex),traceback.format_exc())
                else:self.fail('投屏摆放启动失败：'+value[0],value[1])
        except queue.Empty:pass
        finally:self.app.root.after(100,self.poll)
    def fail(self,message,detail):
        # Restore the console even if construction stopped between the two windows.
        if self.overlay or self.palette:self.finish(resume=False)
        self.preparing=False;self.backend.editing_profile=False
        self.note.set(message+'；触控保持暂停，处理后可再次点击开始。')
        self.backend.event(message,'bad',detail=detail)
    def open_overlay(self):
        self.overlay=tk.Toplevel(self.app.root);self.overlay.title('方案编辑 · 投屏摆放')
        self.overlay.overrideredirect(True);self.overlay.attributes('-toolwindow',True);self.overlay.attributes('-topmost',True);self.overlay.attributes('-alpha',.52)
        self.canvas=tk.Canvas(self.overlay,bg='#142A40',highlightthickness=2,highlightbackground='#72D8CB',cursor='crosshair');self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<ButtonPress-1>',self.canvas_down);self.canvas.bind('<B1-Motion>',self.drag_move);self.canvas.bind('<ButtonRelease-1>',self.drag_end)
        self.overlay.bind('<Escape>',lambda e:self.finish())
        self.palette=tk.Toplevel(self.app.root);self.palette.title('方案编辑工具条')
        self.palette.attributes('-toolwindow',True);self.palette.attributes('-topmost',True);self.palette.configure(bg=INK)
        self.palette.resizable(False,False);self.palette.protocol('WM_DELETE_WINDOW',self.finish)
        title=tk.Frame(self.palette,bg=INK);title.pack(fill='x',padx=9,pady=(6,2))
        tk.Label(title,text='拖入投屏 · '+self.name.get(),bg=INK,fg=WHITE,font=('Microsoft YaHei UI',10,'bold')).pack(side='left')
        self.button(title,'保存',self.save,'#29445D',WHITE).pack(side='right',padx=3)
        self.button(title,'结束摆放',self.finish,'#29445D',WHITE).pack(side='right',padx=3)
        grid=tk.Frame(self.palette,bg=INK);grid.pack(padx=8,pady=4)
        for i,name in enumerate(NAMES):
            label=tk.Label(grid,text=name,width=9,font=SMALL,bg='#29445D',fg='#D5ECFF',padx=3,pady=6,cursor='hand2')
            label.grid(row=i//10,column=i%10,padx=3,pady=3)
            label.bind('<ButtonPress-1>',lambda e,n=name:self.drag_start(n,e))
            label.bind('<B1-Motion>',self.drag_move);label.bind('<ButtonRelease-1>',self.drag_end)
        row=tk.Frame(self.palette,bg=INK);row.pack(fill='x',padx=10,pady=(0,5))
        tk.Label(row,textvariable=self.selected_name,font=SMALL,bg=INK,fg=WHITE,width=12,anchor='w').pack(side='left')
        self.mode_buttons=[]
        for text in MODES:
            button=tk.Radiobutton(row,text=text,variable=self.mode,value=text,command=self.change_mode,
                indicatoron=False,font=SMALL,bg='#29445D',fg=WHITE,selectcolor=TEAL,activebackground=BLUE,activeforeground=WHITE,
                relief='flat',bd=1,padx=12,pady=5,cursor='hand2')
            button.pack(side='left',padx=3);self.mode_buttons.append(button)
        fields=tk.Frame(self.palette,bg=INK);fields.pack(fill='x',padx=10,pady=(0,6))
        for text,var,width in [('覆盖半径',self.hit_radius,6),('摇杆/瞄准范围',self.radius,6),('次/秒',self.hz,4)]:
            options=dict(textvariable=self.frequency_caption) if var is self.hz else dict(textvariable=self.range_caption) if var is self.radius else dict(text=text)
            tk.Label(fields,**options,bg=INK,fg=WHITE,font=SMALL).pack(side='left',padx=(5,4))
            widget=ttk.Spinbox(fields,textvariable=var,from_=0,to=400,increment=5,width=width) if var is self.hit_radius else ttk.Entry(fields,textvariable=var,width=width)
            widget.pack(side='left',padx=(0,6))
            if var is self.hz:self.palette_frequency_input=widget
        self.sync_frequency()
        self.button(fields,'应用属性',self.apply_properties,'#29445D',WHITE).pack(side='left',padx=4)
        self.button(fields,'移除',self.remove,'#29445D','#FFB5B5').pack(side='left',padx=4)
        tk.Label(self.palette,textvariable=self.note,bg=INK,fg='#B5DED8',font=('Microsoft YaHei UI',8),wraplength=850,anchor='w').pack(fill='x',padx=10,pady=(0,6))
        self.palette.update_idletasks();sw=self.palette.winfo_screenwidth();sh=self.palette.winfo_screenheight()
        self.palette.geometry(f'+{max(0,(sw-self.palette.winfo_width())//2)}+{max(0,sh-self.palette.winfo_height()-55)}')
        self.app.minimize_main();self.note.set('把组件拖入投屏；拖动已放置标识微调。编辑期间不向手机发送触控。')
        if hasattr(self.app,'mini'):self.app.mini.set_visible(False)
        self.last_bounds=None
        self.update_bounds()
    def update_bounds(self):
        if not self.overlay:return
        try:
            u=winprobe.user;surface=self.surface['surface'];video=self.surface['video']
            if not u.IsWindow(surface) or not u.IsWindowVisible(video) or u.IsIconic(video):raise ValueError('投屏窗口已关闭或最小化，请结束摆放后重试')
            r=W.RECT();u.GetWindowRect.argtypes=[W.HWND,C.POINTER(W.RECT)]
            if not u.GetWindowRect(surface,C.byref(r)):raise ValueError('无法读取投屏区域')
            self.bounds=fit_rect((r.left,r.top,r.right-r.left,r.bottom-r.top),self.surface['width'],self.surface['height'])
            if self.bounds!=self.last_bounds:
                self.last_bounds=self.bounds
                x,y,w,h=self.bounds;self.overlay.geometry(f'{w}x{h}+{x}+{y}');self.draw()
            overlay=u.GetAncestor(self.overlay.winfo_id(),2)
            palette=u.GetAncestor(self.palette.winfo_id(),2)
            keep_editor_above(video,overlay,palette)
        except Exception as ex:self.fail('投屏摆放中断：'+str(ex),traceback.format_exc());return
        self.overlay.after(220,self.update_bounds)
    def drag_start(self,name,event):
        self.dragging=name
        try:event.widget.grab_set_global()
        except tk.TclError:self.dragging=None;self.note.set('无法捕获拖动，请重试')
    def canvas_down(self,event):
        if not self.bounds:return
        w,h=self.bounds[2:];nearest=control_at(self.draft['controls'],w,h,event.x,event.y)
        if nearest:self.select(nearest);self.drag_start(nearest,event)
    def drag_move(self,event):
        if not self.dragging or not self.bounds:return
        self.canvas.delete('ghost');pos=drop_position(self.bounds,event.x_root,event.y_root)
        if pos:self.canvas.create_text(pos[0]*self.bounds[2],pos[1]*self.bounds[3],text=self.dragging,fill='#FFFFFF',font=('Microsoft YaHei UI',13,'bold'),tags='ghost')
    def drag_end(self,event):
        name=self.dragging;self.dragging=None
        try:event.widget.grab_release()
        except tk.TclError:pass
        if not name or not self.bounds:return
        position=drop_position(self.bounds,event.x_root,event.y_root)
        if not position:self.note.set('请拖到投屏的有效画面内；未改变原位置');self.draw();return
        item=next((c for c in self.draft['controls'] if c['name']==name),None)
        if item:item.update(x=position[0],y=position[1])
        else:self.draft['controls'].append(dict(name=name,x=position[0],y=position[1],mode='once' if name.startswith('鼠标') else 'hold',radius=100 if name=='右摇杆' else 75,hz=1,hit_radius=0 if name in ('左摇杆','右摇杆') else 30))
        self.select(name);self.snapshot();self.refresh();self.note.set(name+' 已放置；可继续拖动或修改属性')
    def draw(self):
        if not self.overlay or not self.bounds:return
        self.canvas.delete('all');w,h=self.bounds[2:]
        for item in self.draft['controls']:
            x,y=item['x']*w,item['y']*h;color='#FFF29C' if item['name']==self.selected else '#88FFE5'
            coverage=item.get('hit_radius',0)*h/1200
            if coverage>0 and item['name'] not in ('左摇杆','右摇杆'):
                self.canvas.create_oval(x-coverage,y-coverage,x+coverage,y+coverage,outline='#EACB88',dash=(4,3),width=2)
            radius=item.get('radius',75)*h/1200 if item['name']=='左摇杆' or item.get('mode')=='aim' else 22
            self.canvas.create_oval(x-radius,y-radius,x+radius,y+radius,outline=color,width=2)
            self.canvas.create_line(x-8,y,x+8,y,fill=color,width=2);self.canvas.create_line(x,y-8,x,y+8,fill=color,width=2)
            self.canvas.create_text(max(28,min(w-35,x)),max(14,y-30),text=item['name'],fill=WHITE,font=('Microsoft YaHei UI',11,'bold'))
    def snapshot(self):
        self.draft['name']=self.name.get()
        try:atomic_json(self.backend.runtime/'editor-draft.json',self.draft)
        except OSError:self.note.set('草稿暂存失败，请及时保存方案')
    def save(self):
        try:
            if not self.apply_properties():return
            self.draft=self.store.save(self.name.get(),self.draft['controls'],self.draft.get('id'),self.draft.get('sha256'))
            self.name_entry.configure(state='readonly');self.load_name.set(self.draft['name']);self.snapshot();self.refresh()
            self.note.set('已保存：'+self.draft['name']+'。在方案列表选择后可使用。')
            self.backend.event('方案已保存：'+self.draft['name'],'ok')
        except Exception as ex:self.note.set(str(ex))
    def use(self):
        if self.overlay:self.note.set('请先结束摆放，再使用方案');return
        if not self.draft.get('id'):self.note.set('先保存方案，再使用');return
        self.app.action('切换方案',lambda:self.backend.switch_profile(self.draft['id']))
    def finish(self,resume=None):
        if not self.overlay and not self.palette:return
        self.snapshot();self.dragging=None
        for window in (self.overlay,self.palette):
            if window is None:continue
            try:window.grab_release();window.destroy()
            except tk.TclError:pass
        self.overlay=None;self.palette=None;self.backend.editing_profile=False
        if hasattr(self.app,'mini'):self.app.mini.set_visible(self.app.mini_visible)
        self.app.show_main()
        self.note.set('已结束摆放，草稿已暂存；点击“保存方案”写入方案库。')
        if (self.resume_after if resume is None else resume) and not self.backend.config.get('input_disconnected'):
            self.app.action('恢复自动控制',lambda:self.backend.request_pad('start'))
    def shutdown(self):
        if self.overlay:self.finish(resume=False)
