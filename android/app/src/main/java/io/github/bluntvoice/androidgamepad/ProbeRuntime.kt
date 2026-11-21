package io.github.bluntvoice.androidgamepad

import android.app.KeyguardManager
import android.content.Context
import android.hardware.input.InputManager
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import android.util.Log
import android.view.KeyEvent
import android.view.MotionEvent
import rikka.shizuku.Shizuku
import kotlin.math.abs

enum class BackendChoice { AUTO, ACCESSIBILITY, SHIZUKU }
enum class ProbeMode { CONTROLLER, SEQUENCE }

object ProbeRuntime : InputManager.InputDeviceListener {
    const val TAG = "GamepadProbe"
    private val main = Handler(Looper.getMainLooper())
    private val input = ControllerInput()
    private lateinit var context: Context
    private var engine: MappingEngine? = null
    private var backend: TouchBackend? = null
    private var usingShizuku = false
    private var mode = ProbeMode.CONTROLLER
    private var token = 0
    private var started = 0L
    private var testView: ProbeView? = null
    private var viewport: Viewport? = null
    private var controllerId: Int? = null
    private var preparing = false
    private var stopping = false
    private var lastInputLog = 0L
    private var source = ""
    var service: ControllerService? = null
    var status = "已暂停"
        private set
    val running get() = backend != null
    val hasSession get() = preparing || running || stopping
    val controllerState get() = input.state

    fun initialize(app: Context) {
        if (::context.isInitialized) return
        context = app.applicationContext
        context.getSystemService(InputManager::class.java).registerInputDeviceListener(this, main)
        Shizuku.addBinderDeadListener { main.post { ShellConnection.lost("Shizuku 已停止") } }
    }

    fun attach(view: ProbeView, area: Viewport) {
        if (testView != null && viewport != area) stop("测试区域已变化")
        testView = view
        viewport = area
    }

    fun detach(view: ProbeView) {
        if (testView !== view) return
        stop("测试窗口失去焦点")
        testView = null
        viewport = null
    }

    fun start(choice: BackendChoice, probeMode: ProbeMode, durationMs: Long) {
        if (hasSession) return
        val area = viewport ?: return
        if (!screenAvailable()) return
        mode = probeMode
        controllerId = ControllerInput.currentController()?.id
        if (mode == ProbeMode.CONTROLLER && controllerId == null) {
            update("未连接实体手柄")
            return
        }
        usingShizuku = when (choice) {
            BackendChoice.AUTO -> ShellConnection.available()
            BackendChoice.ACCESSIBILITY -> false
            BackendChoice.SHIZUKU -> true
        }
        if (!usingShizuku && service == null) {
            update("等待授权无障碍服务")
            return
        }
        val attempt = ++token
        preparing = true
        update("服务准备中")
        fun accept(ready: TouchBackend) {
            if (attempt != token) return
            preparing = false
            input.reset()
            source = ""
            engine = MappingEngine(testProfile, area)
            backend = ready
            started = SystemClock.uptimeMillis()
            if (mode == ProbeMode.CONTROLLER) service?.capture(true)
            testView?.resetStats()
            update(if (usingShizuku) "控制中 · Shizuku" else "控制中 · 无障碍")
            tick(attempt, durationMs)
        }
        val failed: (String) -> Unit = { message -> if (attempt == token) stop("控制异常 · $message") }
        if (usingShizuku) ShellConnection.backend(context, ready = ::accept, fail = failed)
        else accept(AccessibilityTouchBackend(requireNotNull(service), failed))
    }

    fun stop(reason: String = "已暂停") {
        if (stopping) return
        if (!preparing && backend == null) {
            update(reason)
            return
        }
        ++token
        service?.capture(false)
        preparing = false
        stopping = true
        val active = backend
        backend = null
        engine = null
        input.reset()
        update("正在释放触点")
        val finish: (String?) -> Unit = { error ->
            stopping = false
            Log.i(TAG, "session_end result=${error ?: "ok"} reason=$reason")
            update(if (error == null) reason else "控制异常 · $error")
        }
        if (usingShizuku) ShellConnection.close(finish)
        else if (active != null) active.stop(finish) else finish(null)
    }

    fun accepts(deviceId: Int) = running && mode == ProbeMode.CONTROLLER && deviceId == controllerId

