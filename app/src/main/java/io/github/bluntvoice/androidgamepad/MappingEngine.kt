package io.github.bluntvoice.androidgamepad

data class ControllerState(
    val left: Point = Point.Zero,
    val right: Point = Point.Zero,
    val buttons: Set<Button> = emptySet(),
    val lt: Float = 0f,
    val rt: Float = 0f,
)

data class Contact(val id: String, val point: Point, val anchor: Point = point)

class MappingEngine(
    private val profile: Profile,
    private val viewport: Viewport,
    private val calibration: Calibration = Calibration(),
) {
    private data class Pulse(var end: Long = 0, var queued: Int = 0, var gap: Boolean = false)

    private val blocked = mutableSetOf<Button>()
    private var previous = emptySet<Button>()
    private val started = mutableMapOf<Button, Long>()
    private val pulses = mutableMapOf<Button, Pulse>()
    private var cameraPoint: Point? = null
    private var lastMs: Long? = null

    fun resume(held: Set<Button>) {
        blocked.clear()
        blocked.addAll(held)
        previous = emptySet()
        started.clear()
        pulses.clear()
        cameraPoint = null
        lastMs = null
    }

    fun frame(input: ControllerState, now: Long): List<Contact> {
        val dt = lastMs?.let { (now - it).coerceIn(0, 30) / 1000f } ?: 0f
        lastMs = now
        val parameters = profile.parameters
        blocked.retainAll(input.buttons)
        val buttons = input.buttons - blocked
        val down = buttons - previous
        down.forEach { started[it] = now }
        (previous - buttons).forEach(started::remove)
        previous = buttons
        val left = recenter(input.left, calibration.leftCenter).radial(parameters.leftDeadzone)
        val rawRight = recenter(input.right, calibration.rightCenter)
        val right = Point(
            rawRight.x * if (calibration.invertRightX) -1 else 1,
            rawRight.y * if (calibration.invertRightY) -1 else 1,
        ).radial(parameters.rightDeadzone, parameters.rightCurve)
        val aim = profile.mappings.filter { it.action == Action.AIM && it.button in buttons }
            .maxWithOrNull(compareBy({ started.getValue(requireNotNull(it.button)) }, { it.button }))
        val contacts = mutableListOf<Contact>()
        // Keep both continuous controls ahead of new button presses when the platform's pointer limit is reached.
        val ordered = profile.mappings.sortedBy { it.button != null }
        for (mapping in ordered) {
            val anchor = viewport.pixel(mapping.point)
            val button = mapping.button
            val point = when (mapping.action) {
                Action.JOYSTICK -> if (left == Point.Zero) null else {
                    val extent = requireNotNull(mapping.extent)
                    val dx = left.x * if (left.x < 0) extent.left else extent.right
                    val dy = left.y * if (left.y < 0) extent.up else extent.down
                    offset(anchor, dx * viewport.scale, dy * viewport.scale)
                }
                Action.CAMERA -> camera(anchor, right, aim != null, dt, mapping.speedScale)
                Action.TAP -> if (tap(requireNotNull(button), button in down, now, parameters.tapMs)) anchor else null
                Action.HOLD -> if (button in buttons) anchor else null
                Action.REPEAT -> if (button in buttons) {
                    val period = 1000f / mapping.repeatHz
                    val age = now - started.getValue(requireNotNull(button))
                    if (age % period < minOf(parameters.tapMs.toFloat(), period / 2)) anchor else null
                } else null
                Action.AIM -> if (mapping == aim) {
                    offset(anchor, right.x * mapping.radius * viewport.scale, right.y * mapping.radius * viewport.scale)
                } else if (button in buttons) anchor else null
            }
            point?.let { contacts.add(Contact(mapping.id, it, anchor)) }
        }
        return contacts.take(PointerStream.LIMIT)
    }

    private fun tap(button: Button, pressed: Boolean, now: Long, duration: Long): Boolean {
        val pulse = pulses.getOrPut(button) { Pulse() }
        if (pressed) pulse.queued = (pulse.queued + 1).coerceAtMost(8)
        if (pulse.end > now) return true
        if (pulse.end != 0L) {
            pulse.end = 0
            pulse.gap = true
            return false
        }
        if (pulse.gap) pulse.gap = false
        if (pulse.queued == 0) return false
        pulse.queued--
        pulse.end = now + duration
        return true
    }

    private fun camera(anchor: Point, right: Point, aiming: Boolean, dt: Float, scale: Float): Point? {
        if (aiming || right == Point.Zero) {
            cameraPoint = null
            return null
        }
        val previous = cameraPoint
        if (previous == null) {
            cameraPoint = anchor
            return anchor
        }
        val speed = profile.parameters.cameraSpeed * scale * viewport.scale
        val next = Point(previous.x + right.x * speed * dt, previous.y + right.y * speed * dt)
        val xMargin = minOf(.08f * viewport.width, anchor.x - viewport.left,
            viewport.left + viewport.width - 1 - anchor.x)
        val yMargin = minOf(.10f * viewport.height, anchor.y - viewport.top,
            viewport.top + viewport.height - 1 - anchor.y)
        cameraPoint = next.takeIf {
            it.x in (viewport.left + xMargin)..(viewport.left + viewport.width - 1 - xMargin) &&
                it.y in (viewport.top + yMargin)..(viewport.top + viewport.height - 1 - yMargin)
        }
        return cameraPoint
    }

    private fun offset(point: Point, dx: Float, dy: Float) =
        viewport.clamp(Point(point.x + dx, point.y + dy))

    private fun recenter(stick: Point, center: Point): Point {
        fun axis(value: Float, mid: Float) =
            ((value - mid) / (1f - if (value >= mid) mid else -mid)).coerceIn(-1f, 1f)
        return Point(axis(stick.x, center.x), axis(stick.y, center.y))
    }
}
