# GameScrcpy 帧率配色补丁

将投屏左上角 FPS 标签由荧光绿 `#00FF00` 改为柔和红色 `#D96C6C`。保持原背景、字号和内边距。

这是可选的源码工具，需要 Python 3.12。控制台不会自动修改外部 GameScrcpy，仓库也不包含 GameScrcpy 的 EXE。

## 适用构建

仅支持已核验的 GameScrcpy v1.3.4 Windows EXE；同版本号的其他构建也可能不同，必须以完整 SHA-256 为准。

| 文件 | SHA-256 |
| --- | --- |
| 原始 EXE | `28b7fb2e9beef8853e684b89aa1f67723ec1f203eedbe4f511bb31e3a0268a2c` |
| 柔和红色 EXE | `b2423e87195a7de25100ea288706c62eb0572266a54ab347fd0b1f8bedcf810a` |

原始 EXE 大小为 4,315,648 字节。补丁只替换唯一 FPS 标签样式中的六个颜色字节，不改变文件长度。脚本在写入前核验原始哈希、样式唯一性及预期结果哈希，遇到不同构建或已存在的输出文件会退出。

## 使用

在源码仓库根目录运行；将示例路径改为自己的安装目录和输出位置：

```powershell
python ./tools/patch_gamescrcpy_fps.py 'D:/Game/GameScrcpy.v1.3.4/GameScrcpy.exe' 'D:/Game/GameScrcpy-soft-red.exe'
```

脚本始终另存新文件，保留输入 EXE，并输出颜色、哈希和变更字节数。若安装目录已应用补丁，请以保存的原始 EXE 为输入。

生成后退出 GameScrcpy，保留原始 EXE 备份，再用输出文件替换原安装目录的 `GameScrcpy.exe`。保持原目录内其他 DLL、ADB、配置和键位文件齐全，随后从原入口重启。

回退时退出 GameScrcpy，将原始 EXE 备份恢复为安装目录中的 `GameScrcpy.exe`。GameScrcpy 更新可能覆盖配色；新构建必须重新核验，不能去掉哈希检查强行应用。

已在本机原始文件上验证输出哈希、文件长度和六字节差异；实际显示观感仍待用户验收。
