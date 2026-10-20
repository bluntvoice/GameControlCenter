import csv
import configparser
from datetime import datetime,timezone,timedelta
import json
import os
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import traceback

import winprobe
from video_layout import VideoLayoutMemory
from phoneprobe import Phone
if not getattr(sys,'frozen',False):sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/analog'))
from profile_store import ProfileStore
from app_config import load_config,adapter_executable

ZONE=timezone(timedelta(hours=8))
def stamp(): return datetime.now(ZONE).isoformat(timespec='seconds')
def read_json(path,default=None):
    try: return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError,ValueError): return default
def atomic_json(path,data):
    path=Path(path); temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(temp,path)

def center_home():
    if getattr(sys,'frozen',False): return Path(sys.executable).resolve().parents[2]
    return Path(__file__).resolve().parents[1]

# 当前输入通路：适配器独立处理按钮和双摇杆，直接发送多点触控。
# AntiMicroX 仅为备用；不能把已放弃的“合并方案”重新加入日常启动链路。

class Tracker:
    def __init__(self): self.handles={}; self.misses={}; self.exits={}
    def observe(self,key,pid,window=None):
        existing=self.handles.get(key)
        if existing and not existing.alive():
            code=existing.exit_code()
            self.exits[key]=dict(code=code,at=time.time(),pid=existing.pid)
            existing.close(); del self.handles[key]; existing=None
        if pid and (existing is None or existing.pid!=pid):
            if existing: existing.close()
            self.handles[key]=winprobe.Process(pid); self.exits.pop(key,None)
        result=dict(pid=pid,running=bool(pid),state='未启动',tone='muted',hwnd=window['hwnd'] if window else None)
        if pid:
            if window:
                good=winprobe.responds(window['hwnd'])
                self.misses[key]=0 if good else self.misses.get(key,0)+1
                if self.misses[key]>=3: result.update(state='疑似卡住',tone='bad')
                elif not good: result.update(state='窗口响应超时',tone='warn')
                else: result.update(state='运行中',tone='ok')
            else: result.update(state='后台运行',tone='ok'); self.misses[key]=0
        elif key in self.exits:
            exit=self.exits[key]; code=exit['code']
            result.update(state='已退出' if code==0 else '异常退出' if code is not None else '已退出（原因待核实）',
                          tone='muted' if code==0 else 'bad',exit_code=code)
        return result
    def close(self):
        for handle in self.handles.values(): handle.close()

