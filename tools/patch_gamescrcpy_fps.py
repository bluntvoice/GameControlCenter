"""Create a soft-red FPS variant of the verified GameScrcpy v1.3.4 binary."""
import argparse
import hashlib
import json
from pathlib import Path


ORIGINAL_SHA256='28b7fb2e9beef8853e684b89aa1f67723ec1f203eedbe4f511bb31e3a0268a2c'
PATCHED_SHA256='b2423e87195a7de25100ea288706c62eb0572266a54ab347fd0b1f8bedcf810a'
ORIGINAL_STYLE=b'QLabel{color:#00FF00; background: rgba(0,0,0,128); padding: 2px 4px;}'
PATCHED_STYLE=ORIGINAL_STYLE.replace(b'#00FF00',b'#D96C6C')


def patch(source,output):
    source=Path(source);output=Path(output)
    if source.resolve()==output.resolve():raise ValueError('输出必须另存为新文件，保留原始 EXE')
    data=source.read_bytes()
    if hashlib.sha256(data).hexdigest()!=ORIGINAL_SHA256:
        raise ValueError('原始 EXE 的 SHA-256 不匹配，仅支持文档中核验过的 GameScrcpy v1.3.4 构建')
    if data.count(ORIGINAL_STYLE)!=1:raise ValueError('帧率标签样式不唯一，未生成补丁')
    updated=data.replace(ORIGINAL_STYLE,PATCHED_STYLE)
    if len(updated)!=len(data) or hashlib.sha256(updated).hexdigest()!=PATCHED_SHA256:
        raise ValueError('补丁结果校验失败，未生成文件')
    # Exclusive creation also preserves any previous output or hard-linked original.
    with output.open('xb') as file:file.write(updated)
    return dict(color='#D96C6C',original_sha256=ORIGINAL_SHA256,updated_sha256=PATCHED_SHA256,
        changed_bytes=sum(a!=b for a,b in zip(data,updated)),file_size=len(updated))


def main():
    parser=argparse.ArgumentParser(description='把已核验构建的 GameScrcpy 帧率标签改为柔和红色，另存 EXE。')
    parser.add_argument('source',type=Path,help='原始 GameScrcpy.exe')
    parser.add_argument('output',type=Path,help='不存在的新 EXE 路径')
    args=parser.parse_args()
    try:report=patch(args.source,args.output)
    except (OSError,ValueError) as error:parser.exit(1,str(error)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
