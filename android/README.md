# 安卓手柄控制台

Android 17 真机开发项目。已实现 Shizuku 游戏控制、本地方案、悬浮编辑和 Material 3 界面。真实玩法和稳定性验收按测试记录区分。

[安装与操作](docs/playtest.md) · [验收记录](docs/verification.md) · [环境、迁移与技术路线](docs/phase-0.md)

## 构建

需要 JDK 17、Android SDK Platform 35 和 Build Tools 35.0.0。将 `ANDROID_HOME` 指向现有 SDK 或使用 `local.properties` 的 `sdk.dir`。通过 Gradle Wrapper 执行 `testDebugUnitTest lintDebug assembleDebug`。

```powershell
.\gradlew.bat testDebugUnitTest lintDebug assembleDebug
```
