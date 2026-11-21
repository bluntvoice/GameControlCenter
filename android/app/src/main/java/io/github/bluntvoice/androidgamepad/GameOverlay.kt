package io.github.bluntvoice.androidgamepad

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Typeface
import android.os.SystemClock
import android.text.TextUtils
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowManager
import android.widget.Button as NativeButton
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import kotlin.math.hypot
import kotlin.math.roundToInt

class GameOverlay(private val context: Context, private val repository: ProfileRepository) {
    private val windows = context.getSystemService(WindowManager::class.java)
    private var panel: View? = null
    private var panelKey = ""

    private var hints: HintCanvas? = null
    private var hintsKey: Triple<String, Int, Viewport>? = null
    private val panelLocation = IntArray(2)

    fun controls(
        label: String,
        profile: Profile,
        viewport: Viewport,
        toggle: () -> Unit,
        stop: () -> Unit,
        edit: (() -> Unit)? = null,
        mappingViewport: Viewport = viewport,
    ) {
        showHints(profile, mappingViewport)
        if (panelKey == label && panel != null) return
        clearPanel()
        val params = positioned(-2, -2, viewport).apply {
            flags = flags or WindowManager.LayoutParams.FLAG_SPLIT_TOUCH
        }
        val grip = TextView(context).apply {
            text = "⠿"
            contentDescription = "拖动控制悬浮条"
            textSize = 20f
            minWidth = dp(36)
            minHeight = dp(48)
            gravity = Gravity.CENTER
            setTextColor(Color.WHITE)
        }
        val buttons = row().apply {
            alpha = repository.panelOpacity
            background = GradientDrawable().apply {
                setColor(0xFF25303E.toInt())
                cornerRadius = dp(16).toFloat()
            }
            addView(grip)
            addView(button(label, toggle, compact = true))
            if (edit != null) addView(button("编辑", edit, compact = true))
            addView(button("停止", stop, compact = true))
        }
        buttons.measure(View.MeasureSpec.UNSPECIFIED, View.MeasureSpec.UNSPECIFIED)
        val xTravel = (viewport.width - buttons.measuredWidth).coerceAtLeast(0)
        val yTravel = (viewport.height - buttons.measuredHeight).coerceAtLeast(0)
        val placement = repository.panelPlacement
        params.x += (xTravel * placement.x).roundToInt()
        params.y += (yTravel * placement.y).roundToInt()
        var downX = 0f
        var downY = 0f
        var left = 0
        var top = 0
        val slop = ViewConfiguration.get(context).scaledTouchSlop
        var moved = false
        grip.setOnTouchListener { _, event ->
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    downX = event.rawX
                    downY = event.rawY
                    left = params.x
                    top = params.y
                    moved = false
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = event.rawX - downX
                    val dy = event.rawY - downY
                    if (moved || hypot(dx, dy) >= slop) {
                        moved = true
                        params.x = (left + dx.roundToInt()).coerceIn(viewport.left, viewport.left + xTravel)
                        params.y = (top + dy.roundToInt()).coerceIn(viewport.top, viewport.top + yTravel)
                        runCatching { windows.updateViewLayout(buttons, params) }
                    }
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> if (moved) {
                    repository.savePanelPlacement(Point((params.x - viewport.left).toFloat() / xTravel.coerceAtLeast(1),
                        (params.y - viewport.top).toFloat() / yTravel.coerceAtLeast(1)))
                }
            }
            true
        }
        show(buttons, params, label)
    }

    fun pressed(buttons: Set<Button>) {
        hints?.pressed(buttons)
    }

    fun covers(contacts: List<Contact>): Boolean {
        val current = panel ?: return false
        if (!current.isLaidOut || panelKey == "editor") return false
        current.getLocationOnScreen(panelLocation)
        val (left, top) = panelLocation
        fun inside(point: Point) = point.x >= left && point.x < left + current.width &&
            point.y >= top && point.y < top + current.height
        return contacts.any { inside(it.anchor) || inside(it.point) }
    }

    private fun showHints(profile: Profile, viewport: Viewport) {
        if (!repository.showHints) {
            clearHints()
            return
        }
        val key = Triple(profile.id, profile.revision, viewport)
        if (hintsKey == key) return
        clearHints()
        val view = HintCanvas(context, profile, repository.hintOpacity, repository::hintColor).apply {
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        }
        val params = positioned(viewport.width, viewport.height, viewport).apply {
            flags = flags or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
            title = "安卓手柄控制台键位提示"
        }
        runCatching { windows.addView(view, params) }.onSuccess {
            hints = view
            hintsKey = key
        }
    }

    private fun positioned(width: Int, height: Int, viewport: Viewport) = layout(width, height).apply {
        gravity = Gravity.TOP or Gravity.LEFT
        x = viewport.left
        y = viewport.top
        flags = flags or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
        fitInsetsTypes = 0
    }
    fun editor(
        profile: Profile,
        viewport: Viewport,
        save: (Map<String, Point>, Map<String, Extent>) -> Unit,
        cancel: () -> Unit,
    ) {
        clear()
        val frame = FrameLayout(context)
        val label = TextView(context).apply {
            text = "拖动按键以调整位置"
            setTextColor(Color.WHITE)
            textSize = 14f
            isSingleLine = true
            ellipsize = TextUtils.TruncateAt.END
            setPadding(dp(12), 0, dp(12), 0)
        }
        val canvas = EditorCanvas(context, profile, repository::hintColor) { label.text = it }
        frame.addView(canvas, FrameLayout.LayoutParams(-1, -1))
        val toolbar = row().apply {
            setBackgroundColor(0xEE233043.toInt())
            addView(label, LinearLayout.LayoutParams(dp(160), -2))
            addView(button("范围 −", { canvas.resize(-8f) }))
            addView(button("范围 +", { canvas.resize(8f) }))
            addView(button("取消", cancel))
            addView(button("保存", {
                runCatching { save(canvas.positions(), canvas.ranges()) }.onFailure {
                    Toast.makeText(context, it.message ?: "无法保存映射", Toast.LENGTH_LONG).show()
                }
            }))
        }
        frame.addView(toolbar, FrameLayout.LayoutParams(-2, -2, Gravity.TOP or Gravity.CENTER_HORIZONTAL))
        val params = layout(viewport.width, viewport.height).apply {
            gravity = Gravity.TOP or Gravity.START
            x = viewport.left
            y = viewport.top
            flags = flags or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
        }
        show(frame, params, "editor", strict = true)
    }

    fun clear() {
        clearPanel()
        clearHints()
    }

    private fun clearHints() {
        val previous = hints
        hints = null
        hintsKey = null
        if (previous != null) runCatching { windows.removeViewImmediate(previous) }
    }

    private fun clearPanel() {
        val previous = panel
        panel = null
        panelKey = ""
        if (previous != null) runCatching { windows.removeViewImmediate(previous) }
    }

    private fun show(view: View, params: WindowManager.LayoutParams, key: String, strict: Boolean = false) {
        runCatching { windows.addView(view, params) }.onSuccess {
            panel = view
            panelKey = key
        }.onFailure {
            if (strict) throw it
        }
    }

    private fun row() = LinearLayout(context).apply {
        gravity = Gravity.CENTER_VERTICAL
        orientation = LinearLayout.HORIZONTAL
    }

    private fun button(label: String, action: () -> Unit, compact: Boolean = false): View =
        if (compact) TextView(context).apply {
            text = label
            textSize = 13f
            minHeight = dp(48)
            gravity = Gravity.CENTER
            setPadding(dp(11), 0, dp(11), 0)
            setTextColor(Color.WHITE)
            isFocusable = true
            setOnClickListener { action() }
        } else NativeButton(context).apply {
            text = label
            setOnClickListener { action() }
        }

    private fun layout(width: Int, height: Int) = WindowManager.LayoutParams(
        width, height, WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
        PixelFormat.TRANSLUCENT,
    ).apply {
        layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS
        title = "安卓手柄控制台"
    }

    private fun dp(value: Int) = (context.resources.displayMetrics.density * value).toInt()
}

