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
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import kotlin.math.hypot
import kotlin.math.roundToInt

class GameOverlay(private val context: Context, private val repository: ProfileRepository) {
    private val windows = context.getSystemService(WindowManager::class.java)
    private var panel: View? = null
    private var panelKey = ""
    private var panelViewport: Viewport? = null
    private var profilePicker: View? = null

    private var hints: HintCanvas? = null
    private var hintsKey: Triple<String, Int, Viewport>? = null
    private val panelLocation = IntArray(2)

    fun controls(
        label: String,
        profile: Profile,
        viewport: Viewport,
        toggle: () -> Unit,
        stop: () -> Unit,
        chooseProfile: () -> Unit,
        edit: (() -> Unit)? = null,
        mappingViewport: Viewport = viewport,
    ) {
        showHints(profile, mappingViewport)
        if (panelKey == label && panelViewport == viewport && panel != null) return
        clearPanel()
        clearProfilePicker()
        val placement = repository.panelPlacement

        fun redrawControls() {
            clearPanel()
            controls(label, profile, viewport, toggle, stop, chooseProfile, edit, mappingViewport)
        }

        fun place(next: PanelPlacement) {
            repository.savePanelPlacement(next)
            redrawControls()
        }

        fun toggleHints() {
            runCatching { repository.showHints = !repository.showHints }.onSuccess {
                redrawControls()
            }.onFailure {
                Toast.makeText(context, "无法保存键位显示设置", Toast.LENGTH_SHORT).show()
            }
        }

        val params = positioned(-2, -2, viewport).apply {
            flags = flags or WindowManager.LayoutParams.FLAG_SPLIT_TOUCH
            title = if (placement.collapsed) "安卓手柄控制台边缘拉手" else "安卓手柄控制台"
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
        val view = if (placement.collapsed) {
            FrameLayout(context).apply {
                alpha = repository.panelOpacity
                addView(TextView(context).apply {
                    text = if (placement.edge == PanelEdge.LEFT) "›" else "‹"
                    textSize = 23f
                    gravity = Gravity.CENTER
                    setTextColor(Color.WHITE)
                    background = panelBackground()
                    importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
                }, FrameLayout.LayoutParams(dp(32), dp(52), if (placement.edge == PanelEdge.LEFT) {
                    Gravity.LEFT
                } else Gravity.RIGHT))
                minimumWidth = dp(48)
                minimumHeight = dp(52)
                contentDescription = "展开控制悬浮条"
                isFocusable = true
                setOnClickListener { place(placement.copy(collapsed = false)) }
            }
        } else {
            row().apply {
                alpha = repository.panelOpacity
                background = panelBackground()
                addView(grip)
                addView(button(label, toggle, compact = true))
                addView(button("方案", chooseProfile, compact = true))
                val hintsAction = if (repository.showHints) "隐藏键位" else "显示键位"
                addView(button(hintsAction, ::toggleHints, compact = true))
                if (edit != null) addView(button("编辑", edit, compact = true))
                addView(button("停止", stop, compact = true))
                addView(button("收起", { place(placement.fold()) }, compact = true))
            }
        }
        view.measure(View.MeasureSpec.makeMeasureSpec(viewport.width, View.MeasureSpec.AT_MOST),
            View.MeasureSpec.makeMeasureSpec(viewport.height, View.MeasureSpec.AT_MOST))
        val xTravel = (viewport.width - view.measuredWidth).coerceAtLeast(0)
        val yTravel = (viewport.height - view.measuredHeight).coerceAtLeast(0)
        val (offsetX, offsetY) = placement.offset(xTravel, yTravel)
        params.x += offsetX
        params.y += offsetY
        if (!placement.collapsed) {
            installDrag(grip, view, params, viewport, xTravel, yTravel, ::place)
        }
        show(view, params, label)
        if (panel === view) panelViewport = viewport
    }

    private fun installDrag(
        grip: View,
        view: View,
        params: WindowManager.LayoutParams,
        viewport: Viewport,
        xTravel: Int,
        yTravel: Int,
        place: (PanelPlacement) -> Unit,
    ) {
        var downX = 0f
        var downY = 0f
        var left = 0
        var top = 0
        val slop = ViewConfiguration.get(context).scaledTouchSlop
        var moved = false
        grip.setOnTouchListener { _, event ->
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    clearProfilePicker()
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
                        runCatching { windows.updateViewLayout(view, params) }
                    }
                }
                MotionEvent.ACTION_UP -> if (moved) {
                    place(PanelPlacement.fromDrag(params.x - viewport.left, params.y - viewport.top,
                        xTravel, yTravel, dp(72)))
                }
                MotionEvent.ACTION_CANCEL -> if (moved) {
                    params.x = left
                    params.y = top
                    runCatching { windows.updateViewLayout(view, params) }
                }
            }
            true
        }
    }

    fun chooseProfile(current: Profile, profiles: List<Profile>, viewport: Viewport, select: (String) -> Unit) {
        if (profilePicker != null) {
            clearProfilePicker()
            return
        }
        val width = minOf(viewport.width, dp(360))
        val height = minOf((viewport.height * .85f).roundToInt(), dp(116 + 52 * profiles.size), dp(346))
        val content = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            background = panelBackground()
            setPadding(dp(12), dp(8), dp(12), dp(4))
        }
        val header = row().apply {
            addView(TextView(context).apply {
                text = "选择映射方案"
                textSize = 17f
                setTextColor(Color.WHITE)
            }, LinearLayout.LayoutParams(0, -2, 1f))
            addView(button("关闭", ::clearProfilePicker, compact = true))
        }
        content.addView(header)
        content.addView(TextView(context).apply {
            text = "当前 · ${current.name}"
            textSize = 13f
            setTextColor(0xFFB8C9DE.toInt())
            maxLines = 1
            ellipsize = TextUtils.TruncateAt.END
            setPadding(dp(10), 0, dp(10), dp(6))
        })
        content.addView(ScrollView(context).apply {
            addView(LinearLayout(context).apply {
                orientation = LinearLayout.VERTICAL
                for (profile in profiles) {
                    val selected = profile.id == current.id
                    addView(TextView(context).apply {
                        text = if (selected) "✓  ${profile.name}" else profile.name
                        setTextColor(Color.WHITE)
                        minHeight = dp(48)
                        setPadding(dp(12), dp(5), dp(12), dp(5))
                        textSize = 14f
                        gravity = Gravity.CENTER_VERTICAL
                        maxLines = 2
                        ellipsize = TextUtils.TruncateAt.END
                        isFocusable = true
                        if (selected) {
                            stateDescription = "当前方案"
                            background = GradientDrawable().apply {
                                setColor(0xFF3A526F.toInt())
                                cornerRadius = dp(10).toFloat()
                            }
                        }
                        setOnClickListener {
                            clearProfilePicker()
                            select(profile.id)
                        }
                    }, LinearLayout.LayoutParams(-1, -2))
                }
            })
        }, LinearLayout.LayoutParams(-1, 0, 1f))
        val params = positioned(width, height, viewport).apply {
            x += (viewport.width - width) / 2
            y += (viewport.height - height) / 2
            flags = flags or WindowManager.LayoutParams.FLAG_SPLIT_TOUCH
            title = "安卓手柄控制台方案选择"
        }
        runCatching { windows.addView(content, params) }.onSuccess { profilePicker = content }
            .onFailure { Toast.makeText(context, "无法打开方案列表", Toast.LENGTH_SHORT).show() }
    }

    fun pressed(buttons: Set<Button>) {
        hints?.pressed(buttons)
    }

    fun covers(contact: Contact): Boolean =
        (panelKey != "editor" && covers(panel, contact)) || covers(profilePicker, contact)

    private fun covers(view: View?, contact: Contact): Boolean {
        if (view == null || !view.isLaidOut) return false
        view.getLocationOnScreen(panelLocation)
        val (left, top) = panelLocation
        fun inside(point: Point) = point.x >= left && point.x < left + view.width &&
            point.y >= top && point.y < top + view.height
        return inside(contact.anchor) || inside(contact.point)
    }

    private fun panelBackground() = GradientDrawable().apply {
        setColor(0xFF25303E.toInt())
        cornerRadius = dp(16).toFloat()
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
        clearProfilePicker()
        clearPanel()
        clearHints()
    }

    private fun clearHints() {
        val previous = hints
        hints = null
        hintsKey = null
        if (previous != null) runCatching { windows.removeViewImmediate(previous) }
    }

    private fun clearProfilePicker() {
        val previous = profilePicker
        profilePicker = null
        if (previous != null) runCatching { windows.removeViewImmediate(previous) }
    }

    private fun clearPanel() {
        val previous = panel
        panel = null
        panelKey = ""
        panelViewport = null
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
