package io.github.bluntvoice.androidgamepad

import android.view.InputDevice
import android.view.KeyEvent
import android.view.MotionEvent

class ControllerInput {
    private val keys = mutableSetOf<Button>()
    private val axes = mutableSetOf<Button>()
    private val blockedAxes = mutableSetOf<Button>()
    private var axisPrimed = false
    var state = ControllerState()
        private set

    fun reset() {
        keys.clear()
        axes.clear()
        blockedAxes.clear()
        axisPrimed = false
        state = ControllerState()
    }

    fun key(event: KeyEvent, sessionStart: Long): Boolean {
        val button = BUTTONS[event.keyCode] ?: return false
        if (event.action == KeyEvent.ACTION_UP) {
            keys.remove(button)
        } else if (event.action == KeyEvent.ACTION_DOWN && event.repeatCount == 0 && event.downTime >= sessionStart) {
            keys.add(button)
        }
        state = state.copy(buttons = keys + (axes - blockedAxes))
        return true
    }

    fun motion(event: MotionEvent, position: Int = -1) {
        val device = event.device ?: return
        fun range(axis: Int) = device.getMotionRange(axis, InputDevice.SOURCE_JOYSTICK)
        fun value(axis: Int) = if (position < 0) event.getAxisValue(axis) else event.getHistoricalAxisValue(axis, position)

        fun stick(axis: Int): Float {
            val range = range(axis) ?: return 0f
            val raw = value(axis)
            val center = if (range.min <= 0f && range.max >= 0f) 0f else (range.min + range.max) / 2
            val extent = if (raw >= center) range.max - center else center - range.min
            return if (extent > 0f) ((raw - center) / extent).coerceIn(-1f, 1f) else 0f
        }

        fun trigger(button: Button, primary: Int, alternate: Int): Float {
            val axis = if (range(primary) != null) primary else alternate
            val range = range(axis) ?: return if (button in keys) 1f else 0f
            val magnitude = ((value(axis) - range.min) / (range.max - range.min)).coerceIn(0f, 1f)
            val pressed = magnitude >= if (button in axes) .45f else .55f
            if (pressed) axes.add(button) else axes.remove(button)
            return magnitude
        }

        val hx = stick(MotionEvent.AXIS_HAT_X)
        val hy = stick(MotionEvent.AXIS_HAT_Y)
        for ((button, pressed) in listOf(Button.LEFT to (hx < -.5f), Button.RIGHT to (hx > .5f),
            Button.UP to (hy < -.5f), Button.DOWN to (hy > .5f))) {
            if (pressed) axes.add(button) else axes.remove(button)
        }
        val lt = trigger(Button.LT, MotionEvent.AXIS_LTRIGGER, MotionEvent.AXIS_BRAKE)
        val rt = trigger(Button.RT, MotionEvent.AXIS_RTRIGGER, MotionEvent.AXIS_GAS)
        if (!axisPrimed) {
            // A held hat or trigger across resume must pass through neutral before firing.
            blockedAxes.addAll(axes)
            axisPrimed = true
        } else {
            blockedAxes.retainAll(axes)
        }
        val right = if (range(MotionEvent.AXIS_Z) != null && range(MotionEvent.AXIS_RZ) != null) {
            Point(stick(MotionEvent.AXIS_Z), stick(MotionEvent.AXIS_RZ))
        } else {
            Point(stick(MotionEvent.AXIS_RX), stick(MotionEvent.AXIS_RY))
        }
        state = ControllerState(Point(stick(MotionEvent.AXIS_X), stick(MotionEvent.AXIS_Y)),
            right, keys + (axes - blockedAxes), lt, rt)
    }

    companion object {
        fun isController(device: InputDevice?) = device != null && !device.isVirtual &&
            device.isExternal && (device.supportsSource(InputDevice.SOURCE_GAMEPAD) ||
                device.supportsSource(InputDevice.SOURCE_JOYSTICK))

        fun currentController() = InputDevice.getDeviceIds().asSequence().mapNotNull(InputDevice::getDevice)
            .firstOrNull(::isController)

        val BUTTONS = mapOf(
            KeyEvent.KEYCODE_BUTTON_A to Button.A, KeyEvent.KEYCODE_BUTTON_B to Button.B,
            KeyEvent.KEYCODE_BUTTON_X to Button.X, KeyEvent.KEYCODE_BUTTON_Y to Button.Y,
            KeyEvent.KEYCODE_BUTTON_L1 to Button.LB, KeyEvent.KEYCODE_BUTTON_R1 to Button.RB,
            KeyEvent.KEYCODE_BUTTON_L2 to Button.LT, KeyEvent.KEYCODE_BUTTON_R2 to Button.RT,
            KeyEvent.KEYCODE_DPAD_UP to Button.UP, KeyEvent.KEYCODE_DPAD_DOWN to Button.DOWN,
            KeyEvent.KEYCODE_DPAD_LEFT to Button.LEFT, KeyEvent.KEYCODE_DPAD_RIGHT to Button.RIGHT,
            KeyEvent.KEYCODE_BUTTON_THUMBL to Button.LS, KeyEvent.KEYCODE_BUTTON_THUMBR to Button.RS,
            KeyEvent.KEYCODE_BUTTON_START to Button.START, KeyEvent.KEYCODE_BUTTON_SELECT to Button.SELECT,
        )
    }
}
