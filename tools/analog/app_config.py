"""Shared, relocatable paths for source and packaged applications."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

def project_root():
    if getattr(sys,'frozen',False):
        exe=Path(sys.executable).resolve()
        return exe.parents[3] if exe.stem=='GameControlCenter' else exe.parents[2]
    return Path(__file__).resolve().parents[2]

def powershell_path():
    candidates=[Path(os.environ.get('LOCALAPPDATA',''))/'Programs/PowerShell/7/pwsh.exe',
                Path(os.environ.get('ProgramFiles','C:/Program Files'))/'PowerShell/7/pwsh.exe']
    resolved=shutil.which('pwsh')
    if resolved:candidates.append(Path(resolved))
    return next((str(p.resolve()) for p in candidates if p.is_file() and 'windowsapps' not in str(p).lower()),'')

def load_config(home=None):
    root=Path(home).resolve().parent if home else project_root()
    path=root/'control-center/config.json'
    value=json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    defaults=dict(version='0.3.0',mini_visible=False,labels_enabled=True,project=str(root),
        gamescrcpy='',antimicrox='',adb='',serial='',package='com.netease.party',
        powershell=powershell_path(),pythonw=str(Path(sys.executable).with_name('pythonw.exe')),
        antimicrox_settings=str(Path(os.environ.get('LOCALAPPDATA',''))/'antimicrox/antimicrox_settings.ini'),
        sample_seconds=2,fps_low_threshold=48,profile='超燃竞技场-三技能.json',profile_display_name='超燃竞技场-三技能')
    defaults.update(value)
    # Source and portable folders may be moved; never follow a previous machine's project path.
    defaults['project']=str(root)
    if defaults['gamescrcpy'] and not defaults['adb']:
        defaults['adb']=str(Path(defaults['gamescrcpy']).parent/'adb.exe')
    return defaults

def adapter_executable(config):
    packaged=Path(config['project'])/'tools/analog/GamePadAdapter.exe'
    return str(packaged) if packaged.is_file() else config['pythonw']

def validate_config(config):
    for key in ('gamescrcpy','adb','powershell'):
        if not Path(config.get(key,'')).is_file():raise ValueError('文件不存在：'+key)
    if not (Path(config['gamescrcpy']).parent/'scrcpy-server').is_file():
        raise ValueError('GameScrcpy 目录缺少 scrcpy-server，请选择完整解压的 GameScrcpy')
    if not config.get('serial','').strip():raise ValueError('请填写手机的 ADB 序列号或 IP:端口')
    shell=config['powershell']
    if 'windowsapps' in shell.lower():raise ValueError('请使用独立安装的 PowerShell 7，不使用 WindowsApps 别名')
    result=subprocess.run([shell,'-NoProfile','-Command',
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); $PSVersionTable.PSVersion.ToString()"],
        capture_output=True,encoding='utf-8',timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    version=result.stdout.strip()
    try:valid=result.returncode==0 and '-' not in version and tuple(map(int,version.split('.'))) >= (7,6,4)
    except ValueError:valid=False
    if not valid:raise ValueError('需要 PowerShell 7.6.4 或更新的稳定版本，当前读取为：'+version)

def ensure_configuration():
    """First-run setup only; it never contacts a phone or starts another application."""
    root=project_root();path=root/'control-center/config.json'
    if path.exists():return True
    import tkinter as tk
    from tkinter import filedialog,messagebox
    config=load_config();window=tk.Tk();window.title('手机游戏控制台 · 首次设置')
    window.resizable(False,False)
    fields={}
    labels=[('gamescrcpy','GameScrcpy.exe'),('serial','手机 ADB 序列号 / IP:端口'),('powershell','PowerShell 7 的 pwsh.exe'),
            ('antimicrox','AntiMicroX（可留空）'),('package','游戏包名（用于 FPS）')]
    tk.Label(window,text='选择已安装的软件并填写手机连接地址。设置保存在本地。',padx=15,pady=15).grid(row=0,columnspan=3)
    for row,(key,label) in enumerate(labels,1):
        tk.Label(window,text=label).grid(row=row,column=0,padx=10,pady=7,sticky='w')
        value=tk.StringVar(value=config[key]);fields[key]=value
        tk.Entry(window,textvariable=value,width=52).grid(row=row,column=1,pady=7)
        if key in ('gamescrcpy','powershell','antimicrox'):
            def browse(value=value):
                selected=filedialog.askopenfilename(parent=window,filetypes=[('Windows 程序','*.exe')])
                if selected:value.set(selected)
            tk.Button(window,text='浏览',command=browse).grid(row=row,column=2,padx=10)
    accepted=[]
    def save():
        try:
            config.update({k:v.get().strip() for k,v in fields.items()})
            config['adb']=str(Path(config['gamescrcpy']).parent/'adb.exe')
            validate_config(config)
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            phase=root/'phase2b-20261015'
            (phase/'analog').mkdir(parents=True,exist_ok=True);(phase/'evidence').mkdir(parents=True,exist_ok=True)
            settings=phase/'analog/settings.json'
            if not settings.exists():shutil.copy2(root/'defaults/adapter-settings.json',settings)
        except (OSError,ValueError,subprocess.SubprocessError) as error:
            messagebox.showerror('请检查设置',str(error),parent=window);return
        accepted.append(True);window.destroy()
    tk.Button(window,text='保存并打开控制台',command=save,padx=20,pady=7).grid(row=len(labels)+1,columnspan=3,pady=15)
    window.mainloop();return bool(accepted)