class Center:
    def __init__(self,home=None):
        self.home=Path(home) if home else center_home()
        self.config=load_config(self.home)
        if not self.config: raise RuntimeError('找不到控制台 config.json')
        self.project=Path(self.config['project'])
        self.analog=self.project/'phase2b-20261015/analog'
        self.phase=self.project/'phase2b-20261015'
        self.profiles=ProfileStore(self.project,Path(self.config['gamescrcpy']).parent/'keymap')
        self.profiles.ensure();self.editing_profile=False
        self.runtime=self.home/'runtime'; self.runtime.mkdir(parents=True,exist_ok=True)
        self.session=self.home/'logs'/datetime.now(ZONE).strftime('%Y%m%d-%H%M%S-%f')
        self.session.mkdir(parents=True,exist_ok=False)
        self.stop=threading.Event(); self.lock=threading.RLock()
        self.updates=queue.Queue(); self.events=[]; self.local={}; self.phone={}; self.series=[]
        self.busy=False; self.action=''; self.phone_probe=Phone(self.config)
        self.tracker=Tracker(); self.fps_process=None; self.last_signatures={}; self.low_count=0
        self.controller=None; self.input_lock=threading.RLock()
        self.video_layout=VideoLayoutMemory(self.config.get('video_window_layout'))
        self.helper_stop=self.runtime/f'fps-{os.getpid()}.stop'
        self.known_pids={}; self.last_log_path=None; self.log_offset=0
        self.csv_file=(self.session/'samples.csv').open('w',encoding='utf-8-sig',newline='')
        self.csv=csv.DictWriter(self.csv_file,fieldnames=['time','screen_fps','game_fps','game_frame_p95_ms',
             'phone_connected','battery_percent','battery_celsius','controller_count','gamescrcpy_state',
             'adapter_state','labels_state','antimicrox_state','adapter_channel_round_trip_ms','decoder_errors'])
        self.csv.writeheader(); self.csv_file.flush()
        self.event('控制台已打开，开始记录连接与帧率','info')
        self.threads=[]
    def event(self,message,kind='info',**data):
        record=dict(time=stamp(),kind=kind,message=message,**data)
        with self.lock:
            self.events.append(record); self.events=self.events[-120:]
            with (self.session/'events.jsonl').open('a',encoding='utf-8') as file:
                file.write(json.dumps(record,ensure_ascii=False)+'\n')
        self.updates.put(('event',record))
    def start(self):
        self.start_fps_watch()
        for target in [self.poll_local,self.poll_phone,self.poll_diagnostics]:
            thread=threading.Thread(target=target,daemon=True); self.threads.append(thread); thread.start()
    def ps(self,script,*args,timeout=12):
        cmd=[self.config['powershell'],'-NoProfile','-File',str(script),*map(str,args)]
        # Launched background apps can inherit the shell's output handles. Pipes
        # make communicate() wait for those apps even after PowerShell has exited.
        with tempfile.TemporaryFile() as output,tempfile.TemporaryFile() as errors:
            result=subprocess.run(cmd,stdout=output,stderr=errors,
                timeout=timeout,creationflags=subprocess.CREATE_NO_WINDOW)
            output.seek(0);errors.seek(0)
            stdout=output.read().decode('utf-8-sig',errors='replace')
            stderr=errors.read().decode('utf-8-sig',errors='replace')
        if result.returncode: raise RuntimeError((stderr or stdout).strip()[:300])
        return stdout.strip()
    def start_fps_watch(self):
        log=(self.session/'fps-watch.log').open('w',encoding='utf-8')
        self.fps_process=subprocess.Popen([self.config['powershell'],'-NoProfile','-File',
            str(self.home/'src/fps_watch.ps1'),'-OutputPath',str(self.runtime/'fps.json'),
            '-OwnerId',str(os.getpid()),'-StopPath',str(self.helper_stop)],stdout=log,stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW)
        log.close()
    def pid_file(self,path,expected_path):
        try:
            pid=int(path.read_text(encoding='utf-8-sig').strip())
            process=winprobe.Process(pid)
            valid=(process.alive() and process.path.lower()==str(expected_path).lower()
                   and 0<=path.stat().st_mtime-process.created<35)
            process.close(); return pid if valid else None
        except (OSError,ValueError): return None
    def snapshot_local(self):
        config=self.config
        matches={}
        for pid,name in winprobe.process_list({'gamescrcpy.exe','antimicrox.exe'}):
            proc=winprobe.Process(pid)
            for key in ['gamescrcpy','antimicrox']:
                if proc.path.lower()==config[key].lower(): matches[key]=pid
            proc.close()
        matches['adapter']=self.pid_file(self.analog/'adapter.pid',adapter_executable(config))
        matches['labels']=self.labels_pid()
        windows=winprobe.windows(); result={}
        self.remember_video_window(windows,matches.get('gamescrcpy'))
        titles={'gamescrcpy':lambda s:s.startswith('Phone - ') or s=='GameScrcpy',
                'adapter':lambda s:s=='双摇杆模拟触控 · 超燃竞技场样本',
                'labels':lambda s:s.startswith('手柄名称提示'),
                'antimicrox':lambda s:s=='AntiMicroX'}
        for key in ['gamescrcpy','adapter','labels','antimicrox']:
            pid=matches.get(key)
            options=[window for window in windows if window['pid']==pid and titles[key](window['title'])]
            window=next((w for w in options if w['title'].startswith('Phone - ')),options[0] if options else None)
            result[key]=self.tracker.observe(key,pid,window)
            if pid: self.known_pids[pid]=key
        adapter=read_json(self.analog/'status.json',{})
        if result['adapter']['running']:
            age=time.time()-(self.analog/'status.json').stat().st_mtime if (self.analog/'status.json').exists() else 999
            if adapter.get('pid')==result['adapter']['pid'] and age<3:
                if result['adapter']['tone']!='bad':
                    state=('自动重连中' if adapter.get('recovery_pending') else
                           '发送挂起' if adapter.get('focus_suspended') else
                           '恢复输入中' if adapter.get('armed') and adapter.get('neutral_wait') else
                           '输入控制中' if adapter.get('armed') else
                           '等待投屏前台' if adapter.get('auto_on_foreground') and not adapter.get('manual_pause') else '已暂停')
                    result['adapter'].update(state=state,tone='warn' if adapter.get('recovery_pending') else 'ok')
                result['adapter']['detail']=adapter.get('status','')
                result['adapter']['channel_ms']=adapter.get('last_round_trip_ms')
            elif age>5: result['adapter'].update(state='状态更新中断',tone='warn')
        result['adapter']['armed']=bool(adapter.get('armed')) and result['adapter']['running'] and time.time()-(self.analog/'status.json').stat().st_mtime<3
        fps=read_json(self.runtime/'fps.json',{})
        result['screen_fps']=fps.get('fps') if (time.time()-fps.get('at',0)<3.5 and
            fps.get('gamescrcpy_pid')==matches.get('gamescrcpy') and result['gamescrcpy']['tone']!='bad') else None
        result['fps_source']=fps.get('state','采样启动中')
        result['video_window']=any(w['pid']==matches.get('gamescrcpy') and w['title']=='Phone - '+config['serial'] for w in windows)
        result['video_minimized']=any(w['pid']==matches.get('gamescrcpy') and w['title']=='Phone - '+config['serial'] and w['minimized'] for w in windows)
        result['controllers']=self.read_controllers()
        result['input_disconnected']=bool(self.config.get('input_disconnected'))
        if result['input_disconnected']:
            result['adapter'].update(state='停止连接中' if result['adapter']['running'] else '已停止连接',
                tone='warn' if result['adapter']['running'] else 'muted',armed=False,
                detail='不读取手柄；点击“恢复连接”重新启用')
        return result
    def read_controllers(self):
        # The stop action waits for an in-flight read before it acknowledges.
        with self.input_lock:
            if self.config.get('input_disconnected'):return []
            if self.controller is None:self.controller=winprobe.Controller()
            return self.controller.read()
    def set_input_disconnected(self,value):
        with self.input_lock:
            self.save_preference('input_disconnected',bool(value))
            with self.lock:
                self.local['input_disconnected']=bool(value)
                if value:self.local['controllers']=[]
    def stop_connection(self):
        # Persist first: a failed shutdown must not restart monitoring next launch.
        self.set_input_disconnected(True)
        self.request_pad('quit')
        self.event('已停止连接：后台适配器已退出，控制台不再读取手柄；界面与托盘保留','ok')
    def remember_video_window(self,windows,pid):
        if self.editing_profile:return
        video=next((w for w in windows if pid and w['pid']==pid and
                    w['title']=='Phone - '+self.config['serial']),None)
        hwnd=video['hwnd'] if video else None
        saved=self.video_layout.saved if hwnd!=self.video_layout.handle else None
        geometry=winprobe.video_geometry(hwnd,saved) if hwnd else None
        action=self.video_layout.observe(hwnd,geometry,time.monotonic())
        if not action:return
        kind,value=action
        if kind=='save':self.save_preference('video_window_layout',value)
        elif winprobe.restore_video_geometry(hwnd,value):
            self.event('已恢复投屏窗口位置与大小','info')
        else:
            self.video_layout.handle=None
            self.event('投屏窗口布局恢复失败，下次采样重试','warn')
    def labels_pid(self):
        source=self.phase/'evidence/controller-labels.pid'
        try:
            pid=int(source.read_text(encoding='utf-8-sig').strip())
            process=winprobe.Process(pid)
            try:
                return pid if (process.alive() and Path(process.path).name.lower()=='pwsh.exe'
                    and 0<=source.stat().st_mtime-process.created<35) else None
            finally:process.close()
        except (ValueError,OSError):return None
    def save_preference(self,key,value):
        self.save_preferences({key:value})
    def save_preferences(self,values):
        with self.lock:
            self.config.update(values)
            atomic_json(self.home/'config.json',self.config)
    def toggle_labels(self):
        enabled=not bool(self.labels_pid())
        self.set_labels(enabled)
        self.save_preference('labels_enabled',enabled)
        self.event('手柄名称提示已'+('开启' if enabled else '关闭'),'ok')
    def set_labels(self,enabled):
        pid=self.labels_pid()
        if enabled:
            if pid:return
            log=(self.session/'labels-launch.log').open('a',encoding='utf-8')
            subprocess.Popen([self.config['powershell'],'-NoProfile','-STA','-File',
                str(self.project/'tools/phase2b_controller_labels.ps1')],cwd=self.project,
                stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW);log.close()
            deadline=time.monotonic()+6
            while time.monotonic()<deadline:
                live_pid=self.labels_pid()
                if live_pid and any(w['pid']==live_pid and w['title'].startswith('手柄名称提示') for w in winprobe.windows()):return
                if self.stop.wait(.1):return
            raise RuntimeError('提示层尚未启动，请查看运行记录')
        elif pid:
            process=winprobe.Process(pid)
            try:
                window=next((w for w in winprobe.windows() if w['pid']==pid and w['title'].startswith('手柄名称提示')),None)
                if not window:raise RuntimeError('提示层窗口尚未就绪，请稍后再试')
                winprobe.user.PostMessageW.argtypes=[winprobe.W.HWND,winprobe.W.UINT,winprobe.W.WPARAM,winprobe.W.LPARAM]
                winprobe.user.PostMessageW(window['hwnd'],0x10,0,0)
                deadline=time.monotonic()+5
                while process.alive() and time.monotonic()<deadline:
                    if self.stop.wait(.1):return
                if process.alive():raise RuntimeError('提示层尚未确认关闭')
            finally:process.close()
    def poll_local(self):
        while not self.stop.is_set():
            try:
                sample=self.snapshot_local()
                with self.lock:
                    if self.config.get('input_disconnected'):
                        sample['controllers']=[];sample['input_disconnected']=True
                    self.local=sample
                for key in ['gamescrcpy','adapter','labels','antimicrox']:
                    entry=sample[key]; signature=(entry['state'],entry.get('pid'),entry.get('exit_code'))
                    if self.last_signatures.get(key)!=signature:
                        self.last_signatures[key]=signature
                        name=dict(gamescrcpy='投屏软件',adapter='双摇杆适配器',labels='手柄提示层',antimicrox='AntiMicroX 备用')[key]
                        suffix=f"，退出码 {entry['exit_code']:#x}" if entry.get('exit_code') is not None else ''
                        self.event(name+'：'+entry['state']+suffix,entry['tone'],component=key)
                connected=len(sample['controllers'])
                if self.last_signatures.get('controller')!=connected:
                    self.last_signatures['controller']=connected
                    self.event('已停止手柄检测' if sample.get('input_disconnected') else '手柄已连接' if connected else '手柄未连接',
                               'muted' if sample.get('input_disconnected') else 'ok' if connected else 'warn')
                self.updates.put(('local',sample))
            except Exception as ex: self.event('本机状态采样失败：'+str(ex),'warn')
            self.stop.wait(1)
    def poll_phone(self):
        while not self.stop.is_set():
            try:
                sample=self.phone_probe.sample()
                with self.lock:
                    self.phone=sample; local=dict(self.local)
                if self.last_signatures.get('phone')!=sample['connected']:
                    self.last_signatures['phone']=sample['connected']
                    self.event('手机已连接' if sample['connected'] else '手机连接中断','ok' if sample['connected'] else 'warn')
                row=dict(time=stamp(),screen_fps=local.get('screen_fps'),game_fps=sample.get('fps'),
                    game_frame_p95_ms=sample.get('p95_ms'),phone_connected=sample['connected'],
                    battery_percent=(sample.get('battery') or {}).get('percent'),
                    battery_celsius=(sample.get('battery') or {}).get('temperature'),
                    controller_count=len(local.get('controllers',[])),
                    gamescrcpy_state=local.get('gamescrcpy',{}).get('state'),
                    adapter_state=local.get('adapter',{}).get('state'),labels_state=local.get('labels',{}).get('state'),
                    antimicrox_state=local.get('antimicrox',{}).get('state'),
                    adapter_channel_round_trip_ms=local.get('adapter',{}).get('channel_ms'),decoder_errors=self.read_decoder_errors())
                with self.lock:
                    self.series.append(row); self.series=self.series[-180:]
                    self.csv.writerow(row); self.csv_file.flush()
                active=(sample.get('fps') is not None and sample['fps']>5 and
                        local.get('video_window') and not local.get('video_minimized'))
                self.low_count=self.low_count+1 if active and row['screen_fps'] is not None and row['screen_fps']<self.config['fps_low_threshold'] else 0
                if self.low_count==3: self.event('投屏 FPS 持续低于 '+str(self.config['fps_low_threshold']),'warn')
                self.updates.put(('phone',sample))
                atomic_json(self.runtime/'status.json',dict(at=stamp(),local=local,phone=sample,log_folder=str(self.session)))
            except Exception as ex: self.event('手机采样失败：'+str(ex),'warn')
            self.stop.wait(self.config.get('sample_seconds',2))
    def read_decoder_errors(self):
        log_folder=Path(self.config['gamescrcpy']).parent/'logs'
        logs=sorted(log_folder.glob('*.log'),key=lambda p:p.stat().st_mtime)
        if not logs: return 0
        path=logs[-1]
        if path!=self.last_log_path:
            self.last_log_path=path; self.log_offset=path.stat().st_size; return 0
        size=path.stat().st_size
        if size<self.log_offset: self.log_offset=0
        with path.open('rb') as file:
            file.seek(max(self.log_offset,size-512000)); data=file.read()
            self.log_offset=file.tell()
        return data.count(b'[ERROR]')
    def poll_diagnostics(self):
        since=datetime.now(timezone.utc).isoformat()
        while not self.stop.wait(15):
            try:
                output=self.ps(self.home/'src/read_events.ps1','-Since',since,timeout=8)
                records=json.loads(output or '[]')
                for record in records:
                    record_id=record.get('record_id')
                    if record_id in self.last_signatures: continue
                    self.last_signatures[record_id]=True
                    pid=record.get('pid')
                    if pid in self.known_pids:
                        self.event('Windows 记录了 '+('程序崩溃' if record['event_id']==1000 else '程序无响应')+'：'+record.get('app',''),
                                   'bad',windows_event=record,component=self.known_pids[pid])
            except Exception as ex:
                if not self.last_signatures.get('events_unavailable'):
                    self.last_signatures['events_unavailable']=True
                    self.event('Windows 异常日志暂不可读；进程退出和窗口响应监测仍继续','warn')
    def action_async(self,name,function):
        with self.lock:
            if self.busy: return
            self.busy=True; self.action=name
        self.updates.put(('action',name))
        def run():
            try: function(); self.event(name+'完成','ok')
            except Exception as ex: self.event(name+'失败：'+str(ex),'bad')
            finally:
                with self.lock: self.busy=False; self.action=''
                self.updates.put(('action',''))
        threading.Thread(target=run,daemon=True).start()
    def open_component(self,key,show=True):
        with self.lock: record=dict(self.local.get(key,{}))
        if key=='adapter':
            if self.config.get('input_disconnected'):raise RuntimeError('连接已停止，请点击“恢复连接”')
            self.ps(self.project/'tools/analog/launch.ps1',*(['-ShowWindow'] if show else []));return
        if key=='labels':
            self.set_labels(True);return
        if key=='antimicrox':
            self.request_pad('pause')
            self.event('已暂停主输入通路，备用软件可单独使用','info')
        # Resolve the live process even before the first monitor sample arrives.
        for pid,_ in winprobe.process_list({Path(self.config[key]).name.lower()}):
            process=winprobe.Process(pid)
            same=process.path.lower()==self.config[key].lower();process.close()
            if same:
                options=[w for w in winprobe.windows() if w['pid']==pid]
                window=next((w for w in options if w['title'].startswith('Phone - ')),
                            next((w for w in options if w['title'] in ('GameScrcpy','AntiMicroX')),None))
                if window:winprobe.show(window['hwnd'])
                return
        executable=Path(self.config[key]); subprocess.Popen([str(executable)],cwd=executable.parent,
            creationflags=subprocess.CREATE_NO_WINDOW)
    def connect_phone(self):
        serial=self.config['serial']
        def run(*args,timeout=8):
            try:
                return subprocess.run([self.config['adb'],*args],capture_output=True,
                    encoding='utf-8',errors='replace',timeout=timeout,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            except subprocess.TimeoutExpired as ex:
                raise RuntimeError('手机连接超时，请检查手机 WiFi 与无线调试是否开启') from ex
        for attempt in range(2):
            result=run('connect',serial)
            state=run('-s',serial,'get-state',timeout=3)
            # "already connected" can refer to a stale OFFLINE transport.
            # Only the device state is evidence that ADB is ready to use.
            if state.returncode==0 and state.stdout.strip()=='device':
                self.event('手机已连接并确认在线：'+serial,'ok');return
            detail=(state.stderr or state.stdout or result.stderr or result.stdout).strip()
            if 'unauthorized' in detail.lower():
                raise RuntimeError('手机尚未授权调试，请在手机上允许此电脑连接')
            if attempt==0:
                self.event('手机会话未在线，正在清除旧连接并重连：'+serial,'info')
                # Scope recovery to this phone; preserve other ADB devices and servers.
                run('disconnect',serial,timeout=3)
        raise RuntimeError('手机仍未在线：'+detail[:180]+'；请确认同一 WiFi、无线调试已开启，地址与端口未变化')
    def switch_profile(self,ident):
        if self.editing_profile:raise RuntimeError('请先保存或结束方案编辑，再切换方案')
        self.profiles.load(ident)  # Verify the target before interrupting current input.
        status=read_json(self.analog/'status.json',{})
        resume=not self.config.get('input_disconnected') and not status.get('manual_pause',False)
        self.request_pad('pause')
        entry=self.profiles.select(ident)
        self.save_preferences(dict(profile=Path(entry['path']).name,profile_display_name=entry['name']))
        if resume:self.request_pad('start')
        self.event('当前方案：'+entry['name']+'；'+('切回投屏继续当前摇杆方向' if resume else '保持手动暂停'),'ok')
    def editor_surface(self):
        videos=[w for w in winprobe.windows() if w['title']=='Phone - '+self.config['serial'] and w['visible'] and not w['minimized']]
        if len(videos)!=1:raise RuntimeError('请先打开唯一的横屏投屏窗口，并退出最小化')
        video=videos[0]
        process=winprobe.Process(video['pid'])
        try:
            if process.path.lower()!=self.config['gamescrcpy'].lower():raise RuntimeError('投屏窗口来源不匹配')
        finally:process.close()
        self.request_pad('pause')
        output=self.ps(self.project/'tools/analog/video_surface.ps1','-VideoHandle',video['hwnd'])
        from pad_transport import display_info
        info=display_info()
        return dict(video=video['hwnd'],surface=int(json.loads(output)['handle']),width=info['width'],height=info['height'])
    def prepare(self):
        try: self.connect_phone()
        except Exception as ex: self.event('手机尚未连通：'+str(ex),'warn')
        self.open_component('gamescrcpy'); self.request_pad('start')
        self.set_labels(self.config.get('labels_enabled',True))
        self.event('软件已准备。切回投屏按当前摇杆方向继续；已按住按钮须松开再按。Start 已释放','info')
    def request_pad(self,command):
        if command=='start' and self.config.get('input_disconnected'):
            self.set_input_disconnected(False)
            try:return self.request_pad(command)
            except Exception:
                self.set_input_disconnected(True)
                try:self.request_pad('quit')
                except Exception as cleanup:self.event('恢复失败，后台适配器尚待退出：'+str(cleanup),'bad')
                raise
        pid=self.pid_file(self.analog/'adapter.pid',adapter_executable(self.config))
        if not pid:
            if command in ('pause','quit'): return
            self.open_component('adapter',show=False)
            for _ in range(40):
                if self.stop.wait(.1): raise RuntimeError('恢复连接已中止')
                pid=self.pid_file(self.analog/'adapter.pid',adapter_executable(self.config))
                if pid: break
            if not pid: raise RuntimeError('适配器尚未启动')
        if command!='quit':
            winprobe.user.AllowSetForegroundWindow.argtypes=[winprobe.W.DWORD]
            winprobe.user.AllowSetForegroundWindow(pid)
        request_id=secrets.token_hex(12)
        atomic_json(self.analog/'control-request.json',dict(id=request_id,command=command,at=time.time()))
        if command=='quit':
            process=winprobe.Process(pid)
            try:
                deadline=time.monotonic()+9
                while process.alive() and time.monotonic()<deadline:
                    if self.stop.wait(.1):raise RuntimeError('停止连接尚未完成')
                if process.alive():raise RuntimeError('后台适配器尚未退出，请重试“停止连接”；手柄检测已停止')
            finally:process.close()
            return
        deadline=time.monotonic()+9
        while time.monotonic()<deadline:
            if self.stop.wait(.15): raise RuntimeError('连接操作已中止')
            status=read_json(self.analog/'status.json',{})
            if status.get('pid')!=pid or status.get('control_request_id')!=request_id: continue
            if command=='pause' and not status.get('armed') and not status.get('channel_active'): return
            if command=='start' and status.get('armed'): return
            if command=='start' and status.get('auto_on_foreground') and not status.get('manual_pause'):return
            if command=='start' and status.get('status','').startswith('已暂停'):
                raise RuntimeError(status['status'])
        raise RuntimeError('适配器尚未确认操作，请查看其窗口状态')
    def close(self):
        self.stop.set(); self.helper_stop.write_text('stop',encoding='utf-8')
        if self.fps_process:
            try: self.fps_process.wait(timeout=2)
            except subprocess.TimeoutExpired: self.fps_process.terminate()
        # Leave the user's game and related apps running. The monitor owns only its probe.
        with self.lock:
            self.event('控制台已关闭，停止记录','info')
            self.csv_file.flush()
