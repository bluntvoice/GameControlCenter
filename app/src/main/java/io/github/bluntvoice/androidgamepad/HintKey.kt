package io.github.bluntvoice.androidgamepad

enum class HintKey(val label: String, val color: Int, val fixed: Boolean = false) {
    A("A", 0xFF83D96B.toInt(), true),
    B("B", 0xFFFF8989.toInt(), true),
    X("X", 0xFF84BEFF.toInt(), true),
    Y("Y", 0xFFFFDA69.toInt(), true),
    LB("LB", 0xFFD9E4EE.toInt()),
    RB("RB", 0xFFD9E4EE.toInt()),
    LT("LT", 0xFFD9E4EE.toInt()),
    RT("RT", 0xFFD9E4EE.toInt()),
    UP("↑", 0xFF9DE0EF.toInt()),
    DOWN("↓", 0xFF9DE0EF.toInt()),
    LEFT("←", 0xFF9DE0EF.toInt()),
    RIGHT("→", 0xFF9DE0EF.toInt()),
    LS("LS", 0xFFD9E4EE.toInt()),
    RS("RS", 0xFFD9E4EE.toInt()),
    START("Start", 0xFFD9E4EE.toInt()),
    SELECT("Select", 0xFFD9E4EE.toInt()),
    LEFT_STICK("左", 0xFFB9F3C1.toInt()),
    RIGHT_STICK("右", 0xFFB9F3C1.toInt()),
}

fun Mapping.hintKey() = button?.let { HintKey.valueOf(it.name) }
    ?: if (action == Action.JOYSTICK) HintKey.LEFT_STICK else HintKey.RIGHT_STICK