    fun key(event: KeyEvent, origin: String): Boolean {
        if (!accepts(event.deviceId)) return false
        if (!input.key(event, started)) return false
        if (event.repeatCount == 0) {
            Log.i(TAG, "key origin=$origin device=${event.deviceId} code=${event.keyCode} action=${event.action}")
        }
        acceptInput(origin)
        return true
    }

    fun isSessionPress(event: KeyEvent) = event.downTime >= started

    fun motion(event: MotionEvent, origin: String): Boolean {
        if (!accepts(event.deviceId) || !event.isFromSource(android.view.InputDevice.SOURCE_JOYSTICK)) return false
        for (position in 0 until event.historySize) {
            input.motion(event, position)
            render(input.state)
        }
        input.motion(event)
        acceptInput(origin)
        return true
    }

    private fun acceptInput(origin: String) {
        source = origin
        val now = SystemClock.uptimeMillis()
        if (now - lastInputLog >= 500) {
            Log.i(TAG, "input origin=$origin device=$controllerId ${input.state}")
            lastInputLog = now
        }
        render(input.state)
    }

    private fun tick(attempt: Int, durationMs: Long) {
        if (attempt != token || testView == null || !running) return
        if (!screenAvailable()) {
            stop("屏幕已锁定或关闭")
            return
        }
        val elapsed = SystemClock.uptimeMillis() - started
        if (mode == ProbeMode.SEQUENCE && elapsed >= durationMs) {
            stop("测试序列已结束")
            return
        }
        val state = if (mode == ProbeMode.CONTROLLER) input.state else sequence(elapsed)
        render(state)
        testView?.diagnostics(status, state, source.ifBlank { if (mode == ProbeMode.SEQUENCE) "测试序列" else "等待输入" })
        main.postDelayed({ tick(attempt, durationMs) }, 16)
    }

    private fun render(state: ControllerState) {
        engine?.frame(state, SystemClock.uptimeMillis())?.let { backend?.frame(it) }
    }

    private fun screenAvailable() = context.getSystemService(PowerManager::class.java).isInteractive &&
        !context.getSystemService(KeyguardManager::class.java).isKeyguardLocked

    private fun update(value: String) {
        status = value
        testView?.diagnostics(status, input.state, source)
    }

    override fun onInputDeviceAdded(deviceId: Int) = Unit
    override fun onInputDeviceChanged(deviceId: Int) {
        if (deviceId == controllerId && mode == ProbeMode.CONTROLLER && hasSession) {
            stop("手柄能力已变化，请重新开始")
        }
    }
    override fun onInputDeviceRemoved(deviceId: Int) {
        service?.forgetDevice(deviceId)
        if (deviceId == controllerId && mode == ProbeMode.CONTROLLER && hasSession) {
            stop("手柄已断开，请重连后重新开始")
        }
    }

    private fun sequence(elapsed: Long): ControllerState {
        val sample = elapsed % 1000
        val cameraX = if (sample < 500) .48f else -.48f
        val buttons = when {
            elapsed >= 2000 && elapsed < 1600 + 400 * 101 && (elapsed - 2000) % 400 < 60 -> setOf(Button.RB)
            elapsed >= 45_000 && elapsed % 5000 in 3300L..3899L -> setOf(Button.LB)
            else -> emptySet()
        }
        return ControllerState(Point(.17f, -.76f), Point(cameraX, 0f), buttons)
    }

    private val testProfile = Profile("probe", 1, "并发测试", "io.github.bluntvoice.androidgamepad",
        Parameters(cameraSpeed = 500f), listOf(
            Mapping("left", Action.JOYSTICK, Point(.21f, .68f), extent = Extent(90f, 90f, 90f, 90f)),
            Mapping("right", Action.CAMERA, Point(.55f, .54f)),
            Mapping("LB", Action.HOLD, Point(.82f, .70f), Button.LB),
            Mapping("RB", Action.TAP, Point(.82f, .48f), Button.RB),
            Mapping("Y", Action.AIM, Point(.82f, .56f), Button.Y),
            Mapping("X", Action.REPEAT, Point(.75f, .65f), Button.X, repeatHz = 3f),
            Mapping("A", Action.TAP, Point(.72f, .43f), Button.A),
            Mapping("B", Action.HOLD, Point(.9f, .6f), Button.B),
            Mapping("LT", Action.HOLD, Point(.63f, .72f), Button.LT),
            Mapping("RT", Action.HOLD, Point(.9f, .43f), Button.RT),
        ))
}
