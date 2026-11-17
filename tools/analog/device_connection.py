"""Resolve one phone across ADB service names and changing Wi-Fi endpoints."""
import re


def service_identity(name):
    name=name.split('._adb')[0]
    return name.rsplit('-',1)[0] if name.startswith('adb-') and name.count('-')>=2 else name


def connect_device(config,run,*,active_serial=None):
    devices=run('devices','-l').stdout.splitlines()
    online=[line.split()[0] for line in devices if len(line.split())>=2 and line.split()[1]=='device']
    services=[]
    try:discovered=run('mdns','services',timeout=3).stdout
    except RuntimeError:discovered=''
    for line in discovered.splitlines():
        parts=line.split()
        if len(parts)==3 and parts[1] in ('_adb._tcp.','_adb-tls-connect._tcp.'):
            services.append((service_identity(parts[0]),parts[1],parts[2],parts[0]))
    verified={}
    def identity(serial):
        return verified.get(serial,next((key for key,kind,address,name in services if serial==address or serial.startswith(name+'._adb')),
                    service_identity(serial)))
    groups={identity(serial) for serial in online}|{row[0] for row in services}
    configured=config['serial'];saved=config.get('device_identity')
    if saved:
        # ADB may keep a connected IP transport after mDNS advertisements disappear.
        # Verify the physical serial instead of either rejecting it or trusting its IP.
        if saved not in groups:
            for serial in online:
                try:hardware=run('-s',serial,'shell','getprop','ro.serialno',timeout=3)
                except RuntimeError:continue
                reported=hardware.stdout.strip()
                if hardware.returncode==0 and reported and reported.lower() not in ('unknown','null') and saved in (reported,'adb-'+reported):
                    verified[serial]=saved
                    groups.add(saved)
        if saved not in groups:raise RuntimeError('未发现已选择的手机，请检查手机 WiFi 与无线调试')
        selected=saved
    elif identity(configured) in groups:selected=identity(configured)
    elif len(groups)==1:selected=next(iter(groups))
    elif len(groups)>1:raise RuntimeError('发现多台手机，请明确选择要连接的设备，未自动切换')
    else:selected=identity(configured)
    candidates=[]
    if active_serial in online and identity(active_serial)==selected:candidates.append(active_serial)
    # GameScrcpy 1.3.4 routes IP:port through lossy UDP video. An online mDNS
    # alias uses ADB/TCP, while phone_address independently supplies the visible IP.
    candidates.extend(serial for serial in online if '._adb' in serial and identity(serial)==selected)
    if configured in online and identity(configured)==selected:candidates.append(configured)
    # Keep IP endpoints as fallbacks when the ADB service alias is unavailable.
    candidates.extend(address for key,kind,address,name in services if key==selected and kind=='_adb._tcp.')
    candidates.extend(address for key,kind,address,name in services if key==selected and kind=='_adb-tls-connect._tcp.')
    candidates.extend(serial for serial in online if identity(serial)==selected)
    if not candidates:candidates=[configured]
    detail='未发现在线设备'
    for serial in dict.fromkeys(candidates):
        try:
            if serial not in online and ':' in serial and '._adb' not in serial:
                run('connect',serial,timeout=4)
            state=run('-s',serial,'get-state',timeout=3)
            if state.returncode!=0 and 'offline' in (state.stderr+state.stdout).lower() and '._adb' not in serial:
                run('disconnect',serial,timeout=3)
                run('connect',serial,timeout=4)
                state=run('-s',serial,'get-state',timeout=3)
        except RuntimeError as error:
            detail=str(error);continue
        if state.returncode==0 and state.stdout.strip()=='device':
            address=serial if re.fullmatch(r'[\d.]+:\d+',serial) else next(
                (address for key,kind,address,name in services if key==selected and kind=='_adb-tls-connect._tcp.'),serial)
            return dict(serial=serial,phone_address=address,device_identity=selected)
        detail=(state.stderr or state.stdout).strip()
        if 'unauthorized' in detail.lower():raise RuntimeError('手机尚未授权调试，请在手机上允许此电脑连接')
    raise RuntimeError('手机仍未在线：'+detail[:180]+'；请检查手机 WiFi 与无线调试')
