# 安卓手柄控制台

Android 17 真机开发项目。已实现 Shizuku 游戏控制、本地方案、悬浮编辑和 Material 3 界面。真实玩法和稳定性验收按测试记录区分。

[安装与操作](docs/playtest.md) · [验收记录](docs/verification.md) · [环境、迁移与技术路线](docs/phase-0.md)

## 构建

需要 JDK 17、Android SDK Platform 35 和 Build Tools 35.0.0。将 `ANDROID_HOME` 指向现有 SDK 或使用 `local.properties` 的 `sdk.dir`。通过 Gradle Wrapper 执行 `testDebugUnitTest lintDebug assembleDebug`。

```powershell
.\gradlew.bat testDebugUnitTest lintDebug assembleDebug
```

## 版本规划

Android 单独编号。`0.0.9-playtest` 是最后一轮原型试装。下一阶段从 `0.1.0-beta.1` 开始，将同一验收目标下的调整合并测试，每发一轮测试 APK 增加 beta 序号。

- 每次交付新的可安装 APK 时，`versionCode` 都必须高于此前已经交付的构建。仅提交源码或文档时沿用现有版本号。同一版本号交付后保留对应的 APK 与 Git 提交。
- 两套玩法通过真机实操，以及手柄断连、暂停恢复、离线和配置保存等回归通过后，进入 `0.1.0-rc.1`。候选版经覆盖安装和用户确认后，再发布 `0.1.0`。
- 正式版中，修复使用补丁号（如 `0.1.1`），新增功能使用次版本号（如 `0.2.0`）。对外发布时使用 `android-v0.1.0` 这样的 Android 专用标签，以便与电脑版版本区分。
- 每次集中出包记录版本名、`versionCode`、变更、Git 提交、APK SHA-256 和验收结果。
