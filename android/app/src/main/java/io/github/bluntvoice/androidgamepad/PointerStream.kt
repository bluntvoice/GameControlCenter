package io.github.bluntvoice.androidgamepad

enum class TouchAction { DOWN, POINTER_DOWN, MOVE, POINTER_UP, UP, CANCEL }
data class Pointer(val id: Int, val point: Point)
data class TouchEvent(val action: TouchAction, val index: Int, val pointers: List<Pointer>)

class PointerStream {
    companion object { const val LIMIT = 10 }
    private val active = linkedMapOf<String, Pointer>()

    /**
     * Commit each event only after the consuming backend accepts it. If an
     * event fails, the original stream is retained for the cancellation path.
     */
    fun render(contacts: List<Contact>, emit: (TouchEvent) -> Boolean): Boolean {
        require(contacts.size <= LIMIT)
        val wanted = contacts.associateBy(Contact::id)
        require(wanted.size == contacts.size)
        for (id in active.keys.toList().asReversed()) {
            if (id in wanted) continue
            val event = TouchEvent(
                if (active.size == 1) TouchAction.UP else TouchAction.POINTER_UP,
                active.keys.indexOf(id), active.values.toList(),
            )
            if (!emit(event)) return false
            active.remove(id)
        }

        var changed = false
        val moved = LinkedHashMap(active)
        for (contact in contacts) {
            val existing = active[contact.id]
            if (existing == null) {
                val taken = active.values.map(Pointer::id)
                val pointer = Pointer((0 until LIMIT).first { it !in taken }, contact.anchor)
                val event = TouchEvent(
                    if (active.isEmpty()) TouchAction.DOWN else TouchAction.POINTER_DOWN,
                    active.size, active.values.toList() + pointer,
                )
                if (!emit(event)) return false
                active[contact.id] = pointer
                moved[contact.id] = pointer
            } else if (existing.point != contact.point) {
                moved[contact.id] = existing.copy(point = contact.point)
                changed = true
            }
        }
        if (changed) {
            if (!emit(TouchEvent(TouchAction.MOVE, 0, moved.values.toList()))) return false
            active.putAll(moved)
        }
        return true
    }

    fun cancel(emit: (TouchEvent) -> Boolean): Boolean {
        if (active.isEmpty()) return true
        val result = emit(TouchEvent(TouchAction.CANCEL, 0, active.values.toList()))
        active.clear()
        return result
    }

    fun reset() = active.clear()
}
