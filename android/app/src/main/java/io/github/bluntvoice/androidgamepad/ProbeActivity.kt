package io.github.bluntvoice.androidgamepad

import android.app.Activity
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.os.Bundle
import android.os.SystemClock
import android.util.Log
import android.view.Gravity
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.WindowInsets
import android.view.WindowInsetsController
import android.view.WindowManager
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import java.util.Locale

class ProbeActivity : Activity() {
    private lateinit var helper: ProbeView
    private lateinit var choice: BackendChoice

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        choice = BackendChoice.valueOf(intent.getStringExtra("backend") ?: BackendChoice.AUTO.name)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        helper = ProbeView(this)
        val frame = FrameLayout(this).apply {
            addView(helper, FrameLayout.LayoutParams(-1, -1))
        }
        val tools = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            action("手柄测试") { ProbeRuntime.start(choice, ProbeMode.CONTROLLER, 0) }
            action("短序列") { ProbeRuntime.start(choice, ProbeMode.SEQUENCE, 9000) }
            action("5 分钟序列") { ProbeRuntime.start(choice, ProbeMode.SEQUENCE, 300_000) }
            action("暂停") { ProbeRuntime.stop() }
            action("返回") { finish() }
        }
        frame.addView(tools, FrameLayout.LayoutParams(-1, -2, Gravity.TOP))
        setContentView(frame)
        window.insetsController?.apply {
            hide(WindowInsets.Type.systemBars())
            systemBarsBehavior = WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }
        helper.addOnLayoutChangeListener { _, _, _, _, _, _, _, _, _ -> attachIfFocused() }
    }

    private fun LinearLayout.action(label: String, callback: () -> Unit) {
        addView(Button(this@ProbeActivity).apply { text = label; setOnClickListener { callback() } })
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) attachIfFocused() else if (::helper.isInitialized) ProbeRuntime.detach(helper)
    }

    override fun onPause() {
        if (::helper.isInitialized) ProbeRuntime.detach(helper)
        super.onPause()
    }

    override fun dispatchKeyEvent(event: KeyEvent): Boolean =
        ProbeRuntime.key(event, "Activity") || super.dispatchKeyEvent(event)

    override fun dispatchGenericMotionEvent(event: MotionEvent): Boolean =
        ProbeRuntime.motion(event, "Activity") || super.dispatchGenericMotionEvent(event)

    private fun attachIfFocused() {
        if (!hasWindowFocus() || helper.width <= 1 || helper.height <= 1) return
        val location = IntArray(2)
        helper.getLocationOnScreen(location)
        ProbeRuntime.attach(helper, Viewport(location[0], location[1], helper.width, helper.height))
    }
}

class ProbeView(context: Context) : View(context) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val active = linkedMapOf<Int, Point>()
    private val roles = mutableMapOf<Int, String>()
    private var received = 0
    private var peak = 0
    private var cancelled = 0
    private var shoulderDown = 0
    private var rightMovesWithShoulder = 0
    private var diagnostics = "已暂停"
    private var firstDownTime = 0L
    private val density = resources.displayMetrics.density

    fun diagnostics(status: String, state: ControllerState, source: String) {
        diagnostics = String.format(Locale.ROOT,
            "%s  ·  %s\n左  %.2f / %.2f     右  %.2f / %.2f     LT %.2f  RT %.2f     %s",
            status, source, state.left.x, state.left.y, state.right.x, state.right.y, state.lt, state.rt,
            state.buttons.joinToString(" "))
        invalidate()
    }

    fun resetStats() {
        active.clear()
        roles.clear()
        received = 0
        peak = 0
        cancelled = 0
        shoulderDown = 0
        rightMovesWithShoulder = 0
        Log.i(ProbeRuntime.TAG, "probe_reset width=$width height=$height")
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        received++
        val actionIndex = event.actionIndex
        val id = event.getPointerId(actionIndex)
        val action = event.actionMasked
        if (action == MotionEvent.ACTION_DOWN) firstDownTime = event.downTime
        if (action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_POINTER_DOWN) {
            val x = event.getX(actionIndex) / width
            val y = event.getY(actionIndex) / height
            val role = when {
                x < .35f -> "left"
                x < .62f -> "right"
                x in .78f.. .85f && y in .45f.. .51f -> "RB"
                x in .78f.. .85f && y in .67f.. .73f -> "LB"
                else -> "other"
            }
            roles[id] = role
            if (role == "RB" && "left" in roles.values && "right" in roles.values) shoulderDown++
        }
        val liveIds = (0 until event.pointerCount).associate {
            event.getPointerId(it) to Point(event.getX(it), event.getY(it))
        }
        if (action == MotionEvent.ACTION_MOVE && roles.values.any { it == "RB" || it == "LB" }) {
            val right = roles.entries.firstOrNull { it.value == "right" }?.key
            if (right != null && active[right] != liveIds[right]) rightMovesWithShoulder++
        }
        active.clear()
        active.putAll(liveIds)
        peak = maxOf(peak, event.pointerCount)
        val role = roles[id].orEmpty()
        val before = active.size
        when (action) {
            MotionEvent.ACTION_UP, MotionEvent.ACTION_POINTER_UP -> { active.remove(id); roles.remove(id) }
            MotionEvent.ACTION_CANCEL -> { active.clear(); roles.clear(); cancelled++ }
        }
        if (action != MotionEvent.ACTION_MOVE) {
            Log.i(ProbeRuntime.TAG,
                "touch action=${MotionEvent.actionToString(event.action)} id=$id role=$role " +
                    "before=$before live=${active.size} ids=${liveIds.keys.joinToString(",")} " +
                    "down=${event.downTime} streamDown=$firstDownTime delay=${SystemClock.uptimeMillis() - event.eventTime} " +
                    "rb=$shoulderDown rightDuring=$rightMovesWithShoulder cancellations=$cancelled")
            if (action == MotionEvent.ACTION_UP) performClick()
        }
        invalidate()
        return true
    }

    override fun performClick(): Boolean {
        super.performClick()
        return true
    }

    override fun onDraw(canvas: Canvas) {
        canvas.drawColor(Color.rgb(23, 28, 36))
        paint.color = Color.WHITE
        paint.textSize = 14 * density
        val lines = diagnostics.split('\n') + "事件 $received   当前触点 ${active.size}   峰值 $peak   RB 并发 $shoulderDown   按肩键时右摇杆移动 $rightMovesWithShoulder"
        lines.forEachIndexed { index, line -> canvas.drawText(line, 14 * density, (72 + 19 * index) * density, paint) }
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 2 * density
        paint.color = Color.rgb(116, 137, 168)
        listOf(Point(.21f, .68f), Point(.55f, .54f), Point(.82f, .70f), Point(.82f, .48f))
            .forEach { canvas.drawCircle(it.x * width, it.y * height, 24 * density, paint) }
        paint.style = Paint.Style.FILL
        paint.color = Color.rgb(154, 218, 253)
        active.values.forEach { canvas.drawCircle(it.x, it.y, 12 * density, paint) }
    }
}
