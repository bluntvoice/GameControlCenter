"""Owned ADB forward and independently identified app_process, no GameScrcpy changes."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import struct
import subprocess
import threading
import time

from app_config import project_root,load_config
ROOT=project_root()
CONFIG=load_config()
PHASE=ROOT/'phase2b-20261015'
ADB=Path(CONFIG['adb'])
SERIAL=CONFIG['serial']
NO_WINDOW=getattr(subprocess,'CREATE_NO_WINDOW',0)
COMMAND_CONTEXT=threading.local()

def run_command(command,**kwargs):
    """Allow Pause/Stop to cancel a slow connection command on its worker thread."""
    cancel=getattr(COMMAND_CONTEXT,'cancel',None)
    if cancel is None:return subprocess.run(command,**kwargs)
    timeout=kwargs.pop('timeout',10)
    if cancel.is_set():raise RuntimeError('连接操作已取消')
    if kwargs.pop('capture_output',False):kwargs.update(stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    started=time.monotonic()
    process=subprocess.Popen(command,**kwargs)
    try:
        while True:
            if cancel.is_set():raise RuntimeError('连接操作已取消')
            if time.monotonic()-started>=timeout:raise subprocess.TimeoutExpired(command,timeout)
            try:
                out,err=process.communicate(timeout=.1)
                return subprocess.CompletedProcess(command,process.returncode,out,err)
            except subprocess.TimeoutExpired:pass
    finally:
        if process.poll() is None:
            process.kill();process.communicate()

def adb(*args,timeout=10):
    p=run_command([str(ADB),'-s',SERIAL,*args],capture_output=True,
                     encoding='utf-8',errors='replace',timeout=timeout,creationflags=NO_WINDOW)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip())
    return p.stdout

def display_info():
    # The current GameScrcpy session mirrors display 0. Its actual delivered touches
    # are on LogicalDisplayId 0; the SurfaceFlinger virtual capture id is unrelated.
    text=adb('shell','dumpsys display')
    matches=re.findall(r'mOverrideDisplayInfo=DisplayInfo\{[^\n]*displayId 0,[^\n]*?real (\d+) x (\d+),[^\n]*rotation (\d+)',text)
    if not matches:
        matches=re.findall(r'mBaseDisplayInfo=DisplayInfo\{[^\n]*displayId 0,[^\n]*?real (\d+) x (\d+),[^\n]*rotation (\d+)',text)
    if len(matches)!=1: raise RuntimeError('无法唯一识别手机主屏，请确认手机连接正常后重试')
    w,h,rotation=map(int,matches[0])
    if w<=h: raise RuntimeError('手机当前为竖屏，请进入游戏横屏，等待投屏画面旋转后重试')
    return dict(display=0,width=w,height=h,rotation=rotation)

def touches_none():
    text=adb('shell','dumpsys input')
    m=re.search(r'TouchStatesByDisplay:\s*(.*?)(?:CursorStatesByDisplay:|DisplayIdToWindowMap:|Global monitors:)',text,re.S)
    if not m: raise RuntimeError('Unknown touch-state format')
    return m.group(1).strip()=='<no displays touched>',text

class NeutralRequired(RuntimeError):
    """The phone released stale input and requires an empty snapshot first."""

def receive(sock,length,deadline=None):
    data=b''
    while len(data)<length:
        try:part=sock.recv(length-len(data))
        except TimeoutError:
            if deadline is not None and time.monotonic()<deadline:continue
            raise
        if not part: raise ConnectionError('Touch companion disconnected')
        data+=part
    return data

class Transport:
    def __init__(self,case,info=None):
        self.info=info or display_info()
        self.folder=PHASE/'analog/evidence'/case
        self.folder.mkdir(parents=True,exist_ok=False)
        self.sock=None; self.proc=None; self.port=None; self.log=None
        self.remote=None
    def start(self):
        none,_=touches_none()
        if not none: raise RuntimeError('Existing phone touch; release it before starting')
        build=PHASE/'analog/build/pad-touch.jar'
        stock=ADB.parent/'scrcpy-server'
        sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
        self.remote='/data/local/tmp/gcpad-'+sha(build)[:12]+'.jar'
        remote_stock='/data/local/tmp/gcpad-stock-'+sha(stock)[:12]+'.jar'
        for local,remote in [(build,self.remote),(stock,remote_stock)]:
            # Reversible files only; never replace the running GameScrcpy server jar.
            adb('shell',f'if [ -f {remote} ]; then chmod 600 {remote}; fi')
            adb('push',str(local),remote)
            adb('shell',f'chmod 444 {remote}')
        token=secrets.token_hex(24)
        remote_port=secrets.randbelow(14000)+40000
        self.port=int(adb('forward','tcp:0',f'tcp:{remote_port}').strip())
        self.log=(self.folder/'android-server.log').open('w',encoding='utf-8')
        command=(f'CLASSPATH={self.remote}:{remote_stock} app_process / PadTouchServer '
                 f'{self.info["display"]} {self.info["width"]} {self.info["height"]} {remote_port} {token}')
        self.proc=subprocess.Popen([str(ADB),'-s',SERIAL,'shell',command],
                                   stdout=self.log,stderr=subprocess.STDOUT,creationflags=NO_WINDOW)
        try:
            for _ in range(40):
                if self.proc.poll() is not None:
                    raise RuntimeError('Android companion exited; inspect android-server.log')
                try:
                    sock=socket.create_connection(('127.0.0.1',self.port),timeout=.2)
                    sock.settimeout(.4); sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
                    auth=token.encode('ascii'); sock.sendall(struct.pack('>H',len(auth))+auth)
                    if receive(sock,4)!=b'GPC2': raise RuntimeError('Unexpected handshake')
                    self.sock=sock
                    break
                except (OSError,ConnectionError):
                    try: sock.close()
                    except UnboundLocalError: pass
                    time.sleep(.1)
            if not self.sock: raise RuntimeError('Touch companion startup timed out')
            (self.folder/'session.json').write_text(json.dumps(dict(**self.info,
                companion_sha256=sha(build),stock_sha256=sha(stock),serial=SERIAL,
                android_loopback_only=True,watchdog_ms=500),indent=2),encoding='utf-8')
        except BaseException:
            self.close(); raise
    def frame(self,points):
        if not self.sock: raise RuntimeError('Not connected')
        body=bytes([len(points)])+b''.join(struct.pack('>BHH',ident,*point) for ident,point in points.items())
        self.sock.sendall(struct.pack('>H',len(body))+body)
        # Keep exactly one in-flight snapshot. A brief missing ACK is not an
        # instruction to send/replay old frames or rebuild the ADB session.
        # The phone independently releases input after 500ms and rejects stale
        # nonempty input until we acknowledge the reset with an empty snapshot.
        ack=receive(self.sock,1,deadline=time.monotonic()+1.2)[0]
        if ack==255:raise NeutralRequired('通信抖动后触点已释放，请松键归中')
        if ack!=len(points): raise RuntimeError('Unexpected touch acknowledgement')
        return ack
    def close(self):
        errors=[]
        if self.sock:
            try:
                self.frame({}); self.sock.sendall(b'\0\0')
            except (OSError,RuntimeError) as ex:errors.append(str(ex))
            finally:
                self.sock.close(); self.sock=None
        if self.proc:
            try:
                try:self.proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.proc.terminate()
                    try:self.proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait(timeout=2)
            except (OSError,subprocess.TimeoutExpired) as ex:errors.append(str(ex))
            finally:self.proc=None
        if self.log: self.log.close(); self.log=None
        if self.port:
            try: adb('forward','--remove',f'tcp:{self.port}',timeout=3)
            except (OSError,RuntimeError,subprocess.TimeoutExpired) as ex:errors.append(str(ex))
            finally:self.port=None
        if errors:raise RuntimeError('；'.join(errors))
