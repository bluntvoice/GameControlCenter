package io.github.bluntvoice.androidgamepad

import kotlin.math.roundToInt

internal enum class PanelEdge { LEFT, RIGHT }

internal data class PanelPlacement(
    val position: Point,
    val edge: PanelEdge? = null,
    val collapsed: Boolean = false,
) {
    fun offset(xTravel: Int, yTravel: Int): Pair<Int, Int> {
        val x = when (edge) {
            PanelEdge.LEFT -> 0
            PanelEdge.RIGHT -> xTravel
            null -> (position.x * xTravel).roundToInt()
        }
        return x to (position.y * yTravel).roundToInt()
    }

    fun fold() = copy(edge = edge ?: if (position.x <= .5f) PanelEdge.LEFT else PanelEdge.RIGHT,
        collapsed = true)

    companion object {
        fun fromDrag(x: Int, y: Int, xTravel: Int, yTravel: Int, snapDistance: Int): PanelPlacement {
            val left = x.coerceIn(0, xTravel)
            val top = y.coerceIn(0, yTravel)
            val right = xTravel - left
            val edge = if (xTravel > 0 && minOf(left, right) <= snapDistance) {
                if (left <= right) PanelEdge.LEFT else PanelEdge.RIGHT
            } else null
            val position = Point(left.toFloat() / xTravel.coerceAtLeast(1), top.toFloat() / yTravel.coerceAtLeast(1))
            return PanelPlacement(position, edge, collapsed = edge != null)
        }
    }
}

internal class PanelContactGuard {
    private val blocked = mutableSetOf<String>()

    fun filter(contacts: List<Contact>, covered: (Contact) -> Boolean): List<Contact> {
        if (blocked.isNotEmpty()) blocked.retainAll(contacts.map(Contact::id).toSet())
        return contacts.filterNot { contact ->
            contact.id in blocked || covered(contact).also { if (it) blocked.add(contact.id) }
        }
    }

    fun reset() = blocked.clear()
}
