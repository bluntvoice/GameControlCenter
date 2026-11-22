package io.github.bluntvoice.androidgamepad

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.gestures.detectVerticalDragGestures
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.zIndex

private data class ProfileDrag(
    val index: Int,
    val centers: List<Float>,
    val rowAdvance: Float,
    val initialScroll: Int,
    val initialPointerY: Float,
) {
    fun target(translation: Float): Int {
        val center = centers[index] + translation
        return when {
            translation > 0 -> centers.indexOfLast { it <= center }
            translation < 0 -> centers.indexOfFirst { it >= center }
            else -> index
        }
    }
}

@Composable
internal fun ProfileOrderList(
    profiles: List<Profile>,
    selectedId: String,
    scroll: ScrollState,
    viewport: Rect,
    select: (Profile) -> Unit,
    saveOrder: (List<String>) -> Boolean,
) {
    val ids = profiles.map(Profile::id)
    val heights = remember { mutableStateMapOf<String, Int>() }
    val currentSave by rememberUpdatedState(saveOrder)
    val currentViewport by rememberUpdatedState(viewport)
    var drag by remember(ids) { mutableStateOf<ProfileDrag?>(null) }
    var displacement by remember(ids) { mutableFloatStateOf(0f) }
    val density = LocalDensity.current
    val spacing = with(density) { 14.dp.roundToPx() }
    val edge = with(density) { 52.dp.toPx() }
    val scrollStep = with(density) { 12.dp.toPx() }
    val elevation = with(density) { 8.dp.toPx() }

    fun move(from: Int, to: Int): Boolean {
        if (from == to) return false
        val order = ids.toMutableList()
        order.add(to, order.removeAt(from))
        return currentSave(order)
    }

    LaunchedEffect(drag) {
        val active = drag ?: return@LaunchedEffect
        while (true) {
            withFrameNanos { }
            val bounds = currentViewport
            val pointer = active.initialPointerY + displacement
            val amount = when {
                pointer < bounds.top + edge -> (pointer - bounds.top - edge) / edge
                pointer > bounds.bottom - edge -> (pointer - bounds.bottom + edge) / edge
                else -> 0f
            }
            if (amount != 0f) scroll.scrollBy(amount.coerceIn(-1f, 1f) * scrollStep)
        }
    }

    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        profiles.forEachIndexed { index, item ->
            key(item.id) {
                val active = drag
                val translation = if (active == null) 0f else displacement + scroll.value - active.initialScroll
                val target = active?.target(translation)
                val moving = active?.index == index
                val shift = when {
                    active == null || target == null -> 0f
                    moving -> translation
                    index > active.index && index <= target -> -active.rowAdvance
                    index < active.index && index >= target -> active.rowAdvance
                    else -> 0f
                }
                Card(
                    onClick = { if (drag == null) select(item) },
                    modifier = Modifier.onSizeChanged { heights[item.id] = it.height }
                        .zIndex(if (moving) 1f else 0f)
                        .graphicsLayer {
                            translationY = shift
                            shadowElevation = if (moving) elevation else 0f
                            shape = RoundedCornerShape(12.dp)
                        },
                    colors = CardDefaults.cardColors(containerColor = if (item.id == selectedId)
                        MaterialTheme.colorScheme.secondaryContainer else MaterialTheme.colorScheme.surfaceContainerLow),
                ) {
                    Row(Modifier.fillMaxWidth().padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                        RadioButton(selected = item.id == selectedId, onClick = null)
                        Column(Modifier.weight(1f).padding(start = 10.dp),
                            verticalArrangement = Arrangement.spacedBy(3.dp)) {
                            Text(item.name, style = MaterialTheme.typography.titleMedium)
                            Text("${item.mappings.size} 个按键与摇杆 · 修订 ${item.revision}" +
                                if (item.unconvertedCount > 0) " · ${item.unconvertedCount} 个节点待映射" else "",
                                style = MaterialTheme.typography.bodySmall)
                        }
                        if (ids.size > 1) {
                            var handleTop by remember { mutableFloatStateOf(0f) }
                            val tint = MaterialTheme.colorScheme.onSurfaceVariant
                            Box(Modifier.size(48.dp)
                                .onGloballyPositioned { handleTop = it.positionInRoot().y }
                                .semantics {
                                    contentDescription = "拖动排序 ${item.name}"
                                    customActions = buildList {
                                        if (index > 0) add(CustomAccessibilityAction("上移") { move(index, index - 1) })
                                        if (index < ids.lastIndex) add(CustomAccessibilityAction("下移") { move(index, index + 1) })
                                    }
                                }
                                .pointerInput(ids, spacing) {
                                    detectVerticalDragGestures(
                                        onDragStart = { position ->
                                            if (drag != null || ids.any { it !in heights }) return@detectVerticalDragGestures
                                            val rowHeights = ids.map { heights.getValue(it) }
                                            var top = 0f
                                            val centers = rowHeights.map { height ->
                                                val center = top + height / 2f
                                                top += height + spacing
                                                center
                                            }
                                            displacement = 0f
                                            drag = ProfileDrag(index, centers, (rowHeights[index] + spacing).toFloat(),
                                                scroll.value, handleTop + position.y)
                                        },
                                        onDragEnd = {
                                            val finished = drag?.takeIf { it.index == index }
                                            if (finished != null) {
                                                val destination = finished.target(displacement + scroll.value - finished.initialScroll)
                                                drag = null
                                                move(index, destination)
                                            }
                                        },
                                        onDragCancel = { if (drag?.index == index) drag = null },
                                        onVerticalDrag = { _, amount -> if (drag?.index == index) displacement += amount },
                                    )
                                }, contentAlignment = Alignment.Center) {
                                Canvas(Modifier.size(20.dp)) {
                                    for (column in 1..2) {
                                        for (row in 1..3) {
                                            drawCircle(tint, 1.4.dp.toPx(),
                                                Offset(size.width * column / 3f, size.height * row / 4f))
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
