package io.github.bluntvoice.androidgamepad

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.ComponentName
import android.content.Context
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.graphics.Path
import android.os.Binder
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import rikka.shizuku.Shizuku
import java.util.concurrent.Executors
import kotlin.math.roundToInt

interface TouchBackend {
    fun frame(contacts: List<Contact>)
    fun stop(done: (String?) -> Unit)
}

class AccessibilityTouchBackend(
    private val service: AccessibilityService,
    private val onFailure: (String) -> Unit,
    private val onAccepted: () -> Unit = {},
) : TouchBackend {
    private data class Stroke(val path: GestureDescription.StrokeDescription, val end: Point)

    private val handler = Handler(Looper.getMainLooper())
    private val queue = ArrayDeque<List<Contact>>()
    private var active = linkedMapOf<String, Stroke>()
    private var busy = false
    private var stopping: ((String?) -> Unit)? = null
    private var closed = false
    private var failure: String? = null

    override fun frame(contacts: List<Contact>) {
        if (closed || stopping != null) return
        val tail = queue.lastOrNull()
        if (tail != null && tail.map(Contact::id) == contacts.map(Contact::id)) queue.removeLast()
        queue.addLast(contacts)
        if (queue.size > 32) {
            onFailure("无障碍触点队列超限")
            return
        }
        dispatchNext()
    }

    override fun stop(done: (String?) -> Unit) {
        if (closed) {
            done(failure)
            return
        }
        queue.clear()
        queue.addLast(emptyList())
        stopping = done
        dispatchNext()
    }

    private fun dispatchNext() {
        if (busy || closed || queue.isEmpty()) return
        val contacts = queue.removeFirst().map { it.copy(point = pixel(it.point), anchor = pixel(it.anchor)) }
        if (contacts.isEmpty() && active.isEmpty()) {
            finishStop(null)
            return
        }
        if (contacts.size == active.size && contacts.all { active[it.id]?.end == it.point }) {
            dispatchNext()
            return
        }
        val desired = contacts.associateBy(Contact::id)
        val builder = GestureDescription.Builder()
        val next = linkedMapOf<String, Stroke>()
        val remaining = PointerStream.LIMIT - active.size
        // New and old strokes both count toward the platform limit for this segment.
        val additions = contacts.filter { it.id !in active }
        if (additions.size > remaining) queue.addFirst(contacts)
        for ((id, stroke) in active) {
            val contact = desired[id]
            val end = contact?.point ?: stroke.end
            val continuation = stroke.path.continueStroke(line(stroke.end, end), 0,
                SEGMENT_MS, contact != null)
            builder.addStroke(continuation)
            if (contact != null) next[id] = Stroke(continuation, end)
        }
        for (contact in additions.take(remaining)) {
            val stroke = GestureDescription.StrokeDescription(line(contact.anchor, contact.point),
                0, SEGMENT_MS, true)
            builder.addStroke(stroke)
            next[contact.id] = Stroke(stroke, contact.point)
        }
        val timeout = Runnable { complete(null, "无障碍手势回执超时") }
        busy = true
        val callback = object : AccessibilityService.GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription) {
                handler.removeCallbacks(timeout)
                complete(next, null)
            }

            override fun onCancelled(gestureDescription: GestureDescription) {
                handler.removeCallbacks(timeout)
                complete(null, "系统取消了无障碍手势")
            }
        }
        val dispatched = runCatching { service.dispatchGesture(builder.build(), callback, handler) }.getOrDefault(false)
        if (dispatched) handler.postDelayed(timeout, 600)
        else complete(null, "系统拒绝无障碍手势")
    }

    private fun complete(next: LinkedHashMap<String, Stroke>?, error: String?) {
        if (closed || !busy) return
        busy = false
        if (error != null) {
            closed = true
            failure = "$error，未确认全部触点释放"
            active.clear()
            queue.clear()
            if (stopping != null) finishStop(failure) else onFailure(requireNotNull(failure))
            return
        }
        active = requireNotNull(next)
        if (active.isNotEmpty()) onAccepted()
        if (active.isEmpty() && stopping != null) finishStop(null) else dispatchNext()
    }

    private fun finishStop(error: String?) {
        val callback = stopping ?: return
        closed = true
        stopping = null
        callback(error)
    }

    private fun pixel(point: Point) = Point(point.x.roundToInt().toFloat(), point.y.roundToInt().toFloat())

    private fun line(from: Point, to: Point) = Path().apply {
        moveTo(from.x, from.y)
        if (from != to) lineTo(to.x, to.y)
    }

    companion object { private const val SEGMENT_MS = 24L }
}

object ShellConnection {
    private val handler = Handler(Looper.getMainLooper())
    private val worker = Executors.newSingleThreadExecutor()
    private val owner = Binder()
    private var attempt = 0
    private var target: ShizukuTouchBackend? = null
    private var args: Shizuku.UserServiceArgs? = null
    var status = "等待 Shizuku"
        private set

