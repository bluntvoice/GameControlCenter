package io.github.bluntvoice.androidgamepad

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.hardware.input.InputManager
import android.os.Build
import android.provider.Settings
import android.util.Log
import android.view.Display
import android.view.InputDevice
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityManager

class ControllerService : AccessibilityService() {
    private val consumed = mutableSetOf<Pair<Int, Int>>()
    private var capturing = false
    private var capturingScreen = false
    private var inForeground = false

    override fun onServiceConnected() {
        ProbeRuntime.initialize(this)
        ProbeRuntime.service = this
        GameSession.serviceConnected(this)
        capture(false)
        keepInputServiceInForeground()
    }

    internal fun keepInputServiceInForeground() {
        if (GameSession.service !== this || inForeground) return
        try {
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel(
                INPUT_CHANNEL, getString(R.string.input_channel_name), NotificationManager.IMPORTANCE_LOW,
            ))
            val openConsole = PendingIntent.getActivity(this, 0,
                Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
            val notification = Notification.Builder(this, INPUT_CHANNEL)
                .setSmallIcon(R.drawable.ic_gamepad_notification)
                .setContentTitle(getString(R.string.service_name))
                .setContentText(getString(R.string.input_notification_text))
                .setContentIntent(openConsole)
                .setCategory(Notification.CATEGORY_SERVICE)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .build()
            startForeground(INPUT_NOTIFICATION, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
            inForeground = true
            Log.i(TAG, "Input service promoted to foreground")
        } catch (failure: IllegalStateException) {
            Log.w(TAG, "Foreground protection unavailable; will retry when the console resumes", failure)
        } catch (failure: SecurityException) {
            Log.w(TAG, "Foreground protection denied", failure)
        }
    }

    fun capture(enabled: Boolean, screen: Boolean = false) {
        capturing = enabled
        capturingScreen = enabled && screen
        val info = serviceInfo ?: return
        val joystickSource = if (enabled) InputDevice.SOURCE_JOYSTICK else 0
        val screenSource = if (capturingScreen) InputDevice.SOURCE_TOUCHSCREEN else 0
        info.setMotionEventSources(joystickSource or screenSource)
        val flag = AccessibilityServiceInfo.FLAG_REQUEST_FILTER_KEY_EVENTS
        info.flags = if (enabled || consumed.isNotEmpty()) info.flags or flag else info.flags and flag.inv()
        serviceInfo = info
    }

    fun forgetDevice(deviceId: Int) {
        if (consumed.removeAll { it.first == deviceId }) capture(capturing, capturingScreen)
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
        if (!capturing) return
        if (capturingScreen && event.isFromSource(InputDevice.SOURCE_TOUCHSCREEN)) {
            if (event.deviceId <= 0) return
            val device = event.device
            if (device != null && !device.isVirtual && usesMainDisplay(device)) {
                GameSession.screenMotion(event)
            } else {
                GameSession.stop("触摸设备已变化，已恢复系统触控", GameStatus.PAUSED)
            }
            return
        }
        if (!event.isFromSource(InputDevice.SOURCE_JOYSTICK)) return
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

    companion object {
        private const val TAG = "GamepadInputService"
        private const val INPUT_CHANNEL = "gamepad-input"
        private const val INPUT_NOTIFICATION = 401

        internal fun isEnabledInSettings(context: Context): Boolean {
            val component = ComponentName(context, ControllerService::class.java)
            val enabled = Settings.Secure.getString(context.contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES)
            return enabled.orEmpty().split(':').any { ComponentName.unflattenFromString(it) == component }
        }

        // Public since API 37. Keep compiling the rest of the app against API 35.
        private val associatedDisplayId by lazy {
            runCatching { InputDevice::class.java.getMethod("getAssociatedDisplayId") }.getOrNull()
        }

        private fun usesMainDisplay(device: InputDevice): Boolean =
            runCatching { associatedDisplayId?.invoke(device) == Display.DEFAULT_DISPLAY }.getOrDefault(false)
    }

    fun canCaptureMainScreen(): Boolean {
        if (Build.VERSION.SDK_INT < 37 ||
            getSystemService(AccessibilityManager::class.java).isTouchExplorationEnabled) return false
        val input = getSystemService(InputManager::class.java)
        return input.inputDeviceIds.any { id ->
            val device = input.getInputDevice(id) ?: return@any false
            !device.isVirtual && device.supportsSource(InputDevice.SOURCE_TOUCHSCREEN) && usesMainDisplay(device)
        }
    }

    private fun disconnect() {
        if (ProbeRuntime.service === this) {
            if (ProbeRuntime.hasSession) ProbeRuntime.stop("无障碍服务已断开")
            ProbeRuntime.service = null
        }
        GameSession.serviceDisconnected(this)
        if (inForeground) {
            inForeground = false
            stopForeground(STOP_FOREGROUND_REMOVE)
        }
    }
}
