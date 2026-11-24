package dev.bento.spike

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import org.json.JSONObject
import java.util.concurrent.Executors

/** One screen: a button per spike action and a log view. `am start --es action <name> --es args '<json>'` automates it. */
class MainActivity : Activity() {
    private val executor = Executors.newSingleThreadExecutor()
    private lateinit var log: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val column = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        Actions.names.forEach { name ->
            column.addView(Button(this).apply { text = name; setOnClickListener { launch(name, JSONObject()) } })
        }
        log = TextView(this).apply { setTextIsSelectable(true); textSize = 11f }
        column.addView(log)
        setContentView(ScrollView(this).apply { addView(column) })
        handle(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handle(intent)
    }

    private fun handle(intent: Intent?) {
        val action = intent?.getStringExtra("action") ?: return
        val args = intent.getStringExtra("args")?.let { JSONObject(it) } ?: JSONObject()
        intent.removeExtra("action")
        launch(action, args)
    }

    private fun launch(action: String, args: JSONObject) {
        append("▶ $action")
        executor.execute {
            val result = Actions.run(action, args)
            runOnUiThread { append("$action → ${result.toString(1).take(3000)}") }
        }
    }

    private fun append(line: String) {
        log.append(line + "\n")
    }
}
