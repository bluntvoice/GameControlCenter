package io.github.bluntvoice.androidgamepad

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.content.Intent
import android.view.InputDevice
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.accessibility.AccessibilityEvent

class ControllerService : AccessibilityService() {
    private val consumed = mutableSetOf<Pair<Int, Int>>()
    private var capturing = false

    override fun onServiceConnected() {
        ProbeRuntime.initialize(this)
        ProbeRuntime.service = this
        GameSession.serviceConnected(this)
        capture(false)
    }

    fun capture(enabled: Boolean) {
        capturing = enabled
        val info = serviceInfo ?: return
        info.setMotionEventSources(if (enabled) InputDevice.SOURCE_JOYSTICK else 0)
        val flag = AccessibilityServiceInfo.FLAG_REQUEST_FILTER_KEY_EVENTS
        info.flags = if (enabled || consumed.isNotEmpty()) info.flags or flag else info.flags and flag.inv()
        serviceInfo = info
    }

    fun forgetDevice(deviceId: Int) {
        if (consumed.removeAll { it.first == deviceId }) capture(capturing)
    }

    override fun onKeyEvent(event: KeyEvent): Boolean {
        val id = event.deviceId to event.keyCode
        val wasConsumed = id in consumed
        val game = capturing && GameSession.accepts(event.deviceId)
        val probe = capturing && ProbeRuntime.accepts(event.deviceId)
        if (game) GameSession.key(event)
        else if (probe) ProbeRuntime.key(event, "AccessibilityService")
        if (event.action == KeyEvent.ACTION_UP && wasConsumed) {
            consumed.remove(id)
            if (!capturing) capture(false)
            return true
        }
        if (event.action == KeyEvent.ACTION_DOWN && (game || probe) &&
            event.keyCode in ControllerInput.BUTTONS && (event.repeatCount == 0 || wasConsumed) &&
            (if (game) GameSession.isSessionPress(event) else ProbeRuntime.isSessionPress(event))) {
            consumed.add(id)
            return true
        }
        return wasConsumed
    }

    override fun onMotionEvent(event: MotionEvent) {
        if (!capturing || !event.isFromSource(InputDevice.SOURCE_JOYSTICK)) return
        if (GameSession.accepts(event.deviceId)) GameSession.motion(event)
        else if (ProbeRuntime.accepts(event.deviceId)) ProbeRuntime.motion(event, "AccessibilityService")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent) = GameSession.windowChanged()

    override fun onInterrupt() {
        if (ProbeRuntime.hasSession) ProbeRuntime.stop("无障碍服务中断")
        if (GameSession.state.value.status != GameStatus.STOPPED) {
            GameSession.stop("无障碍服务中断", GameStatus.ERROR)
        }
    }

    override fun onUnbind(intent: Intent?): Boolean {
        disconnect()
        return super.onUnbind(intent)
    }

    override fun onDestroy() {
        disconnect()
        super.onDestroy()
    }

    private fun disconnect() {
        if (ProbeRuntime.service === this) {
            if (ProbeRuntime.hasSession) ProbeRuntime.stop("无障碍服务已断开")
            ProbeRuntime.service = null
        }
        GameSession.serviceDisconnected(this)
    }
}
