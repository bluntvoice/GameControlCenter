package io.github.bluntvoice.androidgamepad

import org.json.JSONObject
import kotlin.math.hypot
import kotlin.math.pow

data class Point(val x: Float, val y: Float) {
    companion object { val Zero = Point(0f, 0f) }

    fun radial(deadzone: Float, curve: Float = 1f): Point {
        val length = hypot(x, y)
        if (length <= deadzone) return Zero
        val scaled = ((length.coerceAtMost(1f) - deadzone) / (1f - deadzone)).pow(curve)
        return Point(x / length * scaled, y / length * scaled)
    }
}

data class Viewport(val left: Int, val top: Int, val width: Int, val height: Int) {
    init { require(width > 1 && height > 1) }
    val scale: Float get() = height / 1200f

    fun pixel(point: Point) = Point(
        left + (point.x * width).coerceIn(0f, width - 1f),
        top + (point.y * height).coerceIn(0f, height - 1f),
    )

    fun clamp(point: Point) = Point(
        point.x.coerceIn(left.toFloat(), left + width - 1f),
        point.y.coerceIn(top.toFloat(), top + height - 1f),
    )
}

enum class Button { A, B, X, Y, LB, RB, LT, RT, UP, DOWN, LEFT, RIGHT, LS, RS, START, SELECT }
enum class Action { JOYSTICK, CAMERA, TAP, HOLD, REPEAT, AIM }
data class Extent(val left: Float, val right: Float, val up: Float, val down: Float)

data class Mapping(
    val id: String,
    val action: Action,
    val point: Point,
    val button: Button? = null,
    val extent: Extent? = null,
    val speedScale: Float = 1f,
    val repeatHz: Float = 1f,
    val radius: Float = 90f,
)

data class Parameters(
    val leftDeadzone: Float = .10f,
    val rightDeadzone: Float = .12f,
    val rightCurve: Float = 1.5f,
    val cameraSpeed: Float = 800f,
    val tapMs: Long = 50,
)

data class Calibration(
    val leftCenter: Point = Point.Zero,
    val rightCenter: Point = Point.Zero,
    val invertRightX: Boolean = false,
    val invertRightY: Boolean = false,
) {
    init {
        require(listOf(leftCenter.x, leftCenter.y, rightCenter.x, rightCenter.y).all { it in -.25f.. .25f })
    }
}

data class Profile(
    val id: String,
    val revision: Int,
    val name: String,
    val gamePackage: String,
    val parameters: Parameters,
    val mappings: List<Mapping>,
    val unconvertedCount: Int = 0,
) {
    companion object {
        fun parse(text: String): Profile {
            val json = JSONObject(text)
            require(json.getInt("schemaVersion") == 1) { "不支持的方案版本" }
            require(json.getString("orientation") == "landscape") { "方案需要横屏" }
            val coordinates = json.getJSONObject("coordinateSystem")
            require(coordinates.getString("type") == "normalizedGameViewport")
            require(coordinates.getInt("referenceHeight") == 1200)
            val id = json.getString("profileId")
            require(id.matches(Regex("[a-zA-Z0-9_-]{1,80}")))
            val parameters = json.getJSONObject("parameters")
            val tuning = Parameters(
                parameters.bounded("leftDeadzone", 0f, .4f),
                parameters.bounded("rightDeadzone", 0f, .4f),
                parameters.bounded("rightCurve", .5f, 3f),
                parameters.bounded("cameraPxPerSecondAt1200", 50f, 4000f),
                parameters.getLong("tapMs").also { require(it in 24..150) },
            )
            val data = json.getJSONArray("mappings")
            require(data.length() in 1..18)
            val mappings = List(data.length()) { index ->
                val entry = data.getJSONObject(index)
                val point = entry.getJSONObject("point")
                val action = Action.valueOf(entry.getString("action").uppercase())
                val button = if (action in setOf(Action.JOYSTICK, Action.CAMERA)) null
                    else Button.valueOf(entry.getString("button"))
                val range = if (action == Action.JOYSTICK) entry.getJSONObject("rangeAt1200") else null
                Mapping(
                    id = entry.getString("id"),
                    action = action,
                    point = Point(point.bounded("x", 0f, 1f), point.bounded("y", 0f, 1f)),
                    button = button,
                    extent = range?.let {
                        Extent(it.bounded("left", 1f, 500f), it.bounded("right", 1f, 500f),
                            it.bounded("up", 1f, 500f), it.bounded("down", 1f, 500f))
                    },
                    speedScale = if (action == Action.CAMERA) entry.bounded("speedScale", .1f, 4f) else 1f,
                    repeatHz = if (action == Action.REPEAT) entry.bounded("repeatHz", 1f, 20f) else 1f,
                    radius = if (action == Action.AIM) entry.bounded("radiusAt1200", 10f, 400f) else 90f,
                )
            }
            require(mappings.all { it.id.isNotBlank() })
            require(mappings.map(Mapping::id).distinct().size == mappings.size)
            require(mappings.count { it.action == Action.JOYSTICK } <= 1)
            require(mappings.count { it.action == Action.CAMERA } <= 1)
            val buttons = mappings.mapNotNull(Mapping::button)
            require(buttons.distinct().size == buttons.size)
            val revision = json.getInt("revision").also { require(it >= 1) }
            val name = json.getString("name").also { require(it.length in 1..80) }
            val packageName = json.getString("gamePackage")
            require(packageName.matches(Regex("[A-Za-z_]\\w*(\\.[A-Za-z_]\\w*)+")))
            return Profile(id, revision, name, packageName, tuning, mappings,
                json.optJSONArray("unconverted")?.length() ?: 0)
        }

        private fun JSONObject.bounded(name: String, min: Float, max: Float): Float {
            val value = (get(name) as? Number)?.toFloat()
            require(value != null && value.isFinite() && value in min..max) { "参数超出范围 $name" }
            return value
        }
    }
}
