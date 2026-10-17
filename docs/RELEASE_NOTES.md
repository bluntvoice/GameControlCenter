> 首次公开发布：在 Windows 上管理手机投屏、手柄双摇杆、鼠标操作和按键方案。

## 版本亮点

- 双摇杆直接转换为手机连续触控，手柄和鼠标可以同时使用。
- 在投屏内拖放按键，设置四种触发方式和点击覆盖范围；控制台与悬浮窗均可切换方案。
- 集中查看程序状态、手机电量、手柄连接和帧率记录，支持任务栏与托盘并存。
- 提供首次设置和 Windows x64 便携包，无需另外安装 Python。

## 变更

以本地 v0.2.16 的已验收控制逻辑为基础，统一版本为 0.3.0，整理独立构建入口，移除原电脑路径、手机地址和个人摇杆校准值。

投屏在前台时自动控制，手动暂停会保持暂停；可点击悬浮窗中的适配器状态恢复。手柄断连后，鼠标仍可继续使用。

> [!WARNING]
> 请完整解压后运行，单独复制 EXE 无法使用。需自行安装 GameScrcpy v1.3.4 和 PowerShell 7.6.4+，并授权手机 ADB 调试。默认方案是待校对示例，其他手机、手柄与游戏的兼容性尚未全面验证。

## 下载

| 平台 | 文件 |
| --- | --- |
| Windows x64 | `GameControlCenter-0.3.0-windows-x64.zip` |
| SHA-256 校验 | `SHA256SUMS.txt` |

解压后运行 `control-center/releases/0.3.0/GameControlCenter.exe`，首次打开时填写本机软件路径和手机连接地址。也可在 PowerShell 7 中运行 `CreateShortcut.ps1` 创建桌面入口。

此前版本仅在个人设备上使用，本次为仓库首次发布。完整记录见 [CHANGELOG](https://github.com/bluntvoice/GameControlCenter/blob/v0.3.0/CHANGELOG.md)，使用步骤见 [README](https://github.com/bluntvoice/GameControlCenter/tree/v0.3.0#readme)。
