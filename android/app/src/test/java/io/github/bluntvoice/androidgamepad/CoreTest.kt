package io.github.bluntvoice.androidgamepad

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CoreTest {
    private val area = Viewport(40, 30, 1304, 600)
    private val stick = Mapping("left", Action.JOYSTICK, Point(.2f, .7f),
        extent = Extent(90f, 90f, 90f, 90f))
    private val camera = Mapping("right", Action.CAMERA, Point(.55f, .55f))
    private val tap = Mapping("RB", Action.TAP, Point(.8f, .4f), Button.RB)
    private val hold = Mapping("LB", Action.HOLD, Point(.8f, .6f), Button.LB)
    private val aim = Mapping("Y", Action.AIM, Point(.8f, .5f), Button.Y)
    private val repeat = Mapping("X", Action.REPEAT, Point(.6f, .5f), Button.X, repeatHz = 3f)

    @Test fun profileAssetsMatchTheirVerifiedBindingCounts() {
        fun read(id: String) = Profile.parse(File("src/main/assets/profiles/$id.json").readText(Charsets.UTF_8))
        val arena = read("arena-3skills")
        val vanguard = read("a597648e0bd94b15822daddff501a9fb")
        assertEquals(39, arena.revision)
        assertEquals(14, arena.mappings.size)
        assertEquals(3f, arena.mappings.single { it.button == Button.LT }.repeatHz)
        assertEquals(23, vanguard.revision)
        assertEquals(15, vanguard.mappings.size)
        assertEquals(1, vanguard.unconvertedCount)
        assertFalse((arena.mappings + vanguard.mappings).any { it.action == Action.AIM })
    }

    @Test fun duplicatedProfileUsesIndependentIdAndPreservesUnmappedNodes() {
        val source = File("src/main/assets/profiles/a597648e0bd94b15822daddff501a9fb.json")
            .readText(Charsets.UTF_8)
        val original = Profile.parse(source)
        val json = Profile.duplicateDocument(source, "local-vanguard", "激战先锋（手机）")
        val duplicate = Profile.parse(json)
        val raw = org.json.JSONObject(json)
        assertEquals("local-vanguard", duplicate.id)
        assertEquals(1, duplicate.revision)
        assertEquals("激战先锋（手机）", duplicate.name)
        assertEquals(original.mappings, duplicate.mappings)
        assertEquals(original.id, raw.getJSONObject("copiedFrom").getString("profileId"))
        assertEquals(23, raw.getJSONObject("copiedFrom").getInt("revision"))
        assertEquals("RightButton", raw.getJSONArray("unconverted").getJSONObject(0)
            .getJSONObject("node").getString("key"))
        raw.getJSONArray("mappings").getJSONObject(0).getJSONObject("point").put("x", 0.2)
        assertEquals(original, Profile.parse(source))
        assertFalse(original.mappings == Profile.parse(raw.toString()).mappings)
        assertTrue(runCatching { Profile.duplicateDocument(source, original.id, "副本") }.isFailure)
    }

    @Test fun profileRejectsUnknownActionsAndUnsafeRepeatRates() {
        val original = File("src/main/assets/profiles/arena-3skills.json").readText(Charsets.UTF_8)
        for (invalid in listOf(original.replace("\"repeat\"", "\"script\""),
            original.replace(Regex("\"repeatHz\"\\s*:\\s*3(\\.0)?"), "\"repeatHz\":1000"),
            original.replace("\"schemaVersion\": 1", "\"schemaVersion\": 2"))) {
            assertTrue(runCatching { Profile.parse(invalid) }.isFailure)
        }
    }

    @Test fun deadzoneViewportAndDeviceCenterAreIndependent() {
        assertEquals(Point.Zero, Point(.03f, -.04f).radial(.1f))
        assertEquals(Point(1f, 0f), Point(1f, 0f).radial(.1f))
        assertEquals(Point(1343f, 629f), area.pixel(Point(1f, 1f)))
        val engine = engine(Calibration(leftCenter = Point(.15f, -.16f)))
        assertTrue(engine.frame(ControllerState(left = Point(.15f, -.16f)), 0).isEmpty())
        val contact = engine.frame(ControllerState(left = Point(.15f, -1f)), 16).single()
        assertEquals(contact.anchor.y - 45f, contact.point.y, .01f)
    }

    @Test fun panelSnapsEitherEdgeAndClampsItsDragPosition() {
        val left = PanelPlacement.fromDrag(210, 330, 1600, 1000, 216)
        val right = PanelPlacement.fromDrag(1590, 1010, 1600, 1000, 216)
        val free = PanelPlacement.fromDrag(800, -20, 1600, 1000, 216)
        assertEquals(PanelEdge.LEFT, left.edge)
        assertEquals(PanelEdge.RIGHT, right.edge)
        assertTrue(left.collapsed)
        assertTrue(right.collapsed)
        assertEquals(0 to 330, left.offset(1500, 1000))
        assertEquals(1500 to 1000, right.offset(1500, 1000))
        assertEquals(null, free.edge)
        assertFalse(free.collapsed)
        assertEquals(750 to 0, free.offset(1500, 1000))
    }

    @Test fun reopeningAndRefoldingPanelKeepsTheEdgeAndVerticalRatio() {
        val legacy = PanelPlacement(Point(.82f, .4f))
        assertEquals(820 to 200, legacy.offset(1000, 500))
        val collapsed = legacy.fold()
        val expanded = collapsed.copy(collapsed = false)
        assertEquals(1200 to 180, collapsed.offset(1200, 450))
        assertEquals(900 to 200, expanded.offset(900, 500))
        assertEquals(collapsed, expanded.fold())
    }

    @Test fun panelDoesNotRestartACoveredHeldButtonOrInterruptOtherContacts() {
        val guard = PanelContactGuard()
        val skill = Contact("skill", Point(130f, 300f))
        val stick = Contact("stick", Point(190f, 460f))
        val contacts = listOf(skill, stick)
        assertEquals(contacts, guard.filter(contacts) { false })
        assertEquals(listOf(stick), guard.filter(contacts) { it == skill })
        assertEquals(listOf(stick), guard.filter(contacts) { false })
        assertEquals(listOf(stick), guard.filter(listOf(stick)) { false })
        assertEquals(contacts, guard.filter(contacts) { false })
    }

    @Test fun arenaMappingKeepsScreenPositionsWhenTheCutoutChangesSides() {
        val leftCutout = Viewport(144, 0, 2464, 1200)
        val rightCutout = Viewport(0, 0, 2464, 1200)
        val reference = leftCutout.withLeftCutoutReference(leftInset = 144, rightInset = 0, windowRight = 2608)
        val rotated = rightCutout.withLeftCutoutReference(leftInset = 0, rightInset = 144, windowRight = 2608)
        assertEquals(leftCutout, reference)
        val jump = Point(.9542f, .6542f)
        assertEquals(reference.pixel(jump), rotated.pixel(jump))
        assertEquals(2495.15f, rotated.pixel(jump).x, .01f)
        assertEquals(rightCutout, rightCutout.withLeftCutoutReference(0, 144, windowRight = 2464))
    }

    @Test fun leftStickGainScalesTheResponseWithoutExceedingItsRange() {
        val profile = Profile("gain", 1, "Gain", "test.game",
            Parameters(leftDeadzone = 0f, leftSensitivity = 2f), listOf(stick))
        val engine = MappingEngine(profile, area)
        val state = ControllerState(left = Point(.3f, 0f))
        val light = engine.frame(state, 0).single()
        assertEquals(27f, light.point.x - light.anchor.x, .01f)
        val full = engine.frame(ControllerState(left = Point(.9f, 0f)), 16).single()
        assertEquals(45f, full.point.x - full.anchor.x, .01f)
    }

    @Test fun physicalTouchAndGamepadShareOneStreamInEitherOrder() {
        val stick = Contact("left", Point(180f, 500f))
        val finger = Pointer(7, Point(850f, 260f))
        for (fingerFirst in listOf(false, true)) {
            val stream = PointerStream()
            val screen = ScreenContacts()
            val events = mutableListOf<TouchEvent>()
            val controller = listOf(stick)
            fun render(inputs: List<Contact>) = assertTrue(stream.render(screen.combine(inputs), events::add))
            assertFalse(screen.update(9, 1L, TouchAction.MOVE, 0, listOf(finger)))
            if (!fingerFirst) render(controller)
            assertTrue(screen.update(9, 2L, TouchAction.DOWN, 0, listOf(finger)))
            if (fingerFirst) render(emptyList())
            render(controller)
            assertEquals(2, events.last().pointers.size)
            val stickId = events.last().pointers.single { it.point == stick.point }.id
            val moved = finger.copy(point = Point(925f, 270f))
            assertTrue(screen.update(9, 2L, TouchAction.MOVE, 0, listOf(moved)))
            render(controller)
            assertEquals(TouchAction.MOVE, events.last().action)
            assertTrue(events.last().pointers.any { it.id == stickId && it.point == stick.point })
            assertTrue(screen.update(9, 2L, TouchAction.UP, 0, listOf(moved)))
            render(controller)
            val release = events.last()
            assertEquals(TouchAction.POINTER_UP, release.action)
            assertFalse(release.pointers[release.index].id == stickId)
            render(emptyList())
            assertEquals(TouchAction.UP, events.last().action)
            assertEquals(stickId, events.last().pointers.single().id)
            assertEquals(listOf(TouchAction.DOWN, TouchAction.POINTER_DOWN, TouchAction.MOVE,
                TouchAction.POINTER_UP, TouchAction.UP), events.map(TouchEvent::action))
        }
    }

    @Test fun shouldersDoNotRestartEitherStickStream() {
        val engine = engine()
        val stream = PointerStream()
        val events = mutableListOf<TouchEvent>()
        val drive = ControllerState(Point(0f, -1f), Point(.8f, 0f))
        fun frame(state: ControllerState, whenMs: Long) {
            assertTrue(stream.render(engine.frame(state, whenMs)) { events.add(it) })
        }
        frame(drive, 0)
        frame(drive, 16)
        frame(drive.copy(buttons = setOf(Button.RB)), 20)
        frame(drive, 24)
        frame(drive, 71)
        val edges = events.filter { it.action != TouchAction.MOVE }
        assertEquals(listOf(TouchAction.DOWN, TouchAction.POINTER_DOWN, TouchAction.POINTER_DOWN,
            TouchAction.POINTER_UP), edges.map(TouchEvent::action))
        assertEquals(listOf(0, 1, 2), edges[2].pointers.map(Pointer::id))
        assertEquals(listOf(0, 1, 2), edges[3].pointers.map(Pointer::id))
        assertEquals(2, edges[3].index)
        assertTrue(events.any { it.action == TouchAction.MOVE && it.pointers.size == 3 })
        frame(ControllerState(), 88)
        assertEquals(TouchAction.UP, events.last().action)
    }

    @Test fun rapidTapEdgesQueueWithoutRequiringButtonHold() {
        val engine = engine()
        fun frame(at: Long, pressed: Boolean) = engine.frame(
            ControllerState(buttons = if (pressed) setOf(Button.RB) else emptySet()), at,
        ).isNotEmpty()
        assertTrue(frame(0, true))
        assertTrue(frame(10, false))
        assertTrue(frame(20, true))
        assertTrue(frame(30, false))
        assertFalse(frame(50, false))
        assertTrue(frame(66, false))
        assertFalse(frame(116, false))
    }

    @Test fun resumingRestartsStickAndRequiresNewSkillEdge() {
        val engine = engine()
        val held = ControllerState(Point(1f, 0f), buttons = setOf(Button.LB))
        engine.resume(held.buttons)
        assertEquals(listOf("left"), engine.frame(held, 0).map(Contact::id))
        engine.frame(held.copy(buttons = emptySet()), 16)
        assertEquals(listOf("left", "LB"), engine.frame(held, 32).map(Contact::id))
    }

    @Test fun aimRoutesRightStickToSkillAndReleasesIt() {
        val engine = engine(Calibration(invertRightX = true))
        val state = ControllerState(Point(0f, -1f), Point(1f, 0f), setOf(Button.Y))
        val contacts = engine.frame(state, 1)
        assertEquals(listOf("left", "Y"), contacts.map(Contact::id))
        val skill = contacts.last()
        assertEquals(skill.anchor.x - 45f, skill.point.x, .01f)
        assertEquals(listOf("left", "right"), engine.frame(state.copy(buttons = emptySet()), 16).map(Contact::id))
    }

    @Test fun repeatUsesConfiguredPeriodAndStopsOnRelease() {
        val engine = engine()
        val state = ControllerState(buttons = setOf(Button.X))
        assertEquals("X", engine.frame(state, 2).single().id)
        assertTrue(engine.frame(state, 100).isEmpty())
        assertEquals("X", engine.frame(state, 340).single().id)
        assertTrue(engine.frame(ControllerState(), 350).isEmpty())
    }

    @Test fun failedPointerDownCanCancelThePreviouslyAcceptedPointers() {
        val stream = PointerStream()
        val left = Contact("left", Point(10f, 20f))
        val right = Contact("right", Point(20f, 20f))
        assertTrue(stream.render(listOf(left)) { true })
        assertFalse(stream.render(listOf(left, right)) { it.action != TouchAction.POINTER_DOWN })
        var cancelled: TouchEvent? = null
        assertTrue(stream.cancel { cancelled = it; true })
        assertNotNull(cancelled)
        assertEquals(TouchAction.CANCEL, cancelled?.action)
        assertEquals(listOf(0), cancelled?.pointers?.map(Pointer::id))
        assertTrue(stream.cancel { error("No active pointers expected") })
    }

    private fun engine(calibration: Calibration = Calibration()) = MappingEngine(
        Profile("test", 1, "Test", "test.game", Parameters(), listOf(stick, camera, tap, hold, aim, repeat)),
        area, calibration,
    )
}
