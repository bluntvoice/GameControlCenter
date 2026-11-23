package io.github.bluntvoice.androidgamepad

import android.content.Intent
import android.os.Bundle
import android.os.SystemClock
import android.provider.Settings
import android.view.InputDevice
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.Window
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.boundsInRoot
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import rikka.shizuku.Shizuku
import java.util.Locale

private enum class Page(val label: String) {
    HOME("控制"), PROFILES("方案"), DIAGNOSTICS("诊断"), SETTINGS("设置")
}

class MainActivity : ComponentActivity() {
    private val localInput = ControllerInput()
    private val diagnosticFlow = MutableStateFlow(InputSnapshot())
    private var sampling = false
    private val resumeRevision = MutableStateFlow(0)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        ProbeRuntime.initialize(this)
        GameSession.initialize(this)
        enableEdgeToEdge()
        val callback = window.callback
        window.callback = object : Window.Callback by callback {
            override fun dispatchKeyEvent(event: KeyEvent): Boolean {
                if (sampleKey(event)) return true
                return callback.dispatchKeyEvent(event)
            }
        }
        setContent {
            val dark = isSystemInDarkTheme()
            val context = LocalContext.current
            val scheme = if (dark) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
            MaterialTheme(colorScheme = scheme) { Console() }
        }
    }

    override fun onResume() {
        super.onResume()
        GameSession.service?.keepInputServiceInForeground()
        resumeRevision.value++
    }

    override fun onPause() {
        localInput.reset()
        diagnosticFlow.value = InputSnapshot()
        super.onPause()
    }

    private fun sampleKey(event: KeyEvent): Boolean {
        if (sampling && ControllerInput.isController(event.device) && localInput.key(event, 0L)) {
            diagnosticFlow.value = InputSnapshot(localInput.state, "Activity · Gamepad", event.deviceId, event.eventTime)
            return true
        }
        return false
    }

    override fun dispatchGenericMotionEvent(event: MotionEvent): Boolean {
        if (sampling && ControllerInput.isController(event.device) && event.isFromSource(InputDevice.SOURCE_JOYSTICK)) {
            localInput.motion(event)
            diagnosticFlow.value = InputSnapshot(localInput.state, "Activity · Joystick", event.deviceId, event.eventTime)
            return true
        }
        return super.dispatchGenericMotionEvent(event)
    }

    @OptIn(ExperimentalMaterial3Api::class)
    @Composable
    private fun Console() {
        val repository = GameSession.repository
        val notifications = remember { SnackbarHostState() }
        val coroutine = rememberCoroutineScope()
        fun report(text: String) { coroutine.launch { notifications.showSnackbar(text) } }
        fun change(action: () -> String) {
            runCatching(action).onSuccess(::report).onFailure { report(it.message ?: "操作失败") }
        }
        var page by rememberSaveable { mutableStateOf(Page.HOME) }
        var revision by remember { mutableIntStateOf(0) }
        val resume by resumeRevision.collectAsState()
        val catalog = remember(revision, resume) { repository.all() }
        val profile = remember(revision, resume) { repository.load(repository.selectedId) }
        val backend = remember(revision, resume) { repository.backendChoice }
        val session by GameSession.state.collectAsState()
        var attached by remember { mutableStateOf(ControllerInput.currentController()) }
        var accessReady by remember { mutableStateOf(GameSession.service != null) }
        var accessEnabled by remember { mutableStateOf(ControllerService.isEnabledInSettings(this)) }
        var shellReachable by remember { mutableStateOf(Shizuku.pingBinder()) }
        var shellReady by remember { mutableStateOf(ShellConnection.available()) }
        var clock by remember { mutableStateOf(SystemClock.uptimeMillis()) }
        LaunchedEffect(Unit) {
            while (true) {
                attached = ControllerInput.currentController()
                accessReady = GameSession.service != null
                accessEnabled = accessReady || ControllerService.isEnabledInSettings(this@MainActivity)
                shellReachable = Shizuku.pingBinder()
                shellReady = ShellConnection.available()
                clock = SystemClock.uptimeMillis()
                delay(700)
            }
        }
        LaunchedEffect(page) {
            sampling = page == Page.DIAGNOSTICS
            if (!sampling) {
                localInput.reset()
                diagnosticFlow.value = InputSnapshot()
            }
        }
        val import = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
            if (uri != null) change {
                val saved = repository.import(uri)
                GameSession.stop()
                repository.selectedId = saved.id
                revision++
                "已导入 ${saved.name}"
            }
        }
        fun launchGame(edit: Boolean) {
            val launch = packageManager.getLaunchIntentForPackage(profile.gamePackage)
            if (launch == null) {
                report("手机未安装《蛋仔派对》")
                return
            }
            if (GameSession.arm(profile, backend, edit)) {
                runCatching { startActivity(launch) }.onFailure {
                    GameSession.stop("无法打开游戏", GameStatus.ERROR)
                }
            }
        }
        BackHandler(page != Page.HOME) { page = Page.HOME }
        var duplicateTitle by rememberSaveable { mutableStateOf<String?>(null) }
        duplicateTitle?.let { proposed ->
            AlertDialog(
                onDismissRequest = { duplicateTitle = null },
                title = { Text("复制 ${profile.name}") },
                text = {
                    OutlinedTextField(proposed, { duplicateTitle = it }, label = { Text("副本名称") },
                        singleLine = true, modifier = Modifier.fillMaxWidth())
                },
                confirmButton = {
                    Button(enabled = proposed.trim().length in 1..80, onClick = {
                        change {
                            val copied = repository.duplicate(profile.id, proposed)
                            GameSession.stop()
                            repository.selectedId = copied.id
                            duplicateTitle = null
                            revision++
                            "已创建并选中 ${copied.name}"
                        }
                    }) { Text("复制并选中") }
                },
                dismissButton = { TextButton(onClick = { duplicateTitle = null }) { Text("取消") } },
            )
        }
        val navIcons = listOf(Icons.Filled.Home, Icons.AutoMirrored.Filled.List, Icons.Filled.Info, Icons.Filled.Settings)
        Scaffold(
            topBar = { TopAppBar(title = { Text(if (page == Page.HOME) "安卓手柄控制台" else page.label) }) },
            snackbarHost = { SnackbarHost(notifications) },
            bottomBar = {
                NavigationBar {
                    Page.entries.forEachIndexed { index, entry ->
                        NavigationBarItem(
                            selected = entry == page,
                            onClick = { page = entry },
                            icon = { Icon(navIcons[index], contentDescription = null) },
                            label = { Text(entry.label) },
                        )
                    }
                }
            },
        ) { padding ->
            var viewport by remember { mutableStateOf(Rect.Zero) }
            val scroll = rememberScrollState()
            Box(Modifier.fillMaxSize().padding(padding).onGloballyPositioned { viewport = it.boundsInRoot() },
                contentAlignment = Alignment.TopCenter) {
                Column(
                    Modifier.widthIn(max = 680.dp).fillMaxWidth().verticalScroll(scroll)
                        .padding(horizontal = 20.dp, vertical = 12.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    when (page) {
                        Page.HOME -> Dashboard(
                            profile, session, attached, accessReady, accessEnabled, shellReachable, shellReady, backend,
                            start = { launchGame(false) },
                            edit = { launchGame(true) },
                            stop = { GameSession.stop() },
                            openSettings = { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) },
                            authorize = {
                                if (shellReachable) change {
                                    if (!shellReady) Shizuku.requestPermission(1)
                                    if (shellReady) "Shizuku 已授权" else "请在系统弹窗中完成授权"
                                } else report("请先在 Shizuku 中启动服务")
                            },
                        )
                        Page.PROFILES -> {
                            Text("本地方案", style = MaterialTheme.typography.titleLarge)
                            ProfileOrderList(catalog, profile.id, scroll, viewport, select = { item ->
                                if (item.id != profile.id) {
                                    runCatching {
                                        repository.selectedId = item.id
                                        GameSession.stop()
                                        revision++
                                        GameSession.announceProfileSwitch(profile, item)
                                    }.onFailure { report(it.message ?: "无法切换方案") }
                                }
                            }, saveOrder = { order ->
                                runCatching { repository.saveOrder(order) }.fold(
                                    onSuccess = { revision++; true },
                                    onFailure = { report(it.message ?: "无法保存方案顺序"); false },
                                )
                            })
                            OutlinedButton(onClick = { import.launch(arrayOf("application/json", "application/octet-stream", "text/plain")) }) {
                                Text("导入方案文件")
                            }
                            OutlinedButton(onClick = { duplicateTitle = profile.name.take(74) + "（手机）" }) {
                                Text("复制方案")
                            }
                            Button(onClick = { launchGame(true) }, enabled = accessReady) { Text("在游戏内编辑") }
                            if (repository.isBuiltin(profile.id)) {
                                TextButton(onClick = {
                                    change {
                                        GameSession.stop()
                                        val restored = repository.restore(profile.id)
                                        revision++
                                        "已恢复 ${restored.name} 的原始配置"
                                    }
                                }) { Text("恢复原始配置") }
                            }
                        }
                        Page.DIAGNOSTICS -> {
                            val latest by diagnosticFlow.collectAsState()
                            val background by GameSession.diagnostics.collectAsState()
                            val sample = if (latest.lastMs >= background.lastMs) latest else background
                            Diagnostics(sample, attached, profile, clock)
                            OutlinedButton(onClick = {
                                GameSession.stop()
                                startActivity(Intent(this@MainActivity, ProbeActivity::class.java)
                                    .putExtra("backend", backend.name))
                            }) { Text("打开触控测试画布") }
                            packageManager.getLaunchIntentForPackage("cn.axi.gamepad.an")?.let { intent ->
                                TextButton(onClick = { startActivity(intent) }) { Text("打开手柄·阿西西") }
                            }
                            TextButton(
                                enabled = attached?.id == sample.deviceId && sample.deviceId != null,
                                onClick = {
                                    change {
                                        val device = requireNotNull(attached)
                                        require(clock - sample.lastMs < 3000) { "请拨动摇杆后松手，再校准中心" }
                                        repository.saveCenter(device, sample.state)
                                        revision++
                                        "已保存 ${device.name} 的摇杆中心"
                                    }
                                },
                            ) { Text("校准当前摇杆中心") }
                        }
                        Page.SETTINGS -> {
                            Text("默认触控后端", style = MaterialTheme.typography.titleLarge)
                            BackendChoice.entries.forEach { option ->
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    RadioButton(selected = option == backend, onClick = {
                                        change {
                                            GameSession.stop()
                                            repository.backendChoice = option
                                            revision++
                                            "已保存触控后端"
                                        }
                                    })
                                    Text(option.label())
                                }
                            }
                            HorizontalDivider()
                            Text(profile.name, style = MaterialTheme.typography.titleLarge)
                            Tuning(profile) { left, right, leftGain, speed, tap ->
                                change {
                                    GameSession.stop()
                                    val json = repository.editable(profile.id)
                                    json.getJSONObject("parameters")
                                        .put("leftDeadzone", left.toDouble()).put("rightDeadzone", right.toDouble())
                                        .put("leftSensitivity", leftGain.toDouble())
                                        .put("cameraPxPerSecondAt1200", speed.toDouble()).put("tapMs", tap.toInt())
                                    repository.saveEdit(profile.id, json)
                                    revision++
                                    "已保存方案参数"
                                }
                            }
                            val calibration = remember(attached, revision) { repository.calibration(attached) }
                            for (axisX in listOf(true, false)) {
                                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween,
                                    verticalAlignment = Alignment.CenterVertically) {
                                    Text("反转右摇杆 ${if (axisX) "X" else "Y"} 轴")
                                    Switch(checked = if (axisX) calibration.invertRightX else calibration.invertRightY,
                                        onCheckedChange = { enabled ->
                                            change {
                                                GameSession.stop()
                                                repository.invert(axisX, enabled)
                                                revision++
                                                "已保存轴向"
                                            }
                                        })
                                }
                            }
                            HorizontalDivider()
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically) {
                                Text("手柄与触屏并用", modifier = Modifier.weight(1f))
                                Switch(checked = remember(revision) { repository.hybridTouch },
                                    enabled = android.os.Build.VERSION.SDK_INT >= 37 &&
                                        backend != BackendChoice.ACCESSIBILITY,
                                    onCheckedChange = {
                                        change {
                                            GameSession.stop()
                                            repository.hybridTouch = it
                                            revision++
                                            if (it) "手柄与触屏并用已开启" else "手柄与触屏并用已关闭"
                                        }
                                    })
                            }
                            Text("测试功能。需要 Android 17 和 Shizuku。仅在横屏游戏控制中接收主屏触摸。",
                                style = MaterialTheme.typography.bodySmall)
                            HorizontalDivider()
                            Text("游戏内悬浮显示", style = MaterialTheme.typography.titleLarge)
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically) {
                                Text("显示键位提示")
                                Switch(checked = remember(revision) { repository.showHints }, onCheckedChange = {
                                    change {
                                        repository.showHints = it
                                        revision++
                                        if (it) "键位提示已开启" else "键位提示已关闭"
                                    }
                                })
                            }
                            OverlayOpacity(repository, revision) { hints, panel ->
                                change {
                                    repository.saveOverlayOpacity(hints, panel)
                                    revision++
                                    "已保存不透明度"
                                }
                            }
                            HorizontalDivider()
                            HintColors(repository, revision) { key, color ->
                                change {
                                    repository.saveHintColor(key, color)
                                    revision++
                                    if (color == null) "已恢复 ${key.label} 默认颜色" else "已保存 ${key.label} 的颜色"
                                }
                            }
                            HorizontalDivider()
                            Text("运行日志", style = MaterialTheme.typography.titleLarge)
                            val log by GameSession.log.collectAsState()
                            if (log.isEmpty()) Text("暂无控制记录")
                            log.takeLast(12).asReversed().forEach { Text(it, style = MaterialTheme.typography.bodySmall) }
                            Text("版本 ${BuildConfig.VERSION_NAME}", style = MaterialTheme.typography.bodySmall)
                        }
                    }
                    Spacer(Modifier.height(12.dp))
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Dashboard(
    profile: Profile, session: GameSnapshot, attached: InputDevice?, accessReady: Boolean,
    accessEnabled: Boolean,
    shellReachable: Boolean, shellReady: Boolean, backend: BackendChoice,
    start: () -> Unit, edit: () -> Unit, stop: () -> Unit,
    openSettings: () -> Unit, authorize: () -> Unit,
) {
    val running = session.status in setOf(GameStatus.STARTING, GameStatus.READY, GameStatus.ACTIVE, GameStatus.EDITING)
    val label = if (session.status == GameStatus.STOPPED) {
        when {
            attached == null -> "未连接手柄"
            !accessReady -> "等待无障碍服务"
            backend != BackendChoice.ACCESSIBILITY && !shellReady -> "等待 Shizuku"
            else -> "可以开始"
        }
    } else session.status.label
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)) {
        Column(Modifier.fillMaxWidth().padding(20.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(profile.name, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold)
            Text("${label} · ${session.backend.ifBlank { backend.label() }}",
                style = MaterialTheme.typography.titleMedium)
            if (session.detail.isNotBlank() && session.detail != profile.name) {
                Text(session.detail, style = MaterialTheme.typography.bodyMedium)
            }
            session.viewport?.let { Text("${it.width} × ${it.height} 游戏有效区域", style = MaterialTheme.typography.bodySmall) }
        }
    }
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Button(onClick = start, enabled = !running && attached != null && accessReady &&
            (shellReady || backend == BackendChoice.ACCESSIBILITY)) { Text("开始控制") }
        OutlinedButton(onClick = edit, enabled = !running && accessReady) { Text("编辑触点") }
        if (session.status != GameStatus.STOPPED) TextButton(onClick = stop) { Text("停止") }
    }
    if (backend == BackendChoice.ACCESSIBILITY) {
        Text("无障碍注入处于兼容性验证阶段，当前设备的复合触控可能中断。",
            color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
    }
    HorizontalDivider()
    StatusRow("手柄", attached?.name ?: "未连接", attached != null)
    StatusRow("无障碍", when {
        accessReady -> "已连接"
        accessEnabled -> "开关已开，服务未连接"
        else -> "未开启"
    }, accessReady)
    if (!accessReady) OutlinedButton(onClick = openSettings) {
        Text(if (accessEnabled) "检查无障碍连接" else "开启无障碍手柄输入")
    }
    StatusRow("Shizuku", when {
        shellReady -> "已授权"
        shellReachable -> "等待授权"
        else -> "未启动"
    }, shellReady)
    if (!shellReady) OutlinedButton(onClick = authorize) { Text("授权 Shizuku") }
}

