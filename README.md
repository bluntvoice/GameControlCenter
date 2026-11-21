# 安卓手柄控制台

Android 17 真机开发项目。当前交付目标为核心触控原型，先在测试画布确认后台手柄输入、双摇杆与肩键并发及全部释放。通过该门槛后再进入可玩版 UI、配置管理与游戏内编辑阶段。

[环境、迁移与技术路线](docs/phase-0.md)

## 构建

需要 JDK 17、Android SDK Platform 35 和 Build Tools 35.0.0。将 `ANDROID_HOME` 指向现有 SDK 或使用 `local.properties` 的 `sdk.dir`。通过 Gradle Wrapper 执行 `testDebugUnitTest lintDebug assembleDebug`。

```powershell
.\gradlew.bat testDebugUnitTest lintDebug assembleDebug
```
