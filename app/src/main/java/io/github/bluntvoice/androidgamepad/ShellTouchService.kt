package io.github.bluntvoice.androidgamepad

import android.content.ComponentName
import android.os.Binder
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.Process
import android.os.SystemClock
import android.view.InputDevice
import android.view.InputEvent
import android.view.MotionEvent
import java.lang.reflect.InvocationTargetException
import kotlin.system.exitProcess

/**
 * Shizuku owns this process. Only the owning app UID can supply test frames,
 * and game sessions require the verified game task on the main display.
 */
class ShellTouchService : ITouchService.Stub() {
    private val stream = PointerStream()
    private val watchdogHandler = Handler(Looper.getMainLooper())
    private var owner: IBinder? = null
    private val death = IBinder.DeathRecipient { synchronized(this) { reset() } }
    private val watchdog = Runnable { synchronized(this) { reset() } }
    private var ownerUid = -1
    private var targetUid = -1
    private var foregroundPackage = ""
    private var downTime = 0L
    private val manager by lazy {
        Class.forName("android.hardware.input.InputManagerGlobal").getMethod("getInstance").invoke(null)
            ?: error("InputManagerGlobal unavailable")
    }
    private val injector by lazy {
        manager.javaClass.getMethod("injectInputEvent", InputEvent::class.java,
            Int::class.javaPrimitiveType, Int::class.javaPrimitiveType)
    }

    private val generalInjector by lazy {
        manager.javaClass.getMethod("injectInputEvent", InputEvent::class.java, Int::class.javaPrimitiveType)
    }
    private val taskManager by lazy {
        Class.forName("android.app.ActivityTaskManager").getMethod("getService").invoke(null)
            ?: error("ActivityTaskManager unavailable")
    }
    private val focusedTask by lazy {
        Class.forName("android.app.IActivityTaskManager").getMethod("getFocusedRootTaskInfo")
    }

    @Synchronized
    override fun open(owner: IBinder, targetUid: Int, foregroundPackage: String): String? = checked {
        check(Process.myUid() == 2000) { "原型仅支持 Shizuku shell 模式" }
        check(this.owner == null || Binder.getCallingUid() == ownerUid) { "触控会话已由其他客户端占用" }
        val uid = Binder.getCallingUid()
        check(uid >= 10_000 && targetUid >= 10_000)
        check((foregroundPackage.isEmpty() && uid == targetUid) ||
            (foregroundPackage == ProfileRepository.GAME_PACKAGE && uid != targetUid)) { "不支持的触控目标" }
        if (foregroundPackage.isEmpty()) {
            injector
        } else {
            generalInjector
            check(isForeground(foregroundPackage)) { "Shizuku 未核实目标游戏在主显示屏前台" }
        }
        check(reset()) { "上一次触控取消失败" }
        owner.linkToDeath(death, 0)
        this.owner = owner
        ownerUid = uid
        this.targetUid = targetUid
        this.foregroundPackage = foregroundPackage
    }

    @Synchronized
    override fun frame(ids: Array<String>, coordinates: FloatArray): String? = checked {
        check(Binder.getCallingUid() == ownerUid && owner != null) { "无有效的触控会话" }
        check(ids.size <= PointerStream.LIMIT && coordinates.size == ids.size * 4)
        check(coordinates.all { it.isFinite() && it in 0f..16384f })
        val contacts = ids.mapIndexed { index, id ->
            val i = index * 4
            Contact(id, Point(coordinates[i], coordinates[i + 1]), Point(coordinates[i + 2], coordinates[i + 3]))
        }
        try {
            if (contacts.isNotEmpty() && foregroundPackage.isNotEmpty()) {
                check(isForeground(foregroundPackage)) { "目标游戏已经离开前台" }
            }
            check(stream.render(contacts, ::inject)) { "系统拒绝触控事件" }
        } catch (failure: Exception) {
            reset()
            throw failure
        }
        watchdogHandler.removeCallbacks(watchdog)
        watchdogHandler.postDelayed(watchdog, 1200)
    }

    @Synchronized
    override fun close(): String? = checked {
        check(targetUid < 0 || Binder.getCallingUid() == ownerUid)
        check(reset()) { "系统未确认触点已取消" }
    }

    @Synchronized
    override fun destroy() {
        if (Binder.getCallingUid() != ownerUid && Binder.getCallingUid() != Process.myUid()) return
        reset()
        exitProcess(0)
    }

    private fun reset(): Boolean {
        watchdogHandler.removeCallbacks(watchdog)
        val cancelled = runCatching { stream.cancel(::inject) }.getOrDefault(false)
        stream.reset()
        owner?.let { runCatching { it.unlinkToDeath(death, 0) } }
        owner = null
        ownerUid = -1
        targetUid = -1
        foregroundPackage = ""
        downTime = 0
        return cancelled
    }

    private fun inject(event: TouchEvent): Boolean {
        val now = SystemClock.uptimeMillis()
        if (event.action == TouchAction.DOWN) downTime = now
        val base = when (event.action) {
            TouchAction.DOWN -> MotionEvent.ACTION_DOWN
            TouchAction.POINTER_DOWN -> MotionEvent.ACTION_POINTER_DOWN
            TouchAction.MOVE -> MotionEvent.ACTION_MOVE
            TouchAction.POINTER_UP -> MotionEvent.ACTION_POINTER_UP
            TouchAction.UP -> MotionEvent.ACTION_UP
            TouchAction.CANCEL -> MotionEvent.ACTION_CANCEL
        }
        val properties = event.pointers.map {
            MotionEvent.PointerProperties().apply { id = it.id; toolType = MotionEvent.TOOL_TYPE_FINGER }
        }.toTypedArray()
        val positions = event.pointers.map {
            MotionEvent.PointerCoords().apply { x = it.point.x; y = it.point.y; pressure = 1f; size = .1f }
        }.toTypedArray()
        val motion = MotionEvent.obtain(downTime, now, base or (event.index shl MotionEvent.ACTION_POINTER_INDEX_SHIFT),
            properties.size, properties, positions, 0, 0, 1f, 1f, 0, 0, InputDevice.SOURCE_TOUCHSCREEN, 0)
        return try {
            asShell {
                // HyperOS gesture monitors receive the same pointer stream as the game.
                // The app verifies the game window and this service verifies its foreground task.
                if (foregroundPackage.isEmpty()) injector.invoke(manager, motion, 1, targetUid) as Boolean
                else generalInjector.invoke(manager, motion, 1) as Boolean
            }
        } finally {
            motion.recycle()
        }
    }

    private fun isForeground(packageName: String): Boolean = asShell {
        val task = focusedTask.invoke(taskManager) ?: return@asShell false
        val component = task.javaClass.getField("topActivity").get(task) as? ComponentName
        task.javaClass.getField("displayId").getInt(task) == 0 && component?.packageName == packageName
    }

    private inline fun <T> asShell(block: () -> T): T {
        val identity = Binder.clearCallingIdentity()
        return try { block() } finally { Binder.restoreCallingIdentity(identity) }
    }

    private inline fun checked(block: () -> Unit): String? = try {
        block()
        null
    } catch (failure: Exception) {
        val cause = (failure as? InvocationTargetException)?.targetException ?: failure
        "${cause.javaClass.simpleName}: ${cause.message}"
    }
}
