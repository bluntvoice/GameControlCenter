# GameControlCenter · 手机游戏控制台

[![版本](https://img.shields.io/github/v/release/bluntvoice/GameControlCenter?label=%E7%89%88%E6%9C%AC&color=2563eb)](https://github.com/bluntvoice/GameControlCenter/releases/latest)
[![下载量](https://img.shields.io/github/downloads/bluntvoice/GameControlCenter/total?label=%E4%B8%8B%E8%BD%BD%E9%87%8F&color=16a34a)](https://github.com/bluntvoice/GameControlCenter/releases)

在 Windows 上通过 GameScrcpy 玩手机游戏，使用手柄双摇杆和鼠标操作，并在一个控制台里管理启动、按键方案和运行状态。

这个项目从个人使用需求中整理而来：左摇杆保留连续方向和推动幅度，右摇杆直接拖动游戏视角；手柄与鼠标共用触控通道，减少来回暂停适配器的操作。

## 能做什么

- **启动与监测**：一键准备 GameScrcpy、双摇杆适配器和按键标识，也可分别打开。查看手机、手柄和程序状态，提示进程退出及窗口响应超时。
- **手柄与鼠标并用**：支持 XInput 手柄、模拟双摇杆、鼠标左右键。同一个游戏位置可以绑定多个不同按键。
- **拖放制作方案**：把按键拖到投屏内，按有效画面比例保存位置；可调点击覆盖范围、摇杆行程和视角速度。
- **四种触发方式**：按住、单次点击、连续点击、按住瞄准。普通类型只触发一次按下过程；连续点击默认每秒 10 次。
- **悬浮窗与托盘**：查看必要状态、切换方案、开关按键标识、恢复自动控制。主界面默认同时保留任务栏和托盘入口，手动关闭窗口后仅留托盘。
- **停止连接**：主界面或托盘中点击后退出后台输入适配器，停止控制台读取手柄，保留界面与托盘并记忆停止状态；点击“恢复连接”或“一键准备”重新启用。普通“暂停控制”仍保留手柄检测。此操作不禁用手柄，不影响其他游戏，也不关闭独立运行的投屏或备用软件。
- **电量与帧率记录**：查看手机电量、温度和充电状态，记录投屏及游戏画面帧率、连接变化和异常事件。
- **投屏窗口记忆**：控制台运行时自动记住普通投屏窗口的位置和大小，重连后恢复；最小化、最大化和全屏不会覆盖记录。显示器变化时让窗口保持在可见区域，手机旋转时按画面比例适配，不修改串流码率或分辨率。
- **柔和红色帧率**：提供可选的 [GameScrcpy FPS 配色补丁](docs/GAMESCRCPY_FPS_COLOR.md)，供已核验的 v1.3.4 构建另存生成柔和红色版本。

## 下载与运行

从 [Releases](https://github.com/bluntvoice/GameControlCenter/releases) 下载 `GameControlCenter-0.3.0-windows-x64.zip`，完整解压到可写目录。请保留整个文件夹，不能只复制一个 EXE。

需要先准备：

| 项目 | 要求 |
| --- | --- |
| 电脑 | Windows x64；目前实测环境为 Windows 10 |
| 投屏软件 | 单独安装 [GameScrcpy](https://github.com/NuoRan/GameScrcpy)，目前适配 v1.3.4；目录中需包含 `adb.exe` 和 `scrcpy-server` |
| PowerShell | 7.6.4 或更新的稳定版本，使用独立安装的 `pwsh.exe`；[安装说明](https://learn.microsoft.com/powershell/scripting/install/install-powershell-on-windows) |
| 手机 | 开启并授权 ADB 调试；目前实测为小米 Android 17，其他设备尚待验证 |
| 手柄 | 支持 XInput 的手柄；仅使用鼠标时可以不连接手柄 |

Release 已包含控制台和适配器所需的 Python 运行环境，无需另装 Python。AntiMicroX 为可选的备用软件，日常使用无需安装。

1. 打开解压目录中的 `control-center/releases/0.3.0/GameControlCenter.exe`。
2. 首次运行时，选择 GameScrcpy 和 PowerShell，填写手机 ADB 序列号或无线调试的 `IP:端口`。USB 序列号可通过 `adb devices` 查看。
3. 在 GameScrcpy 建立投屏后，点控制台的“一键准备”，让横屏游戏投屏保持前台。
4. 默认方案为“超燃竞技场-三技能”示例。请先在训练场校对位置，再用于正式游戏；不同手机比例和游戏布局可能需要调整。

无线调试首次配对需要先完成 `adb pair`；控制台的“连接手机”用于连接已经配对的地址。无线端口改变后，需要修改本地 `control-center/config.json` 中的 `serial`。

如需桌面入口，在 PowerShell 7 中运行根目录的 `CreateShortcut.ps1`。它创建带版本号的快捷方式，遇到同名文件时停止，不覆盖已有入口。

从个人旧版本迁移时，请先退出旧控制台和适配器，保留旧目录备份，再打开新版本。此发行包使用独立的本机设置和方案库，不会自动导入旧方案。

## 日常控制

投屏在前台时，适配器自动控制；切到其他软件时释放触点并挂起。切回投屏后，摇杆按当前方向继续，已经按住的按钮需要先松开再按。Start 不承担启停功能。

**手动暂停会保持暂停。** 点击控制台“恢复自动控制”，或点击悬浮窗中的适配器状态，即可恢复。手柄断连不会停止鼠标控制。

鼠标左键未设置固定映射时，可以自由点击和拖动；右键需要先放置对应按键。固定映射优先于自由触控，同一圆心可分别绑定手柄按键、鼠标左键和右键。

AntiMicroX 与主适配器可能重复输出。控制台打开备用软件前会暂停主适配器；已有非空映射运行时，适配器会提示冲突。一般无需同时开启。

## 制作与切换按键方案

在“方案编辑”中新建或载入方案，让手机进入横屏游戏，点“开始在投屏摆放”。从浮动工具条拖入按键，再选择触发方式和范围；工具条会保持在投屏上方。

| 类型 | 按下后的行为 | 常见用途 |
| --- | --- | --- |
| 按住 | 持续触摸，松键时抬起 | 蓄力、持续操作 |
| 单次点击 | 每次按下完成一次点击，长按不连发 | 跳跃、交互、普通点击 |
| 连续点击 | 按住期间按设定频率重复点击，默认 10 次/秒 | 需要重复点击的按钮 |
| 按住瞄准 | 以配置位置为起点，按住并拖动调整方向 | 拖动施法、定向技能 |

“覆盖半径”控制鼠标自由点击时的命中圈，也用于编辑时选中和拖动。“摇杆/瞄准范围”调整触控行程，右摇杆的数值表示视角速度百分比。两者互不替代。

保存后结束摆放，再从控制台或悬浮窗切换到该方案。保存前会备份旧文件；新建方案需要在对应游戏模式内验收。位置按有效画面比例缩放，不包含标题栏、工具栏和黑边。

## 数据与监测说明

所有记录保存在解压目录内，不上传手机状态或操作记录。首次设置会创建本机配置；首次初始化方案库时，若 GameScrcpy 没有同名示例方案，会创建示例文件，已有同名文件会保留。

- 本机设置：`control-center/config.json`。
- 会话记录：`control-center/logs/` 下的 `samples.csv` 和 `events.jsonl`。
- 方案库：`phase2b-20261015/profiles/library.json`；按键 JSON 位于 GameScrcpy 的 `keymap` 目录。
- 方案备份：`control-center/backups/profile-edits/`。

投屏 FPS 读取 GameScrcpy 的显示值，游戏 FPS 来自手机 SurfaceFlinger 采样。两者都不代表端到端输入延迟；没有有效数据时留空。窗口响应超时显示为“疑似卡住”，不等同于已经证明应用崩溃。

目前主要在蛋仔派对训练场和个人设备上验证，未完成所有手机、手柄及游戏的兼容性测试。系统级黑屏和显示异常仍需独立排查，本项目不承诺修复显卡驱动或 USB 存储故障。

## 从源码构建

需要 Python 3.12 x64、PowerShell 7.6.4+ 和 Java 8。构建脚本会下载并校验固定版本的 ECJ、R8，只用于编译 Android 触控组件。

在 PowerShell 7 中运行：

```powershell
python -m pip install -r requirements-build.txt
./build.ps1 -Python python -Java java
```

脚本先运行回归测试，再生成 Windows ZIP 和 `SHA256SUMS.txt`。旧输出不会被覆盖。项目源码沿用原有目录结构，`control-center/src` 为控制台，`tools/analog` 为适配器，`phase2b-20261015` 为运行数据和方案目录。

## 版本记录

### 0.3.0

1. 新增：首次设置和 Windows 便携发布包，集中提供控制台、适配器及必要运行文件。
2. 修复：公开源码不再依赖原电脑的安装路径、手机地址和摇杆中心校准值。
3. 优化：整理源码、示例方案、构建脚本和使用说明，保留已验收的手柄与鼠标控制逻辑。

详细记录见 [CHANGELOG](CHANGELOG.md)。

## 许可与致谢

项目源码采用 [MIT License](LICENSE)。手柄图标来自 [Lucide](https://lucide.dev)，图标原始文件和许可保存在 `control-center/assets/lucide/`。Python、Tcl/Tk 和 PyInstaller 等组件遵循各自许可，见 [第三方说明](THIRD_PARTY_NOTICES.md)。GameScrcpy、PowerShell 和 AntiMicroX 由使用者单独安装，本仓库不分发它们的完整程序。
