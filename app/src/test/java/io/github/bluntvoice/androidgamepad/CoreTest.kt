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
