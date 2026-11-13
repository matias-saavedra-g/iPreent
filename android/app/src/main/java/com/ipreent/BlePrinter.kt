package com.ipreent

import android.annotation.SuppressLint
import android.bluetooth.*
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.os.Build
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import java.util.UUID

private val WRITE_CHARS = listOf("0000ae01", "0000ff02", "0000ab01", "0000ae81", "49535343-8841")
private val NOTIFY_CHARS = listOf("0000ae02", "0000ae04", "0000ff03", "0000ab03", "49535343-1e4d")
private val SERVICES = listOf("0000ae00", "0000ff00", "0000ab00", "0000ae80", "49535343")
private val CCCD = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")

private fun UUID.matches(prefixes: List<String>) = prefixes.any { toString().lowercase().startsWith(it) }

data class Found(val name: String, val address: String)

/** BLE transport. Port of ipreent/ble.py. All permission checks happen in the UI before we get here. */
@SuppressLint("MissingPermission")
class BlePrinter private constructor(private val gatt: BluetoothGatt, val model: Model, private val cb: Callback) {

    companion object {
        /** Devices whose name matches a known model or that advertise a printer service. */
        suspend fun scan(ctx: Context, isKnown: (String) -> Boolean, millis: Long = 6000): List<Found> {
            val scanner = adapter(ctx).bluetoothLeScanner ?: fail(R.string.err_bt_off, "Bluetooth is off")
            val found = linkedMapOf<String, Found>()
            val cb = object : ScanCallback() {
                override fun onScanResult(type: Int, r: ScanResult) {
                    val name = r.scanRecord?.deviceName ?: r.device.name ?: ""
                    val uuids = r.scanRecord?.serviceUuids.orEmpty().map { it.uuid }
                    if (isKnown(name) || uuids.any { it.matches(SERVICES) })
                        found[r.device.address] = Found(name, r.device.address)
                }
            }
            scanner.startScan(null, ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(), cb)
            try { delay(millis) } finally { scanner.stopScan(cb) }
            return found.values.toList()
        }

        suspend fun connect(ctx: Context, address: String, model: Model): BlePrinter {
            val cb = Callback()
            val dev = adapter(ctx).getRemoteDevice(address)
            val gatt = dev.connectGatt(ctx, false, cb, BluetoothDevice.TRANSPORT_LE)
            try {
                withTimeout(15000) {
                    cb.connected.await()
                    gatt.discoverServices(); cb.discovered.await()
                    if (gatt.requestMtu(maxOf(23, model.mtu + 3))) withTimeoutOrNull(3000) { cb.mtu.await() }
                }
                val p = BlePrinter(gatt, model, cb)
                p.setup()
                return p
            } catch (e: Throwable) {
                gatt.close(); throw e
            }
        }

        private fun adapter(ctx: Context) =
            (ctx.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager).adapter
                ?: fail(R.string.err_no_bt, "No Bluetooth on this device")
    }

    class Callback : BluetoothGattCallback() {
        val connected = CompletableDeferred<Unit>()
        val discovered = CompletableDeferred<Unit>()
        val mtu = CompletableDeferred<Int>()
        val writes = Channel<Int>(Channel.CONFLATED)
        val replies = Channel<Pair<Int, ByteArray>>(Channel.UNLIMITED)
        val paused = MutableStateFlow(false)

        override fun onConnectionStateChange(g: BluetoothGatt, status: Int, state: Int) {
            if (state == BluetoothProfile.STATE_CONNECTED) connected.complete(Unit)
            else {
                val e = UserError(R.string.err_disconnected, listOf(status), "Disconnected (status $status)")
                connected.completeExceptionally(e); discovered.completeExceptionally(e)
                writes.close(e)
            }
        }
        override fun onServicesDiscovered(g: BluetoothGatt, status: Int) { discovered.complete(Unit) }
        override fun onMtuChanged(g: BluetoothGatt, m: Int, status: Int) { mtu.complete(m) }
        override fun onCharacteristicWrite(g: BluetoothGatt, c: BluetoothGattCharacteristic, status: Int) { writes.trySend(status) }
        override fun onDescriptorWrite(g: BluetoothGatt, d: BluetoothGattDescriptor, status: Int) { writes.trySend(status) }