private class EditorCanvas(
    context: Context,
    profile: Profile,
    private val color: (HintKey) -> Int,
    private val selectedLabel: (String) -> Unit,
) :
    View(context) {
    private data class Marker(val mapping: Mapping, var point: Point, var extent: Extent?)
    private val markers = profile.mappings.map { Marker(it, it.point, it.extent) }
    private val brush = Paint(Paint.ANTI_ALIAS_FLAG)
    private val density = resources.displayMetrics.density
    private var selected: Marker? = null
    private var dragging = false

    init {
        contentDescription = "游戏触点编辑区域"
        isClickable = true
    }

    fun positions() = markers.filter { it.point != it.mapping.point }.associate { it.mapping.id to it.point }
    fun ranges() = markers.filter { it.extent != it.mapping.extent }
        .mapNotNull { marker -> marker.extent?.let { marker.mapping.id to it } }.toMap()

    fun resize(amount: Float) {
        val marker = selected
        val current = marker?.extent
        if (current == null) {
            selectedLabel("选择左摇杆后可调整范围")
            return
        }
        fun size(value: Float) = (value + amount).coerceIn(10f, 400f)
        marker.extent = Extent(size(current.left), size(current.right), size(current.up), size(current.down))
        selectedLabel("左摇杆范围 ${marker.extent!!.up.toInt()} px")
        invalidate()
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                val closest = markers.minByOrNull { hypot(it.point.x * width - event.x, it.point.y * height - event.y) }
                selected = closest?.takeIf {
                    hypot(it.point.x * width - event.x, it.point.y * height - event.y) <= density * 40
                }
                dragging = selected != null
                selectedLabel(selected?.mapping?.hintKey()?.label ?: "拖动按键以调整位置")
            }
            MotionEvent.ACTION_MOVE -> if (dragging) {
                selected?.point = Point((event.x / width).coerceIn(0f, 1f), (event.y / height).coerceIn(0f, 1f))
            }
            MotionEvent.ACTION_UP -> {
                dragging = false
                performClick()
            }
            MotionEvent.ACTION_CANCEL -> dragging = false
        }
        invalidate()
        return true
    }

    override fun performClick(): Boolean = super.performClick()

    override fun onDraw(canvas: Canvas) {
        canvas.drawColor(0x540F1620)
        brush.textAlign = Paint.Align.CENTER
        brush.typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        for (marker in markers) {
            val x = marker.point.x * width
            val y = marker.point.y * height
            val key = marker.mapping.hintKey()
            brush.style = Paint.Style.FILL
            brush.textSize = density * if (marker === selected) 17f else 14f
            brush.color = color(key)
            brush.setShadowLayer(density * 1.5f, 0f, density, Color.BLACK)
            drawLabel(canvas, brush, key.label, x, y, width, height)
            brush.clearShadowLayer()
            marker.extent?.takeIf { marker === selected }?.let { extent ->
                brush.style = Paint.Style.STROKE
                brush.strokeWidth = density * 1.5f
                val scale = height / 1200f
                canvas.drawOval(x - extent.left * scale, y - extent.up * scale,
                    x + extent.right * scale, y + extent.down * scale, brush)
            }
        }
    }
}

