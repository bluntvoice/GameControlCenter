package io.github.bluntvoice.androidgamepad

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.TextView
import rikka.shizuku.Shizuku

class MainActivity : Activity() {
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var status: TextView
    private val refresh = object : Runnable {
        override fun run() {
            renderStatus()
            handler.postDelayed(this, 400)
        }
    }
    private val permissionListener = Shizuku.OnRequestPermissionResultListener { _, _ -> renderStatus() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        ProbeRuntime.initialize(this)
        Shizuku.addRequestPermissionResultListener(permissionListener)
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val padding = (20 * resources.displayMetrics.density).toInt()
            setPadding(padding, padding, padding, padding)
        }
        val page = ScrollView(this).apply { addView(content) }
        val title = TextView(this).apply { text = "安卓手柄控制台"; textSize = 26f }
        content.addView(title)
        content.addView(TextView(this).apply {
            text = "核心触控原型 · 仅在测试画布注入触点"
            textSize = 16f
        })
        status = TextView(this).apply { textSize = 16f; setPadding(0, 16, 0, 16) }
        content.addView(status)
        content.addView(Button(this).apply {
            text = "授权 Shizuku"
            setOnClickListener {
                if (!Shizuku.pingBinder()) {
                    android.widget.Toast.makeText(this@MainActivity, "请先在 Shizuku 中启动服务",
                        android.widget.Toast.LENGTH_SHORT).show()
                } else if (!ShellConnection.available()) {
                    runCatching { Shizuku.requestPermission(1) }.onFailure {
                        android.widget.Toast.makeText(this@MainActivity, it.message,
                            android.widget.Toast.LENGTH_LONG).show()
                    }
                }
            }
        })
        content.addView(Button(this).apply {
            text = "开启无障碍服务"
            setOnClickListener { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) }
        })
        val options = Spinner(this).apply {
            adapter = ArrayAdapter(this@MainActivity, android.R.layout.simple_spinner_dropdown_item,
                listOf("自动 · 优先可用的 Shizuku", "无障碍", "Shizuku"))
        }
        content.addView(options)
        content.addView(Button(this).apply {
            text = "打开横屏测试画布"
            setOnClickListener {
                val intent = Intent(this@MainActivity, ProbeActivity::class.java)
                    .putExtra("backend", BackendChoice.entries[options.selectedItemPosition].name)
                startActivity(intent)
            }
        })
        packageManager.getLaunchIntentForPackage("cn.axi.gamepad.an")?.let { launch ->
            content.addView(Button(this).apply {
                text = "打开手柄·阿西西"
                setOnClickListener { startActivity(launch) }
            })
        }
        setContentView(page)
    }

    override fun onResume() {
        super.onResume()
        handler.post(refresh)
    }

    override fun onPause() {
        handler.removeCallbacks(refresh)
        super.onPause()
    }

    override fun onDestroy() {
        Shizuku.removeRequestPermissionResultListener(permissionListener)
        super.onDestroy()
    }

    private fun renderStatus() {
        val controller = ControllerInput.currentController()
        val device = controller?.let { "${it.name} · ID ${it.id}" } ?: "未连接"
        val shizuku = when {
            !Shizuku.pingBinder() -> "未启动"
            ShellConnection.available() -> "已授权"
            else -> "等待授权"
        }
        status.text = "手柄 · $device\nShizuku · $shizuku\n无障碍服务 · " +
            if (ProbeRuntime.service != null) "已连接" else "未启用"
    }
}