@Composable
private fun StatusRow(label: String, value: String, ready: Boolean) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        val color = if (ready) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outline
        Box(Modifier.size(8.dp).background(color, CircleShape))
        Text(label, Modifier.padding(start = 10.dp).weight(.32f), style = MaterialTheme.typography.labelLarge)
        Text(value, Modifier.weight(.68f), style = MaterialTheme.typography.bodyMedium)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Diagnostics(input: InputSnapshot, device: InputDevice?, profile: Profile, clock: Long) {
    Text(device?.name ?: "未连接手柄", style = MaterialTheme.typography.headlineSmall)
    Text(if (device == null) "等待外接手柄" else "设备 ID ${device.id} · ${input.source.ifBlank { "等待事件" }}")
    if (input.lastMs > 0) Text("最近输入 ${(clock - input.lastMs).coerceAtLeast(0)} ms 前",
        style = MaterialTheme.typography.bodySmall)
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
        Stick("左摇杆", input.state.left, profile.parameters.leftDeadzone)
        Stick("右摇杆", input.state.right, profile.parameters.rightDeadzone)
    }
    Text("LT  ${decimal(input.state.lt)}     RT  ${decimal(input.state.rt)}",
        fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodyLarge)
    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Button.entries.forEach { button ->
            val pressed = button in input.state.buttons
            Card(colors = CardDefaults.cardColors(containerColor = if (pressed)
                MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceContainer)) {
                Text(button.name, Modifier.padding(horizontal = 11.dp, vertical = 7.dp),
                    fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.labelLarge)
            }
        }
    }
}

