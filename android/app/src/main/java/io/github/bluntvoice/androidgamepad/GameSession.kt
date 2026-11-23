package io.github.bluntvoice.androidgamepad

import android.app.KeyguardManager
import android.content.Context
import android.graphics.Rect
import android.hardware.input.InputManager
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import android.util.Log
import android.view.InputDevice
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.WindowInsets
import android.view.WindowManager
import android.view.accessibility.AccessibilityWindowInfo
import android.widget.Toast
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow

enum class GameStatus(val label: String) {
    STOPPED("已停止"), WAITING("等待游戏"), STARTING("服务准备中"), READY("可以控制"),
    ACTIVE("控制中"), PAUSED("已暂停"), EDITING("编辑中"), ERROR("控制异常"),
}

data class GameSnapshot(val status: GameStatus = GameStatus.STOPPED, val detail: String = "",
    val backend: String = "", val viewport: Viewport? = null)

data class InputSnapshot(val state: ControllerState = ControllerState(), val source: String = "",
    val deviceId: Int? = null, val lastMs: Long = 0)

object GameSession : InputManager.InputDeviceListener {
    private const val TAG = "GamepadSession"
    private val main = Handler(Looper.getMainLooper())
    private val mutableState = MutableStateFlow(GameSnapshot())
    val state = mutableState.asStateFlow()
    private val mutableInput = MutableStateFlow(InputSnapshot())
    val diagnostics = mutableInput.asStateFlow()
    private val mutableLog = MutableStateFlow<List<String>>(emptyList())
    val log = mutableLog.asStateFlow()
    private val controller = ControllerInput()
    private val panelContacts = PanelContactGuard()
    private lateinit var app: Context
    lateinit var repository: ProfileRepository
        private set
    var service: ControllerService? = null
        private set
    private var overlay: GameOverlay? = null
    private var profile: Profile? = null
    private var switchingTo: Profile? = null
    private var choice = BackendChoice.AUTO
    private var editingRequested = false
    private var deviceId: Int? = null
    private var started = 0L
    private var waitingSince = 0L
    private var token = 0
    private data class GameRegion(val safe: Viewport, val mapping: Viewport)

    private var region: GameRegion? = null
    private var engine: MappingEngine? = null
    private var backend: TouchBackend? = null
    private var shellBacked = false
    private var screenContacts: ScreenContacts? = null
    private var releasing = false
    private var stopAfterRelease = false
    private var observing = false
    private var lastHealthCheck = 0L
    private var lastTargetCheck = 0L
    private var hadContacts = false
    private var lastInputLog = 0L
    private val observer = object : Runnable {
        override fun run() {
            if (!observing) return
            observeWindow()
            if (observing) main.postDelayed(this, 120L)
        }
    }

    fun initialize(context: Context) {
        if (::app.isInitialized) return
        app = context.applicationContext
        repository = ProfileRepository(app)
        app.getSystemService(InputManager::class.java).registerInputDeviceListener(this, main)
    }

    fun serviceConnected(value: ControllerService) {
        initialize(value)
        service = value
        overlay = GameOverlay(value, repository)
    }

    fun serviceDisconnected(value: ControllerService) {
        if (service !== value) return
        value.capture(false)
        service = null
        profile = null
        stopObserver()
        stop("无障碍服务已断开", GameStatus.ERROR)
        overlay?.clear()
        overlay = null
        service = null
    }

    fun arm(selected: Profile, selectedBackend: BackendChoice, edit: Boolean = false): Boolean {
        check(::app.isInitialized)
        if (releasing || ProbeRuntime.hasSession) {
            publish(GameStatus.ERROR, "等待上一段触控会话释放")
            return false
        }
        if (profile != null && backend != null) {
            stop("请在暂停后再选择方案", GameStatus.PAUSED)
            return false
        }
        if (service == null) {
            publish(GameStatus.ERROR, "等待无障碍手柄输入服务")
            return false
        }
        if (!edit && ControllerInput.currentController() == null) {
            publish(GameStatus.ERROR, "未连接实体手柄")
            return false
        }
        if (!edit && selectedBackend != BackendChoice.ACCESSIBILITY && !ShellConnection.available()) {
            publish(GameStatus.ERROR, "等待 Shizuku 启动并授权，也可在设置手动试用无障碍")
            return false
        }
        profile = selected
        choice = selectedBackend
        editingRequested = edit
        waitingSince = SystemClock.uptimeMillis()
        publish(GameStatus.WAITING, "等待《蛋仔派对》横屏窗口")
        startObserver()
        return true
    }

