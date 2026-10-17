# 第三方组件

本项目的 MIT 许可仅适用于本项目原创代码，不替代第三方组件的许可。

| 组件 | 用途 | 许可与位置 |
| --- | --- | --- |
| Lucide `gamepad-2` | 软件图标 | ISC 等原始许可；完整文本见 `control-center/assets/lucide/LICENSE` |
| Python 3.12 | Release 中的 Python 运行环境及标准库 | PSF 等许可；发行包中的 `PYTHON-LICENSE.txt` |
| Tcl/Tk | 图形界面 | 发行包的 `TCL-LICENSE.txt`，以及对应运行目录 `_internal/_tk_data/license.terms` |
| PyInstaller | 构建工具及运行引导程序 | GPL-2.0-or-later，附带分发例外；见发行包的 `PYINSTALLER-COPYING.txt` |
| Pillow、fontTools | 构建时生成图标，不作为应用依赖收集 | 各自项目许可，见依赖发行版 |
| Eclipse ECJ、Google R8 | 构建 Android 触控组件 | 构建工具不随应用分发；分别遵循 Eclipse 和 Google 的原始许可 |

GameScrcpy 和它的 `scrcpy-server`、ADB，以及 PowerShell、AntiMicroX 均为外部软件。本仓库不包含它们的完整发行文件；运行时从用户选择的安装目录调用。Android 触控组件在手机上通过反射使用该 GameScrcpy 版本提供的类，因此不同 GameScrcpy 版本可能不兼容。

项目链接：[Lucide](https://github.com/lucide-icons/lucide)、[Python](https://www.python.org/)、[PyInstaller](https://github.com/pyinstaller/pyinstaller)、[GameScrcpy](https://github.com/NuoRan/GameScrcpy)。

Tcl 许可原文：[tcltk/tcl · core-8-6-15](https://github.com/tcltk/tcl/blob/core-8-6-15/license.terms)，源码副本保存在 `tools/licenses/TCL-LICENSE.txt`。
