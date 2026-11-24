package dev.bento.engine.bridge

import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.os.BatteryManager
import android.os.Build
import android.os.PowerManager
import android.os.StatFs
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** `DeviceConditions` of api/android-endpoints.md §2. */
@Serializable
data class DeviceConditionsSnapshot(
    val online: Boolean,
    val metered: Boolean,
    val unmetered: Boolean,
    val charging: Boolean,
    @SerialName("battery_pct") val batteryPct: Int,
    @SerialName("power_save") val powerSave: Boolean,
    @SerialName("data_saver") val dataSaver: Boolean,
    @SerialName("storage_free_bytes") val storageFreeBytes: Long,
    val thermal: String,
)

/** Raw platform readings; [ConditionsMapping.map] is the pure, JVM-tested part. */
data class RawConditions(
    val hasInternet: Boolean,
    val validated: Boolean,
    val notMetered: Boolean,
    val temporarilyNotMetered: Boolean,
    val restrictBackgroundStatus: Int,
    val batteryStatus: Int,
    val plugged: Int,
    val batteryLevel: Int,
    val batteryScale: Int,
    val powerSave: Boolean,
    val thermalStatus: Int,
    val storageFreeBytes: Long,
)

object ConditionsMapping {
    // Platform constants copied so the mapping runs on the JVM without android.jar values.
    private const val RESTRICT_BACKGROUND_STATUS_ENABLED = 3
    private const val BATTERY_STATUS_CHARGING = 2
    private const val BATTERY_STATUS_FULL = 5

    fun map(raw: RawConditions): DeviceConditionsSnapshot {
        val online = raw.hasInternet && raw.validated
        val unmetered = online && (raw.notMetered || raw.temporarilyNotMetered)
        val charging = raw.plugged != 0 || raw.batteryStatus == BATTERY_STATUS_CHARGING || raw.batteryStatus == BATTERY_STATUS_FULL
        val pct = if (raw.batteryLevel >= 0 && raw.batteryScale > 0) (raw.batteryLevel * 100 / raw.batteryScale).coerceIn(0, 100) else 100
        return DeviceConditionsSnapshot(
            online = online,
            metered = online && !unmetered,
            unmetered = unmetered,
            charging = charging,
            batteryPct = pct,
            powerSave = raw.powerSave,
            dataSaver = raw.restrictBackgroundStatus == RESTRICT_BACKGROUND_STATUS_ENABLED,
            storageFreeBytes = raw.storageFreeBytes.coerceAtLeast(0),
            thermal = thermal(raw.thermalStatus),
        )
    }

    /** `PowerManager.THERMAL_STATUS_*` → `none|light|moderate|severe` (critical and above are severe). */
    fun thermal(status: Int): String = when {
        status <= 0 -> "none"
        status == 1 -> "light"
        status == 2 -> "moderate"
        else -> "severe"
    }
}

/**
 * [DeviceConditions] from ConnectivityManager, the sticky battery broadcast, PowerManager and StatFs.
 * [observe] reports changes (network and power) while the engine runs, as `on_event("conditions", …)`.
 */
class AndroidDeviceConditions(private val context: Context) : DeviceConditions {
    private val connectivity = context.getSystemService(ConnectivityManager::class.java)
    private val power = context.getSystemService(PowerManager::class.java)
    private var callback: ConnectivityManager.NetworkCallback? = null
    private var powerReceiver: android.content.BroadcastReceiver? = null
    private var thermalListener: PowerManager.OnThermalStatusChangedListener? = null

    override fun snapshot(): String = BridgeJson.encodeToString(DeviceConditionsSnapshot.serializer(), current())

    fun current(): DeviceConditionsSnapshot = ConditionsMapping.map(read())

    private fun read(): RawConditions {
        val caps = connectivity.activeNetwork?.let(connectivity::getNetworkCapabilities)
        val battery = context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        return RawConditions(
            hasInternet = caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) == true,
            validated = caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) == true,
            notMetered = caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED) == true,
            temporarilyNotMetered = Build.VERSION.SDK_INT >= Build.VERSION_CODES.R &&
                caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_TEMPORARILY_NOT_METERED) == true,
            restrictBackgroundStatus = connectivity.restrictBackgroundStatus,
            batteryStatus = battery?.getIntExtra(BatteryManager.EXTRA_STATUS, -1) ?: -1,
            plugged = battery?.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) ?: 0,
            batteryLevel = battery?.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) ?: -1,
            batteryScale = battery?.getIntExtra(BatteryManager.EXTRA_SCALE, -1) ?: -1,
            powerSave = power.isPowerSaveMode,
            thermalStatus = power.currentThermalStatus,
            storageFreeBytes = runCatching { StatFs(context.filesDir.absolutePath).availableBytes }.getOrDefault(0L),
        )
    }

    /** Start change callbacks; [onChange] receives the new snapshot JSON. */
    fun observe(onChange: (String) -> Unit) {
        stopObserving()
        val network = object : ConnectivityManager.NetworkCallback() {
            override fun onCapabilitiesChanged(network: Network, networkCapabilities: NetworkCapabilities) = onChange(snapshot())

            override fun onLost(network: Network) = onChange(snapshot())
        }
        connectivity.registerDefaultNetworkCallback(network)
        callback = network
        val receiver = object : android.content.BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) = onChange(snapshot())
        }
        val filter = IntentFilter().apply {
            addAction(Intent.ACTION_POWER_CONNECTED)
            addAction(Intent.ACTION_POWER_DISCONNECTED)
            addAction(Intent.ACTION_BATTERY_LOW)
            addAction(Intent.ACTION_BATTERY_OKAY)
            addAction(PowerManager.ACTION_POWER_SAVE_MODE_CHANGED)
        }
        androidx.core.content.ContextCompat.registerReceiver(context, receiver, filter, androidx.core.content.ContextCompat.RECEIVER_NOT_EXPORTED)
        powerReceiver = receiver
        val thermal = PowerManager.OnThermalStatusChangedListener { onChange(snapshot()) }
        power.addThermalStatusListener(context.mainExecutor, thermal)
        thermalListener = thermal
    }

    fun stopObserving() {
        callback?.let { runCatching { connectivity.unregisterNetworkCallback(it) } }
        callback = null
        powerReceiver?.let { runCatching { context.unregisterReceiver(it) } }
        powerReceiver = null
        thermalListener?.let { runCatching { power.removeThermalStatusListener(it) } }
        thermalListener = null
    }
}