    fun accepts(id: Int) = backend != null && deviceId == id && !releasing

    fun isSessionPress(event: KeyEvent) = event.downTime >= started

    fun key(event: KeyEvent): Boolean {
        if (!accepts(event.deviceId) || !controller.key(event, started)) return false
        if (event.repeatCount == 0) Log.i(TAG, "key device=${event.deviceId} key=${event.keyCode} action=${event.action}")
        acceptInput(event.deviceId)
        return true
    }

    fun motion(event: MotionEvent): Boolean {
        if (!accepts(event.deviceId)) return false
        for (index in 0 until event.historySize) {
            controller.motion(event, index)
            render()
        }
        controller.motion(event)
        acceptInput(event.deviceId)
        return true
    }

    fun screenMotion(event: MotionEvent) {
        val fingers = screenContacts ?: return
        val action = when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> TouchAction.DOWN
            MotionEvent.ACTION_POINTER_DOWN -> TouchAction.POINTER_DOWN
            MotionEvent.ACTION_MOVE -> TouchAction.MOVE
            MotionEvent.ACTION_POINTER_UP -> TouchAction.POINTER_UP
            MotionEvent.ACTION_UP -> TouchAction.UP
            MotionEvent.ACTION_CANCEL -> TouchAction.CANCEL
            else -> return
        }
        val points = List(event.pointerCount) { index ->
            Pointer(event.getPointerId(index), Point(event.getRawX(index), event.getRawY(index)))
        }
        if (fingers.update(event.deviceId, event.downTime, action, event.actionIndex, points)) {
            render(checkTarget = action == TouchAction.DOWN)
        }
    }

    private fun acceptInput(id: Int) {
        val now = SystemClock.uptimeMillis()
        mutableInput.value = InputSnapshot(controller.state, "AccessibilityService", id, now)
        overlay?.pressed(controller.state.buttons)
        if (now - lastInputLog >= 500) {
            Log.i(TAG, "input device=$id ${controller.state}")
            lastInputLog = now
        }
        render()
    }

    fun windowChanged() {
        if (observing) observeWindow()
    }

    fun pause() = stop("等待继续控制", GameStatus.PAUSED)

    fun stop(reason: String = "", status: GameStatus = GameStatus.STOPPED) =
        stopSession(reason, status)

    private fun stopSession(reason: String, status: GameStatus, afterRelease: (() -> Unit)? = null) {
        if (afterRelease == null && switchingTo != null) {
            switchingTo = null
            if (reason.isNotBlank()) toast("切换失败 · $reason")
        }
        if (releasing) {
            if (status == GameStatus.STOPPED) {
                stopAfterRelease = true
                profile = null
                stopObserver()
            }
            return
        }
        val wasStarting = state.value.status == GameStatus.STARTING
        val current = backend
        ++token
        if (current != null || wasStarting) service?.capture(false)
        backend = null
        screenContacts = null
        engine = null
        region = null
        deviceId = null
        controller.reset()
        panelContacts.reset()
        mutableInput.value = InputSnapshot()
        if (status == GameStatus.STOPPED || service == null) {
            profile = null
            stopObserver()
        }
        overlay?.clear()
        fun finish(error: String?) {
            releasing = false
            val label = when {
                error != null && afterRelease == null -> GameStatus.ERROR
                stopAfterRelease -> GameStatus.STOPPED
                error != null -> GameStatus.PAUSED
                else -> status
            }
            stopAfterRelease = false
            val detail = error ?: reason
            Log.i(TAG, "session_end status=$label detail=$detail")
            publish(label, detail)
            if (current != null && (afterRelease == null || error != null || label != GameStatus.PAUSED)) {
                val action = if (label == GameStatus.PAUSED) "控制已暂停" else "控制已停止"
                toast(if (detail.isBlank()) action else "$action · $detail")
            }
            if (afterRelease != null && switchingTo != null) {
                if (error == null && label == GameStatus.PAUSED) {
                    afterRelease()
                } else {
                    switchingTo = null
                    if (error != null) toast("切换失败 · $error")
                }
            }
            if (observing) observeWindow()
        }
        if (current != null || wasStarting) {
            releasing = true
            publish(GameStatus.PAUSED, "正在释放触点")
            if (shellBacked && afterRelease != null) ShellConnection.releaseForSwitch(::finish)
            else if (shellBacked) ShellConnection.close(::finish)
            else if (current != null) current.stop(::finish) else finish(null)
        } else {
            finish(null)
        }
    }

    private fun resume() {
        val current = profile ?: return
        arm(current, choice)
    }

    private fun editFromOverlay() {
        val current = profile ?: return
        arm(current, choice, edit = true)
    }

    private fun showProfilePicker() {
        val current = profile ?: return
        if (releasing || switchingTo != null || state.value.status !in SWITCH_STATES) return
        val viewport = gameRegion(current) ?: return
        val profiles = repository.forGame(current.gamePackage)
        overlay?.chooseProfile(current, profiles, viewport.safe, ::switchProfile)
    }

    private fun switchProfile(id: String) {
        val current = profile ?: return
        val status = state.value.status
        if (id == current.id || releasing || switchingTo != null || status !in SWITCH_STATES) return
        val next = runCatching {
            repository.load(id).also { require(it.gamePackage == current.gamePackage) { "方案不适用于当前游戏" } }
        }.getOrElse {
            val message = it.message ?: "无法读取方案"
            stop(message, GameStatus.PAUSED)
            toast("无法切换方案 · $message")
            return
        }

        if (status == GameStatus.PAUSED || status == GameStatus.ERROR) {
            if (!saveSelectedProfile(next)) {
                publish(GameStatus.PAUSED, "无法保存所选方案")
                toast("切换失败 · 无法保存所选方案")
                return
            }
            publish(GameStatus.PAUSED, "已切换至 · ${next.name}")
            observeWindow()
            announceProfileSwitch(current, next)
            return
        }

        switchingTo = next
        stopSession("正在切换方案", GameStatus.PAUSED) {
            if (switchingTo !== next) return@stopSession
            val viewport = gameRegion(next)
            if (viewport == null) {
                stop("游戏窗口已变化，请回到横屏游戏后重试", GameStatus.PAUSED)
                return@stopSession
            }
            begin(next, viewport)
        }
    }

    private fun saveSelectedProfile(selected: Profile): Boolean {
        val previous = repository.selectedId
        return runCatching { repository.selectedId = selected.id }.fold(
            onSuccess = { profile = selected; true },
            onFailure = {
                if (repository.selectedId != previous) runCatching { repository.selectedId = previous }
                false
            },
        )
    }

    internal fun announceProfileSwitch(previous: Profile, selected: Profile) {
        if (previous.id != selected.id) toast("方案切换 · ${previous.name} → ${selected.name}")
    }

    private fun toast(message: String) {
        Toast.makeText(app, message, Toast.LENGTH_SHORT).show()
    }

    private fun startObserver() {
        if (!observing) {
            observing = true
            main.post(observer)
        }
    }

    private fun stopObserver() {
        observing = false
        main.removeCallbacks(observer)
    }

    private fun observeWindow() {
        val selected = switchingTo ?: profile ?: return
        val status = state.value.status
        if (releasing) return
        val viewport = gameRegion(selected)
        if (viewport == null) {
            overlay?.clear()
            if (status in ACTIVE_STATES || status == GameStatus.EDITING) {
                stop("游戏已失焦、锁屏或离开横屏，返回后可继续", GameStatus.PAUSED)
            } else if (status == GameStatus.WAITING && SystemClock.uptimeMillis() - waitingSince > 60_000) {
                stop("未找到横屏游戏窗口，请重新开始", GameStatus.ERROR)
            }
            return
        }
        if (status in ACTIVE_STATES && region != viewport) {
            stop("游戏有效区域已变化", GameStatus.PAUSED)
            return
        }
        if (status == GameStatus.EDITING && region != viewport) {
            stop("游戏有效区域已变化，编辑已取消", GameStatus.PAUSED)
            return
        }
        when (status) {
            GameStatus.WAITING -> if (editingRequested) showEditor(selected, viewport) else begin(selected, viewport)
            GameStatus.READY, GameStatus.ACTIVE -> overlay?.controls(
                "暂停", selected, viewport.safe, ::pause, ::stopFromOverlay, ::showProfilePicker,
                mappingViewport = viewport.mapping,
            )
            GameStatus.PAUSED, GameStatus.ERROR -> overlay?.controls(
                "继续", selected, viewport.safe, ::resume, ::stopFromOverlay, ::showProfilePicker,
                ::editFromOverlay, viewport.mapping,
            )
            else -> Unit
        }
    }

    private fun stopFromOverlay() = stop()

    private fun showEditor(selected: Profile, viewport: GameRegion) {
        val currentOverlay = overlay ?: return
        region = viewport
        val editable = runCatching { repository.editable(selected.id) }.getOrElse {
            stop(it.message ?: "无法打开映射编辑", GameStatus.ERROR)
            return
        }
        publish(GameStatus.EDITING, selected.name, viewport = viewport.mapping)
        runCatching {
            currentOverlay.editor(
                selected, viewport.mapping,
                save = save@{ points, ranges ->
                    if (points.isEmpty() && ranges.isEmpty()) {
                        stop("映射位置未修改", GameStatus.PAUSED)
                        return@save
                    }
                    val entries = editable.getJSONArray("mappings")
                    for (index in 0 until entries.length()) {
                        val entry = entries.getJSONObject(index)
                        val id = entry.getString("id")
                        points[id]?.let { point ->
                            entry.getJSONObject("point").put("x", point.x.toDouble()).put("y", point.y.toDouble())
                        }
                        ranges[id]?.let { extent ->
                            entry.getJSONObject("rangeAt1200").put("left", extent.left.toDouble())
                                .put("right", extent.right.toDouble()).put("up", extent.up.toDouble())
                                .put("down", extent.down.toDouble())
                        }
                    }
                    val saved = repository.saveEdit(selected.id, editable)
                    profile = saved
                    stop("映射位置已保存", GameStatus.PAUSED)
                },
                cancel = { stop("编辑已取消", GameStatus.PAUSED) },
            )
        }.onFailure { stop(it.message ?: "无法打开编辑浮层", GameStatus.ERROR) }
    }

    private fun begin(selected: Profile, viewport: GameRegion) {
        val failureStatus = if (switchingTo === selected) GameStatus.PAUSED else GameStatus.ERROR
        val capture = service ?: return
        val attached = ControllerInput.currentController()
        if (attached == null) {
            stop("未连接实体手柄", GameStatus.PAUSED)
            return
        }
        val targetUid = try {
            app.packageManager.getApplicationInfo(selected.gamePackage, 0).uid
        } catch (_: Exception) {
            stop("无法核实游戏应用身份", failureStatus)
            return
        }
        if (choice == BackendChoice.ACCESSIBILITY) shellBacked = false
        else if (ShellConnection.available()) shellBacked = true
        else {
            stop("Shizuku 不可用", failureStatus)
            return
        }
        val hybrid = repository.hybridTouch && shellBacked
        if (hybrid && !capture.canCaptureMainScreen()) {
            stop("当前系统未识别可并用的主屏触摸设备，可在设置关闭并用", failureStatus)
            return
        }
        val currentToken = ++token
        val backendName = when {
            hybrid -> "Shizuku · 手柄与触屏并用"
            shellBacked -> "Shizuku"
            else -> "无障碍 · 兼容性测试"
        }
        region = viewport
        deviceId = attached.id
        publish(GameStatus.STARTING, "正在准备触控会话", backendName, viewport.mapping)
        fun fail(message: String) {
            if (currentToken == token) stop(message, failureStatus)
        }
        fun accepted() {
            if (currentToken == token && state.value.status == GameStatus.READY) {
                publish(GameStatus.ACTIVE, selected.name, backendName, viewport.mapping)
            }
        }
        fun ready(newBackend: TouchBackend) {
            if (currentToken != token) return
            if (gameRegion(selected) != viewport) {
                fail("启动时游戏窗口已变化")
                return
            }
            val prepared = runCatching {
                val nextEngine = MappingEngine(selected, viewport.mapping, repository.calibration(attached))
                capture.capture(true, screen = hybrid)
                nextEngine
            }.getOrElse {
                fail(it.message ?: "无法初始化映射")
                return
            }
            val switched = switchingTo === selected
            val previous = profile
            if (switched && !saveSelectedProfile(selected)) {
                fail("无法保存所选方案")
                return
            }
            if (switched) switchingTo = null
            controller.reset()
            engine = prepared
            backend = newBackend
            started = SystemClock.uptimeMillis()
            hadContacts = false
            lastTargetCheck = 0L
            screenContacts = if (hybrid) ScreenContacts() else null
            Log.i(TAG, "session_ready profile=${selected.id} backend=$backendName viewport=${viewport.safe} " +
                "mappingViewport=${viewport.mapping} device=${attached.id}")
            publish(GameStatus.READY, if (hybrid) "等待手柄或触屏动作" else "等待手柄动作", backendName, viewport.mapping)
            observeWindow()
            if (currentToken == token) {
                if (switched && previous != null) announceProfileSwitch(previous, selected)
                else toast("已开始控制 · ${selected.name}")
            }
            tick(currentToken)
        }
        if (shellBacked) ShellConnection.backend(app, targetUid, ::ready, ::fail, ::accepted, selected.gamePackage)
        else ready(AccessibilityTouchBackend(capture, ::fail, ::accepted))
    }

    private fun tick(currentToken: Int) {
        if (currentToken != token || backend == null) return
        val now = SystemClock.uptimeMillis()
        if (shellBacked && now - lastHealthCheck > 750) {
            lastHealthCheck = now
            if (!ShellConnection.available()) {
                stop("Shizuku 停止或权限已撤销", GameStatus.ERROR)
                return
            }
        }
        render()
        main.postDelayed({ tick(currentToken) }, 16L)
    }

    private fun render(checkTarget: Boolean = false) {
        val now = SystemClock.uptimeMillis()
        val generated = engine?.frame(controller.state, now) ?: return
        val controllerContacts = panelContacts.filter(generated) { overlay?.covers(it) == true }
        val contacts = screenContacts?.combine(controllerContacts) ?: controllerContacts
        if (contacts.isNotEmpty() && (checkTarget || !hadContacts || now - lastTargetCheck >= 48)) {
            val selected = profile ?: return
            if (gameRegion(selected) != region) {
                stop("触控前检查发现游戏已失焦或区域变化", GameStatus.PAUSED)
                return
            }
            lastTargetCheck = now
        }
        hadContacts = contacts.isNotEmpty()
        backend?.frame(contacts)
    }

    private fun gameRegion(selected: Profile): GameRegion? {
        val capture = service ?: return null
        if (!app.getSystemService(PowerManager::class.java).isInteractive ||
            app.getSystemService(KeyguardManager::class.java).isKeyguardLocked) return null
        val window = try {
            val windows = capture.windows
            if (windows.any { it.displayId == 0 && it.isFocused &&
                    it.type != AccessibilityWindowInfo.TYPE_APPLICATION &&
                    it.type != AccessibilityWindowInfo.TYPE_ACCESSIBILITY_OVERLAY }) return null
            windows.firstOrNull {
                it.displayId == 0 && it.type == AccessibilityWindowInfo.TYPE_APPLICATION && it.isFocused
            }?.takeIf { it.root?.packageName?.toString() == selected.gamePackage }
        } catch (_: SecurityException) {
            return null
        } ?: return null
        val bounds = Rect()
        window.getBoundsInScreen(bounds)
        val metrics = capture.getSystemService(WindowManager::class.java).maximumWindowMetrics
        val screen = metrics.bounds
        val cutout = metrics.windowInsets.getInsets(WindowInsets.Type.displayCutout())
        val windowRight = minOf(bounds.right, screen.right)
        val safeBounds = Rect(screen.left + cutout.left, screen.top + cutout.top,
            screen.right - cutout.right, screen.bottom - cutout.bottom)
        if (!bounds.intersect(safeBounds) || bounds.width() <= bounds.height() || bounds.height() <= 1) return null
        val safe = Viewport(bounds.left, bounds.top, bounds.width(), bounds.height())
        // The Arena HUD stays fixed when the camera cutout changes sides.
        val mapping = if (selected.id == ProfileRepository.ARENA_ID) {
            safe.withLeftCutoutReference(cutout.left, cutout.right, windowRight)
        } else safe
        return GameRegion(safe, mapping)
    }

    override fun onInputDeviceAdded(deviceId: Int) {
        val device = InputDevice.getDevice(deviceId) ?: return
        if (ControllerInput.isController(device)) toast("手柄已连接 · ${device.name}")
    }

    override fun onInputDeviceRemoved(deviceId: Int) {
        if (deviceId == this.deviceId) stop("手柄已断开，重连后可继续", GameStatus.PAUSED)
        else if (screenContacts?.usesDevice(deviceId) == true) stop("触摸设备已断开", GameStatus.PAUSED)
    }

    override fun onInputDeviceChanged(deviceId: Int) {
        if (deviceId == this.deviceId) stop("手柄能力已变化，请继续前确认设备", GameStatus.PAUSED)
    }

    private fun publish(status: GameStatus, detail: String, backend: String = "", viewport: Viewport? = null) {
        val next = GameSnapshot(status, detail, backend, viewport)
        if (mutableState.value == next) return
        mutableState.value = next
        val entry = listOf(status.label, detail, backend).filter(String::isNotBlank).joinToString(" · ")
        mutableLog.value = (mutableLog.value + entry).takeLast(40)
        Log.i(TAG, entry)
    }

    private val ACTIVE_STATES = setOf(GameStatus.STARTING, GameStatus.READY, GameStatus.ACTIVE)
    private val SWITCH_STATES = setOf(GameStatus.READY, GameStatus.ACTIVE, GameStatus.PAUSED, GameStatus.ERROR)
}