        @Deprecated("pre-33 callback")
        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic) {
            @Suppress("DEPRECATION") handle(c.value ?: return)
        }
        override fun onCharacteristicChanged(g: BluetoothGatt, c: BluetoothGattCharacteristic, value: ByteArray) = handle(value)

        private fun handle(data: ByteArray) {
            for ((cmd, payload) in Protocol.parseNotification(data)) {
                if (cmd == Protocol.CMD_FLOW) paused.value = payload.firstOrNull() == 0x10.toByte()
                else replies.trySend(cmd to payload)
            }
        }
    }

    private lateinit var writeChar: BluetoothGattCharacteristic
    private val mtu get() = if (cb.mtu.isCompleted) cb.mtu.getCompleted() else 23

    private suspend fun setup() {
        val chars = gatt.services.flatMap { it.characteristics }
        writeChar = chars.firstOrNull { it.uuid.matches(WRITE_CHARS) }
            ?: fail(R.string.err_no_write_char, "No known write characteristic; is this a supported printer?")
        for (c in chars.filter { it.uuid.matches(NOTIFY_CHARS) && it.properties and BluetoothGattCharacteristic.PROPERTY_NOTIFY != 0 }) {
            gatt.setCharacteristicNotification(c, true)
            val d = c.getDescriptor(CCCD) ?: continue
            val v = BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE
            if (Build.VERSION.SDK_INT >= 33) gatt.writeDescriptor(d, v)
            else @Suppress("DEPRECATION") { d.value = v; gatt.writeDescriptor(d) }
            withTimeoutOrNull(2000) { cb.writes.receive() }
        }
    }

    private suspend fun write(chunk: ByteArray) {
        val noRsp = writeChar.properties and BluetoothGattCharacteristic.PROPERTY_WRITE_NO_RESPONSE != 0
        val type = if (noRsp) BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE else BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
        repeat(50) {   // the stack refuses a write while the previous one is in flight: retry briefly
            val ok = if (Build.VERSION.SDK_INT >= 33) gatt.writeCharacteristic(writeChar, chunk, type) == BluetoothStatusCodes.SUCCESS
            else @Suppress("DEPRECATION") run { writeChar.writeType = type; writeChar.value = chunk; gatt.writeCharacteristic(writeChar) }
            if (ok) { withTimeoutOrNull(1000) { cb.writes.receive() }; return }
            delay(10)
        }
        fail(R.string.err_bt_write, "Bluetooth write failed")
    }

    suspend fun send(data: ByteArray, progress: (Float) -> Unit = {}) {
        val chunk = maxOf(20, minOf(model.mtu, mtu - 3))
        var i = 0
        while (i < data.size) {
            while (cb.paused.value) delay(20)
            write(data.copyOfRange(i, minOf(data.size, i + chunk)))
            delay(model.intervalMs.toLong())
            i += chunk
            progress(minOf(i, data.size).toFloat() / data.size)
        }
    }

    suspend fun request(cmd: Int, timeout: Long = 2000): ByteArray? {
        while (cb.replies.tryReceive().isSuccess) { /* drain */ }
        send(Protocol.frame(cmd, Protocol.bytes(0), model.newFormat))
        return withTimeoutOrNull(timeout) {
            var got: Pair<Int, ByteArray>
            do got = cb.replies.receive() while (got.first != cmd)
            got.second
        }
    }

    /** Poll state until the printer stops reporting 'printing'. */
    suspend fun waitDone(timeout: Long = 60000): ByteArray? = withTimeoutOrNull(timeout) {
        while (true) {
            val st = request(Protocol.CMD_GET_STATE)
            if (st == null || st[0].toInt() and 0x80 == 0) return@withTimeoutOrNull st
            delay(500)
        }
        @Suppress("UNREACHABLE_CODE") null
    }

    fun close() { gatt.disconnect(); gatt.close() }
}
