package io.github.bluntvoice.androidgamepad

import android.content.Context
import android.net.Uri
import android.util.AtomicFile
import org.json.JSONObject
import java.io.File
import java.util.UUID

class ProfileRepository(private val context: Context) {
    private val directory = File(context.filesDir, "profiles").apply { mkdirs() }
    private val preferences = context.getSharedPreferences("gamepad-settings", Context.MODE_PRIVATE)
    private val originals = context.assets.list("profiles").orEmpty()
        .filter { it.endsWith(".json") }
        .associate { file ->
            val text = context.assets.open("profiles/$file").bufferedReader(Charsets.UTF_8).use { it.readText() }
            Profile.parse(text).id to text
        }

    var selectedId: String
        get() = preferences.getString("profile", null)?.takeIf { it in ids() } ?: ARENA_ID
        set(value) {
            require(value in ids())
            check(preferences.edit().putString("profile", value).commit()) { "无法保存所选方案" }
        }

    var backendChoice: BackendChoice
        get() = runCatching { BackendChoice.valueOf(preferences.getString("backend", "AUTO")!!) }
            .getOrDefault(BackendChoice.AUTO)
        set(value) {
            check(preferences.edit().putString("backend", value.name).commit()) { "无法保存后端设置" }
        }

    fun ids() = (originals.keys + directory.listFiles().orEmpty()
        .filter { it.isFile && it.extension == "json" }.map { it.nameWithoutExtension }).distinct()

    fun all(): List<Profile> = ids().map(::load).sortedBy { if (it.id == ARENA_ID) 0 else 1 }
    fun load(id: String) = Profile.parse(read(id))
    fun isBuiltin(id: String) = id in originals
    fun editable(id: String) = JSONObject(read(id))

    fun saveEdit(id: String, edited: JSONObject): Profile {
        val current = load(id)
        require(current.id == edited.getString("profileId")) { "方案 ID 已变化" }
        require(current.revision == edited.getInt("revision")) { "方案已有更新，请重新打开" }
        val updated = JSONObject(edited.toString()).put("revision", Math.addExact(current.revision, 1))
        return persist(updated.toString(2))
    }

    fun duplicate(id: String, name: String): Profile {
        val newId = "local-${UUID.randomUUID()}"
        check(newId !in ids())
        return persist(Profile.duplicateDocument(read(id), newId, name))
    }

    var hybridTouch: Boolean
        get() = preferences.getBoolean("hybridTouch", false)
        set(value) { check(preferences.edit().putBoolean("hybridTouch", value).commit()) }

    var showHints: Boolean
        get() = preferences.getBoolean("showHints", true)
        set(value) { check(preferences.edit().putBoolean("showHints", value).commit()) }

    fun hintColor(key: HintKey): Int = if (key.fixed) key.color
        else preferences.getInt("hintColor.${key.name}", key.color)

    fun saveHintColor(key: HintKey, color: Int?) {
        require(!key.fixed)
        val entry = "hintColor.${key.name}"
        val edit = preferences.edit()
        if (color == null) edit.remove(entry) else edit.putInt(entry, color)
        check(edit.commit()) { "无法保存键位颜色" }
    }

    val hintOpacity get() = preferences.getFloat("hintOpacity", .72f)
    val panelOpacity get() = preferences.getFloat("panelOpacity", .88f)
    val panelPlacement get() = Point(
        preferences.getFloat("panelX", 1f).coerceIn(0f, 1f),
        preferences.getFloat("panelY", .04f).coerceIn(0f, 1f),
    )

    fun saveOverlayOpacity(hint: Float, panel: Float) {
        require(hint in .15f..1f && panel in .35f..1f)
        check(preferences.edit().putFloat("hintOpacity", hint).putFloat("panelOpacity", panel).commit())
    }

    fun savePanelPlacement(point: Point) {
        preferences.edit().putFloat("panelX", point.x).putFloat("panelY", point.y).apply()
    }

    fun restore(id: String): Profile = persist(requireNotNull(originals[id]) { "此方案没有内置原始版本" })

    fun import(uri: Uri): Profile {
        val bytes = context.contentResolver.openInputStream(uri)?.use { it.readNBytes(MAX_BYTES + 1) }
            ?: error("无法打开文件")
        require(bytes.size <= MAX_BYTES) { "方案文件超过 512 KB" }
        val text = bytes.toString(Charsets.UTF_8).removePrefix("\uFEFF")
        val profile = Profile.parse(text)
        require(profile.gamePackage == GAME_PACKAGE) { "首期仅支持《蛋仔派对》方案" }
        if (profile.id !in ids()) return persist(text)
        if (JSONObject(read(profile.id)).toString() == JSONObject(text).toString()) return load(profile.id)
        val copyId = "import-${UUID.randomUUID()}"
        return persist(JSONObject(text).put("profileId", copyId)
            .put("name", profile.name.take(72) + "（导入）").toString(2))
    }

    fun calibration(device: android.view.InputDevice?): Calibration {
        val prefix = device?.descriptor?.let { "device.$it" }
        fun center(key: String) = preferences.getFloat("$prefix.$key", 0f)
        return Calibration(Point(center("leftX"), center("leftY")), Point(center("rightX"), center("rightY")),
            preferences.getBoolean("invertRightX", false), preferences.getBoolean("invertRightY", false))
    }

    fun invert(axisX: Boolean, value: Boolean) {
        check(preferences.edit().putBoolean(if (axisX) "invertRightX" else "invertRightY", value).commit()) {
            "无法保存轴向设置"
        }
    }

    fun saveCenter(device: android.view.InputDevice, input: ControllerState) {
        Calibration(input.left, input.right)
        val prefix = "device.${device.descriptor}"
        check(preferences.edit().putFloat("$prefix.leftX", input.left.x).putFloat("$prefix.leftY", input.left.y)
            .putFloat("$prefix.rightX", input.right.x).putFloat("$prefix.rightY", input.right.y).commit()) {
            "无法保存摇杆校准"
        }
    }

    private fun read(id: String): String {
        require(id.matches(Regex("[a-zA-Z0-9_-]{1,80}"))) { "无效方案 ID" }
        val file = AtomicFile(File(directory, "$id.json"))
        return if (file.baseFile.exists() || "${file.baseFile.path}.bak".let { File(it).exists() }) {
            file.readFully().toString(Charsets.UTF_8)
        } else requireNotNull(originals[id]) { "方案不存在" }
    }

    private fun persist(text: String): Profile {
        val profile = Profile.parse(text)
        val raw = text.toByteArray(Charsets.UTF_8)
        require(raw.size <= MAX_BYTES) { "方案文件超过 512 KB" }
        val file = AtomicFile(File(directory, "${profile.id}.json"))
        val output = file.startWrite()
        try {
            output.write(raw)
            file.finishWrite(output)
        } catch (failure: Exception) {
            file.failWrite(output)
            throw failure
        }
        check(file.readFully().contentEquals(raw)) { "方案保存校验失败" }
        return profile
    }

    companion object {
        const val ARENA_ID = "arena-3skills"
        const val GAME_PACKAGE = "com.netease.party"
        private const val MAX_BYTES = 512 * 1024
    }
}
