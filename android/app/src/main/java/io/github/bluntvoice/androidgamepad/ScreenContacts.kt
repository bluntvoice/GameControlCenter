package io.github.bluntvoice.androidgamepad

/** Physical fingers for the current touch gesture on the verified foreground display. */
internal class ScreenContacts {
    private var device = -1
    private var downTime = -1L
    private var fingers = emptyMap<Int, Contact>()

    fun update(device: Int, downTime: Long, action: TouchAction, actionIndex: Int, points: List<Pointer>): Boolean {
        if (action == TouchAction.DOWN) {
            this.device = device
            this.downTime = downTime
            fingers = emptyMap()
        } else if (this.device != device || this.downTime != downTime) {
            return false
        }

        if (action == TouchAction.UP || action == TouchAction.CANCEL) {
            fingers = emptyMap()
            this.device = -1
            this.downTime = -1L
        } else {
            val next = linkedMapOf<Int, Contact>()
            for ((index, pointer) in points.withIndex()) {
                if (action == TouchAction.POINTER_UP && index == actionIndex) continue
                if (!pointer.point.x.isFinite() || !pointer.point.y.isFinite()) continue
                val point = Point(pointer.point.x.coerceAtLeast(0f), pointer.point.y.coerceAtLeast(0f))
                next[pointer.id] = fingers[pointer.id]?.copy(point = point)
                    ?: Contact("front-touch:$device:$downTime:${pointer.id}", point)
            }
            fingers = next
        }
        return true
    }

    fun usesDevice(id: Int) = device == id

    fun combine(controller: List<Contact>): List<Contact> {
        if (fingers.isEmpty()) return controller
        val screen = fingers.values.take(PointerStream.LIMIT)
        return screen + controller.take(PointerStream.LIMIT - screen.size)
    }
}