    fun available() = runCatching {
        Shizuku.pingBinder() && Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED
    }.getOrDefault(false)

    fun backend(
        context: Context,
        targetUid: Int = context.applicationInfo.uid,
        ready: (TouchBackend) -> Unit,
        fail: (String) -> Unit,
        accepted: () -> Unit = {},
        foregroundPackage: String = "",
    ) {
        if (!available()) {
            fail("Shizuku 未启动或未授权")
            return
        }
        if (target != null) {
            fail("另一个触控会话正在使用 Shizuku")
            return
        }
        val token = ++attempt
        val serviceArgs = Shizuku.UserServiceArgs(ComponentName(context, ShellTouchService::class.java))
            .daemon(false).processNameSuffix("gamepad_touch").version(3)
        args = serviceArgs
        status = "正在连接 Shizuku UserService"
        val candidate = ShizukuTouchBackend(worker, handler, owner, fail, accepted)
        target = candidate
        val connection = object : ServiceConnection {
            override fun onServiceConnected(name: ComponentName, binder: IBinder) {
                if (token != attempt) return
                val service = ITouchService.Stub.asInterface(binder)
                candidate.open(service, targetUid, foregroundPackage) { error ->
                    if (token != attempt) return@open
                    if (error == null) {
                        status = "Shizuku shell 注入会话已建立"
                        ready(candidate)
                    } else {
                        status = error
                        fail(error)
                    }
                }
            }

            override fun onServiceDisconnected(name: ComponentName) {
                if (token == attempt) lost("Shizuku UserService 已断开")
            }
        }
        activeConnection = connection
        runCatching { Shizuku.bindUserService(serviceArgs, connection) }.onFailure {
            fail("无法绑定 Shizuku UserService：${it.message}")
        }
        handler.postDelayed({
            if (token == attempt && !candidate.isReady) fail("Shizuku UserService 准备超时")
        }, 6000)
    }

    private var activeConnection: ServiceConnection? = null

    fun lost(message: String) {
        status = message
        target?.connectionLost(message)
    }

    fun close(done: (String?) -> Unit) {
        ++attempt
        val old = target
        val oldArgs = args
        val oldConnection = activeConnection
        target = null
        args = null
        activeConnection = null
        fun finish(error: String?) {
            if (oldArgs != null && oldConnection != null) {
                runCatching { Shizuku.unbindUserService(oldArgs, oldConnection, true) }
            }
            status = error ?: "Shizuku 会话已关闭"
            done(error)
        }
        if (old == null) finish(null) else old.stop(::finish)
    }
}

private class ShizukuTouchBackend(
    private val worker: java.util.concurrent.Executor,
    private val handler: Handler,
    private val owner: IBinder,
    private val onFailure: (String) -> Unit,
    private val onAccepted: () -> Unit = {},
) : TouchBackend {
    private val queue = ArrayDeque<List<Contact>>()
    private var service: ITouchService? = null
    private var busy = false
    private var closing = false
    private var failed = false
    var isReady = false
        private set

    fun open(remote: ITouchService, targetUid: Int, foregroundPackage: String, done: (String?) -> Unit) {
        service = remote
        worker.execute {
            val error = call { remote.open(owner, targetUid, foregroundPackage) }
            handler.post {
                isReady = error == null && !closing
                done(error)
            }
        }
    }

    override fun frame(contacts: List<Contact>) {
        if (closing || failed) return
        if (queue.lastOrNull()?.map(Contact::id) == contacts.map(Contact::id)) queue.removeLast()
        queue.addLast(contacts)
        if (queue.size > 32) {
            connectionLost("Shizuku 触点队列超限")
            return
        }
        drain()
    }

    fun connectionLost(message: String) {
        if (failed) return
        failed = true
        queue.clear()
        onFailure(message)
    }

    private fun drain() {
        val remote = service ?: return
        if (busy || closing || queue.isEmpty()) return
        busy = true
        val contacts = queue.removeFirst()
        val ids = contacts.map(Contact::id).toTypedArray()
        val coordinates = contacts.flatMap { listOf(it.point.x, it.point.y, it.anchor.x, it.anchor.y) }.toFloatArray()
        worker.execute {
            val error = call { remote.frame(ids, coordinates) }
            handler.post {
                busy = false
                if (error != null && !closing) {
                    connectionLost(error)
                } else {
                    if (!closing && contacts.isNotEmpty()) onAccepted()
                    drain()
                }
            }
        }
    }

    override fun stop(done: (String?) -> Unit) {
        closing = true
        isReady = false
        queue.clear()
        val remote = service
        worker.execute {
            val error = call { remote?.close() }
            handler.post { done(error) }
        }
    }

    private inline fun call(action: () -> String?): String? = try {
        action()
    } catch (exception: Exception) {
        "Shizuku 触控调用失败：${exception.message}"
    }
}