@Composable
private fun Stick(label: String, point: Point, deadzone: Float) {
    val active = MaterialTheme.colorScheme.primary
    val outline = MaterialTheme.colorScheme.outline
    Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(5.dp)) {
        Text(label, style = MaterialTheme.typography.titleSmall)
        Canvas(Modifier.size(110.dp).semantics {
            contentDescription = "$label X ${decimal(point.x)} Y ${decimal(point.y)}"
        }) {
            val radius = size.minDimension / 2f - 5.dp.toPx()
            drawCircle(outline.copy(alpha = .55f), radius, style = Stroke(width = 1.dp.toPx()))
            drawCircle(outline.copy(alpha = .5f), radius * deadzone, style = Stroke(width = 1.dp.toPx()))
            drawLine(outline.copy(alpha = .35f), center - Offset(radius, 0f), center + Offset(radius, 0f))
            drawLine(outline.copy(alpha = .35f), center - Offset(0f, radius), center + Offset(0f, radius))
            drawCircle(active, 6.dp.toPx(), center + Offset(point.x, point.y) * radius)
        }
        Text("${decimal(point.x)} / ${decimal(point.y)}", fontFamily = FontFamily.Monospace,
            style = MaterialTheme.typography.labelMedium)
        Text("死区 ${decimal(deadzone)}", style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun Tuning(profile: Profile, save: (Float, Float, Float, Float, Float) -> Unit) {
    var left by remember(profile.id, profile.revision) { mutableStateOf(profile.parameters.leftDeadzone) }
    var right by remember(profile.id, profile.revision) { mutableStateOf(profile.parameters.rightDeadzone) }
    var leftGain by remember(profile.id, profile.revision) { mutableStateOf(profile.parameters.leftSensitivity) }
    var speed by remember(profile.id, profile.revision) { mutableStateOf(profile.parameters.cameraSpeed) }
    var tap by remember(profile.id, profile.revision) { mutableStateOf(profile.parameters.tapMs.toFloat()) }
    Text("左摇杆死区 ${decimal(left)}")
    Slider(left, { left = it }, valueRange = 0f.. .4f)
    Text("右摇杆死区 ${decimal(right)}")
    Slider(right, { right = it }, valueRange = 0f.. .4f)
    Text("左摇杆灵敏度 ${(leftGain * 100).toInt()}%")
    Slider(leftGain, { leftGain = it }, valueRange = .5f..2f)
    Text("右摇杆灵敏度 ${(speed / 8f).toInt()}% · ${speed.toInt()} px/s")
    Slider(speed, { speed = it }, valueRange = 50f..4000f)
    Text("点击时长 ${tap.toInt()} ms")
    Slider(tap, { tap = it }, valueRange = 24f..150f)
    Button(onClick = { save(left, right, leftGain, speed, tap) }) { Text("保存方案参数") }
}

@Composable
private fun OverlayOpacity(repository: ProfileRepository, revision: Int, save: (Float, Float) -> Unit) {
    var hints by remember(revision) { mutableStateOf(repository.hintOpacity) }
    var panel by remember(revision) { mutableStateOf(repository.panelOpacity) }
    Text("键位提示不透明度 ${(hints * 100).toInt()}%")
    Slider(hints, { hints = it }, valueRange = .15f..1f)
    Text("悬浮条不透明度 ${(panel * 100).toInt()}%")
    Slider(panel, { panel = it }, valueRange = .35f..1f)
    Button(onClick = { save(hints, panel) }) { Text("保存不透明度") }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun HintColors(repository: ProfileRepository, revision: Int, save: (HintKey, Int?) -> Unit) {
    var visible by rememberSaveable { mutableStateOf(false) }
    var selected by rememberSaveable { mutableStateOf<HintKey?>(null) }
    OutlinedButton(onClick = {
        selected = null
        visible = true
    }) { Text("其他按键配色") }
    if (!visible) return
    val key = selected
    if (key == null) {
        AlertDialog(
            onDismissRequest = { visible = false },
            title = { Text("选择按键") },
            text = {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    HintKey.entries.filter { !it.fixed }.forEach { item ->
                        val color = remember(item, revision) { repository.hintColor(item) }
                        OutlinedButton(onClick = { selected = item }) {
                            Box(Modifier.size(9.dp).background(Color(color), CircleShape))
                            Text(item.label, Modifier.padding(start = 7.dp))
                        }
                    }
                }
            },
            confirmButton = { TextButton(onClick = { visible = false }) { Text("关闭") } },
        )
        return
    }
    var raw by rememberSaveable(key) {
        mutableStateOf(String.format(Locale.ROOT, "#%06X", repository.hintColor(key) and 0xFFFFFF))
    }
    val rgb = raw.trim().removePrefix("#")
    val color = if (rgb.matches(Regex("[0-9A-Fa-f]{6}"))) {
        (0xFF000000L or rgb.toLong(16)).toInt()
    } else null
    AlertDialog(
        onDismissRequest = { selected = null },
        title = { Text("${key.label} 配色") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedTextField(raw, { raw = it.take(8) }, singleLine = true,
                    label = { Text("颜色值 #RRGGBB") })
                if (color != null) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(22.dp).background(Color(color), CircleShape))
                        Text("预览", Modifier.padding(start = 8.dp))
                    }
                }
                TextButton(onClick = {
                    save(key, null)
                    selected = null
                }) { Text("恢复默认颜色") }
            }
        },
        confirmButton = {
            Button(enabled = color != null, onClick = {
                if (color != null) save(key, color)
                selected = null
            }) { Text("保存颜色") }
        },
        dismissButton = { TextButton(onClick = { selected = null }) { Text("取消") } },
    )
}

private fun BackendChoice.label() = when (this) {
    BackendChoice.AUTO -> "自动 · 优先 Shizuku"
    BackendChoice.ACCESSIBILITY -> "无障碍 · 兼容性测试"
    BackendChoice.SHIZUKU -> "Shizuku"
}

private fun decimal(value: Float) = String.format(Locale.ROOT, "%.2f", value)
