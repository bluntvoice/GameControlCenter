# Phase 0 调查与工程基线

调查日期 2026-11-21。

## 本机与真机

| 项目 | 现场结果 |
| --- | --- |
| 工程 | `D:\codex-data\projects\android-gamepad`，检查时不存在，已独立初始化 `feature/android-gamepad` |
| 磁盘 | C 约 6.04 GiB、D 约 210.04 GiB、F 约 28.38 GiB 可用 |
| Android Studio | `F:\应用数据\Android Studio`，2022.1.1 RC 1，内置 JBR 11.0.15 |
| 原有 SDK | `F:\src\Android\sdk`，调查时仅 Platform 33-ext4 和 Build Tools 33.0.1 |
| 既有 Java / Gradle | PATH 中 Java 8u271。用户缓存发现 Gradle 7.4。新工程采用 JDK 17、Gradle 8.13、AGP 8.13.2、Kotlin 2.2.21 |
| Android 构建 | 构建用 Platform 35 和 Build Tools 35.0.0。原型的 API 下限及 targetSdk 均为 34，所需前台外手柄 MotionEvent 回调自 API 34 起可用。运行验证用 API 37 |
| ADB | F 盘 Platform Tools 33.0.3，以现有授权连接设备 |
| 手机 | 2509FPN0BC，Android 17 / API 37，物理尺寸竖屏 1200 × 2608。《蛋仔派对》`com.netease.party` 已安装 |
| Shizuku | `moe.shizuku.privileged.api` 13.7.0-thedjchi。进程 `shizuku_server` 以 shell 身份运行，设备报告 shell 持有 `INJECT_EVENTS`。新 App 用户授权、UserService 和事件投递待实测 |
| 手柄 | 调查时只看到系统虚拟设备 `uinput-xiaomi`，未看到实体设备或摇杆轴。需用户连接实体手柄采样 |

以现有命令行工具构建，避免升级 Android Studio。API 37 SDK 没有安装。Google 的 Android 17 SDK 配置区分编译 API 与运行行为，AGP 8.13 官方最大支持 API 36.1。原型先用已覆盖所需公开 API 的构建基线。 [Android 17 SDK](https://developer.android.com/about/versions/17/setup-sdk) · [AGP 8.13](https://developer.android.com/build/releases/agp-8-13-0-release-notes)

## Windows 源码与迁移

Windows 源码位于 `D:\CodexData\程序助手\GameControlCenter`，读取时 `main` 为 `b6114b2784653c175c6593aea3922f908c4bd6d0`。工作区已有修改，Android 工程使用独立 Git。核对了 `tools/analog/profile_store.py`、`tools/analog/pad_core.py` 及 `control-center/src/backend.py` 的加载入口，配置来源为 `D:\CodexData\程序助手\GameControlProfiles\phase2b-20261015` 的正式 `profiles/library.json`、`analog/settings.json` 和库引用的实际 GameScrcpy keymap 文件。

| 配置 | 版本 | 源节点 | 可转换 | 差异 |
| --- | ---: | ---: | ---: | --- |
| 超燃竞技场-三技能 | 39 | 14 | 14 | LT 为每秒 3 次连点，以库里的适配器元数据为准 |
| 激战先锋 | 23 | 16 | 15 | `RightButton` 无实体手柄绑定，原节点随报告保留 |

方案稳定 ID、修订号、坐标、Windows 键名对应的实体按钮和源文件 SHA-256 已纳入版本化 JSON。摇杆四向范围按 Windows 的 2608 × 1200 基准还原为像素，再按 Android 游戏有效区域的高度缩放。保留死区、曲线、视角速度和右摇杆速度系数。Windows XInput 测出的右摇杆静止偏移属于设备校准。

Windows 的技能瞄准由 `KMT_FREE_LOOK` 按钮节点接管右摇杆，触点在技能锚点附近移动，松键释放。两份正式配置均无该节点，左摇杆控件标注的 `aim` 没有改变 Windows 运行时的方向摇杆行为。迁移保持这一点。原型会单独覆盖声明式技能瞄准。脚本仅识别源代码生成的两种固定形态，已知连点来自适配器元数据。未知节点带原始 JSON 和失败原因保留，导入器无脚本运行逻辑。

## 手柄·阿西西

包名 `cn.axi.gamepad.an`，版本 1.0.6 / 7，记录的安装器为 `com.miui.packageinstaller`。包管理器解析出的 launcher Activity 为 `.AxiGamePadIndexActivity`。官方页面列出按键、摇杆、震动和体感检测。当前公开资料未找到 SDK、数据接口或正式联动 Intent。Android 端计划使用包管理器 launcher Intent 提供可选快捷入口。本机界面各轴数值、死区显示及两 App 同时运行的输入冲突需结合实体手柄验证。 [开发者主页](https://www.axixi.top/#apps)

## 技术路线与参考实现

- 两种注入共用同一组归一化输入、映射规则和触点生命周期。输入采用公开 AccessibilityService 的 key filter 和 joystick motion source。仅在目标窗口、允许控制并且后端就绪时启用摇杆事件拦截。检查过滤退出、按键按下抬起对称、设备变化、焦点和锁屏。
- Shizuku 通过用户授予的 UserService 权限，尝试以 shell 身份调用系统输入管理器。对 DOWN、POINTER_DOWN、MOVE、POINTER_UP、UP 和 CANCEL 保持稳定 Pointer ID、连续 downTime。系统拒绝、人机窗口变化、权限丢失、Binder 死亡必须进入可见错误或暂停状态。shell 权限存在与触点送达分别取证。 [Shizuku API](https://github.com/RikkaApps/Shizuku-API) · [AOSP 输入管理器](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/core/java/android/hardware/input/InputManagerGlobal.java)
- 无障碍路径维护整组活动 stroke，派发下一段时由 `continueStroke` 延续每个存活的 pointer。需要验证加入新 stroke、短按排队、用户触屏冲突和取消回调。 [AccessibilityService](https://developer.android.com/reference/android/accessibilityservice/AccessibilityService) · [StrokeDescription](https://developer.android.com/reference/android/accessibilityservice/GestureDescription.StrokeDescription) · [AOSP 手势注入](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/services/accessibility/java/com/android/server/accessibility/MotionEventInjector.java)
- OpenMapper 提供 Shizuku 路线案例，许可证为 PolyForm Noncommercial 1.0.0。Zploy 针对 Android 16 与特定 Xbox 布局类手柄。thorpad 记录了公开 Accessibility motion event、shell 读取输入设备及前台浮层路线。后两者公开仓库首页未找到许可声明。本工程独立实现。 [OpenMapper](https://github.com/kinou-p/android-open-mapper) · [Zploy](https://github.com/king0929zion/Zploy) · [thorpad](https://github.com/stagfoo/thorpad)
- 最终界面遵循 Compose Material 3 文档。Phase 1 先用可记录实际触点和事件顺序的测试画布。 [Material 3](https://developer.android.com/develop/ui/compose/designsystems/material3)

## 门槛

Phase 1 以真机接收端记录作为证据。验证双摇杆真实活动时肩键进入独立触点，松手后接收端触点归零，后台输入能交回系统。实体手柄与授权、真实游戏显示区域、5 分钟复合控制和 100 次短按单列结果。未满足核心并发的真机门槛时，暂停 Phase 2 界面和编辑器投入。