private class HintCanvas(context: Context, profile: Profile, private val opacity: Float, color: (HintKey) -> Int) :
    View(context) {
    private data class Label(val point: Point, val key: HintKey, val color: Int) {
        val outlineColor = if (Color.luminance(color) >= .18f) 0xFF10141E.toInt() else 0xFFF7FAFF.toInt()
    }

    private val labels = profile.mappings.map {
        val key = it.hintKey()
        Label(it.point, key, color(key))
    }
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textAlign = Paint.Align.CENTER
        typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
    }
    private val density = resources.displayMetrics.density
    private val outline = Paint(paint).apply {
        style = Paint.Style.STROKE
        strokeJoin = Paint.Join.ROUND
        strokeWidth = 2.5f * density
    }
    private val flashUntil = LongArray(HintKey.entries.size)
    private var previous = emptySet<Button>()

    fun pressed(buttons: Set<Button>) {
        if (previous == buttons) return
        val now = SystemClock.uptimeMillis()
        val added = buttons - previous
        previous = buttons
        for (button in added) flashUntil[HintKey.valueOf(button.name).ordinal] = now + FLASH_MS
        if (added.isNotEmpty()) invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        val now = SystemClock.uptimeMillis()
        var flashing = false
        for (entry in labels) {
            val remaining = (flashUntil[entry.key.ordinal] - now).coerceAtLeast(0L)
            val intensity = remaining.toFloat() / FLASH_MS
            flashing = flashing || remaining > 0
            paint.textSize = (13f + 2.5f * intensity) * density
            paint.color = entry.color
            paint.alpha = ((opacity + (1f - opacity) * intensity) * 255).roundToInt()
            outline.textSize = paint.textSize
            outline.color = entry.outlineColor
            outline.alpha = paint.alpha
            if (remaining > 0) outline.setShadowLayer((1.5f + 2.5f * intensity) * density, 0f, 0f, entry.color)
            else outline.clearShadowLayer()
            drawLabel(canvas, paint, entry.key.label, entry.point.x * width, entry.point.y * height, width, height, outline)
        }
        if (flashing) postInvalidateOnAnimation()
    }

    companion object { private const val FLASH_MS = 210L }
}

private fun drawLabel(
    canvas: Canvas,
    paint: Paint,
    text: String,
    x: Float,
    y: Float,
    width: Int,
    height: Int,
    outline: Paint? = null,
) {
    val inset = (outline?.strokeWidth ?: 0f) / 2
    val halfWidth = (paint.measureText(text) / 2 + inset).coerceAtMost(width / 2f)
    val halfHeight = ((paint.descent() - paint.ascent()) / 2 + inset).coerceAtMost(height / 2f)
    val centerX = x.coerceIn(halfWidth, width - halfWidth)
    val baseline = y.coerceIn(halfHeight, height - halfHeight) - (paint.ascent() + paint.descent()) / 2
    outline?.let { canvas.drawText(text, centerX, baseline, it) }
    canvas.drawText(text, centerX, baseline, paint)
}
