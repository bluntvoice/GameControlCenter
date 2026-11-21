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
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.WindowInsets
import android.view.WindowManager
import android.view.accessibility.AccessibilityWindowInfo
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
    private lateinit var app: Context
    lateinit var repository: ProfileRepository
        private set
    var service: ControllerService? = null
        private set
    private var overlay: GameOverlay? = null
    private var profile: Profile? = null
    private var choice = BackendChoice.AUTO
    private var editingRequested = false
    private var deviceId: Int? = null
    private var started = 0L
    private var waitingSince = 0L
    private var token = 0
    private var region: Viewport? = null
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

    fun stop(reason: String = "", status: GameStatus = GameStatus.STOPPED) {
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
        mutableInput.value = InputSnapshot()
        if (status == GameStatus.STOPPED || service == null) {
            profile = null
            stopObserver()
        }
        overlay?.clear()
        fun finish(error: String?) {
            releasing = false
            val label = when {
                error != null -> GameStatus.ERROR
                stopAfterRelease -> GameStatus.STOPPED
                else -> status
            }
            stopAfterRelease = false
            val detail = error ?: reason
            Log.i(TAG, "session_end status=$label detail=$detail")
            publish(label, detail)
            if (observing) observeWindow()
        }
        if (current != null || wasStarting) {
            releasing = true
            publish(GameStatus.PAUSED, "正在释放触点")
            if (shellBacked) ShellConnection.close(::finish)
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
        val selected = profile ?: return
        val status = state.value.status
        if (releasing) return
        val viewport = gameViewport(selected.gamePackage)
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
            GameStatus.READY, GameStatus.ACTIVE -> overlay?.controls("暂停", selected, viewport, ::pause, ::stopFromOverlay)
            GameStatus.PAUSED, GameStatus.ERROR -> overlay?.controls("继续", selected, viewport, ::resume, ::stopFromOverlay, ::editFromOverlay)
            else -> Unit
        }
    }

    private fun stopFromOverlay() = stop()

    private fun showEditor(selected: Profile, viewport: Viewport) {
        val currentOverlay = overlay ?: return
        region = viewport
        val editable = runCatching { repository.editable(selected.id) }.getOrElse {
            stop(it.message ?: "无法打开映射编辑", GameStatus.ERROR)
            return
        }
        publish(GameStatus.EDITING, selected.name, viewport = viewport)
        runCatching {
            currentOverlay.editor(
                selected, viewport,
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

    private fun begin(selected: Profile, viewport: Viewport) {
        val capture = service ?: return
        val attached = ControllerInput.currentController()
        if (attached == null) {
            stop("未连接实体手柄", GameStatus.PAUSED)
            return
        }
        val targetUid = try {
            app.packageManager.getApplicationInfo(selected.gamePackage, 0).uid
        } catch (_: Exception) {
            stop("无法核实游戏应用身份", GameStatus.ERROR)
            return
        }
        if (choice == BackendChoice.ACCESSIBILITY) shellBacked = false
        else if (ShellConnection.available()) shellBacked = true
        else {
            stop("Shizuku 不可用", GameStatus.ERROR)
            return
        }
        val hybrid = repository.hybridTouch && shellBacked
        if (hybrid && !capture.canCaptureMainScreen()) {
            stop("当前系统未识别可并用的主屏触摸设备，可在设置关闭并用", GameStatus.ERROR)
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
        publish(GameStatus.STARTING, "正在准备触控会话", backendName, viewport)
        fun fail(message: String) {
            if (currentToken == token) stop(message, GameStatus.ERROR)
        }
        fun accepted() {
            if (currentToken == token && state.value.status == GameStatus.READY) {
                publish(GameStatus.ACTIVE, selected.name, backendName, viewport)
            }
        }
        fun ready(newBackend: TouchBackend) {
            if (currentToken != token) return
            if (gameViewport(selected.gamePackage) != viewport) {
                fail("启动时游戏窗口已变化")
                return
            }
            controller.reset()
            engine = MappingEngine(selected, viewport, repository.calibration(attached))
            backend = newBackend
            started = SystemClock.uptimeMillis()
            hadContacts = false
            lastTargetCheck = 0L
            screenContacts = if (hybrid) ScreenContacts() else null
            capture.capture(true, screen = hybrid)
            Log.i(TAG, "session_ready profile=${selected.id} backend=$backendName viewport=$viewport device=${attached.id}")
            publish(GameStatus.READY, if (hybrid) "等待手柄或触屏动作" else "等待手柄动作", backendName, viewport)
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
        val controllerContacts = engine?.frame(controller.state, now) ?: return
        val contacts = screenContacts?.combine(controllerContacts) ?: controllerContacts
        if (contacts.isNotEmpty() && (checkTarget || !hadContacts || now - lastTargetCheck >= 48)) {
            val target = profile?.gamePackage ?: return
            if (gameViewport(target) != region) {
                stop("触控前检查发现游戏已失焦或区域变化", GameStatus.PAUSED)
                return
            }
            lastTargetCheck = now
        }
        if (controllerContacts.isNotEmpty() && overlay?.covers(controllerContacts) == true) {
            val message = "悬浮条遮住了映射触点，请拖到空白处"
            stop(message, GameStatus.PAUSED)
            android.widget.Toast.makeText(app, message, android.widget.Toast.LENGTH_SHORT).show()
            return
        }
        hadContacts = contacts.isNotEmpty()
        backend?.frame(contacts)
    }

    private fun gameViewport(target: String): Viewport? {
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
            }?.takeIf { it.root?.packageName?.toString() == target }
        } catch (_: SecurityException) {
            return null
        } ?: return null
        val bounds = Rect()
        window.getBoundsInScreen(bounds)
        val metrics = capture.getSystemService(WindowManager::class.java).maximumWindowMetrics
        val screen = metrics.bounds
        val safe = metrics.windowInsets.getInsets(WindowInsets.Type.displayCutout())
        val safeBounds = Rect(screen.left + safe.left, screen.top + safe.top,
            screen.right - safe.right, screen.bottom - safe.bottom)
        if (!bounds.intersect(safeBounds) || bounds.width() <= bounds.height() || bounds.height() <= 1) return null
        return Viewport(bounds.left, bounds.top, bounds.width(), bounds.height())
    }

    override fun onInputDeviceAdded(deviceId: Int) = Unit

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
}
