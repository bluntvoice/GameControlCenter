# 安卓手柄控制台

Android 17 真机开发项目。已实现 Shizuku 游戏控制、本地方案、悬浮编辑和 Material 3 界面。真实玩法和稳定性验收按测试记录区分。

[安装与操作](docs/playtest.md) · [验收记录](docs/verification.md) · [环境、迁移与技术路线](docs/phase-0.md)

## 后续开发计划

自 2026-11-21 起，以 `0.1.0-beta.1` 为当前使用基线。后续按实际使用反馈和明确的功能需求做小范围迭代，保留已稳定运行的功能和现有架构。

- Shizuku 是唯一正式支持的触控注入后端。保留现有 `AccessibilityService` 对手柄按键、摇杆、触屏并用及前台窗口识别的支持。纯无障碍触控注入保留现有实验入口，开发完善和专项验收暂缓。
- 暂缓 P0 触控安全恢复、P1 两套玩法专项回归、P2 脱离电脑和配置专项验收。这些历史工作包可随相关改动或实际反馈按需复测，后续开发可直接按需求推进。
- 每次代码修改执行必要的编译、自动测试和与改动直接相关的回归。沿用现有配置格式和兼容规则，保留旧方案的稳定 ID、修订和本地副本关系。
- 在 `feat/android-gamepad` 继续提交并推送改动，交付时记录实际变更、已通过的检查及待验证项。

## 构建

需要 JDK 17、Android SDK Platform 35 和 Build Tools 35.0.0。将 `ANDROID_HOME` 指向现有 SDK 或使用 `local.properties` 的 `sdk.dir`。通过 Gradle Wrapper 执行 `testDebugUnitTest lintDebug assembleDebug`。

```powershell
.\gradlew.bat testDebugUnitTest lintDebug assembleDebug
```

## 版本规划

Android 单独编号。当前测试基线为 `0.1.0-beta.1`。同一轮的相关调整合并测试，交付新的测试 APK 时递增 Beta 序号。

- 每次交付新的可安装 APK 时，`versionCode` 都必须高于此前已经交付的构建。仅提交源码或文档时沿用现有版本号。同一版本号交付后保留对应的 APK 与 Git 提交。
- 是否发布正式版由用户另行决定。当前迭代按具体需求推进，暂缓围绕 RC 门槛的专项开发。
- 正式版中，修复使用补丁号（如 `0.1.1`），新增功能使用次版本号（如 `0.2.0`）。对外发布时使用 `android-v0.1.0` 这样的 Android 专用标签，以便与电脑版版本区分。
- 每次集中出包记录版本名、`versionCode`、变更、Git 提交、APK SHA-256 和验收结果。
