# Plan: Audio Device Hot-Swap & Selection

## What exists

- `AudioPipeline.list_devices()` (pipeline.py:403) — scans sounddevice/PortAudio, returns deduplicated input/output devices with index/name/sample_rate
- `_handle_get_audio_devices()` (iris_gateway.py:5185) — WebSocket handler sends device lists to frontend on `get_audio_devices` request
- Frontend `useIRISWebSocket.ts` (line 799) dispatches `iris:audio_devices` custom event
- `SidePanel.tsx` (line 260) renders input_device/output_device dropdowns populated from the event
- `AudioEngine.initialize()` (engine.py:367) auto-selects mic on startup, reads `config["input_device"]`/`config["output_device"]`
- `AudioEngine.update_config()` (engine.py:537) calls `stop() → initialize() → start()` when config changes — correct restart sequence already built
- `AudioPipeline.cleanup()` + `stop()` properly close input streams

## What's missing

1. **No `select_audio_device` WebSocket message** — frontend shows devices but cannot tell backend to switch
2. **No hot-plug detection** — sounddevice/PortAudio doesn't fire events when USB/BT devices connect
3. **Frontend doesn't save device selection** — dropdown renders device names but selecting one does nothing

## Implementation (3 small changes)

### 1. Backend: `_handle_select_audio_device` (iris_gateway.py, NEW at line ~5255)

New WS message type: `select_audio_device`
Payload: `{ device_type: "input" | "output", device_index: int, device_name: string }`

Logic:
```python
async def _handle_select_audio_device(self, session_id, client_id, message):
    payload = message.get("payload", {})
    device_type = payload.get("device_type")    # "input" or "output"
    device_index = payload.get("device_index")
    device_name = payload.get("device_name", f"index {device_index}")

    if device_type not in ("input", "output"):
        # error response
        return
    if device_index is None:
        # error response
        return

    # Get AudioEngine singleton, update config, trigger restart
    from .audio.engine import get_audio_engine
    engine = get_audio_engine()
    engine.update_config(**{f"{device_type}_device": device_index})

    # Persist in iris_config.json so it survives restarts
    _persist_audio_device(device_type, device_index, device_name)

    # Send confirmation
    await self._ws_manager.send_to_client(client_id, {
        "type": "audio_device_selected",
        "payload": { "device_type": device_type, "device_index": device_index, "name": device_name }
    })

    # Re-push the full device list so frontend updates "active device" highlight
    await self._handle_get_audio_devices(session_id, client_id)
```

Register in `_handle_message` dispatch table at ~line 428 (alongside `get_audio_devices`):
```python
elif msg_type == "select_audio_device":
    await self._handle_select_audio_device(session_id, client_id, message)
```

**Reuse existing `update_config()` path** — it already:
1. Updates `self.config["input_device"]` or `self.config["output_device"]`
2. Calls `self.stop()` → proper cleanup of input stream
3. Calls `self.initialize()` → creates new AudioPipeline with new device index
4. Calls `self.start()` → opens new input stream on the selected device
5. Re-registers frame listeners and wake-word callback (automatically — they're re-registered in start())

**No new stream management code needed.** `update_config()` handles the hot-swap atomically.

### 2. Backend: Device change polling (engine.py, ~line 580)

sounddevice doesn't have hot-plug events, so we poll `list_devices()` every 2 seconds in a daemon thread. When the snapshot changes, broadcast `audio_devices_updated` to all connected clients.

Add to `AudioEngine.start()`:
```python
self._device_poll_stop = threading.Event()
self._device_poll_thread = threading.Thread(
    target=self._poll_device_changes, daemon=True, name="iris-device-poll"
)
self._device_poll_thread.start()
```

New method in `AudioEngine`:
```python
def _poll_device_changes(self):
    """Poll audio devices every 2s. Broadcast if the set of indices changes."""
    last_inputs = set()
    last_outputs = set()
    while not self._device_poll_stop.wait(2.0):
        try:
            devices = AudioPipeline.list_devices()
            inputs = set(d["index"] for d in devices if d["input"])
            outputs = set(d["index"] for d in devices if d["output"])
            if inputs != last_inputs or outputs != last_outputs:
                last_inputs, last_outputs = inputs, outputs
                logger.info(
                    f"[AudioEngine] Device change detected: "
                    f"inputs={len(inputs)}, outputs={len(outputs)}"
                )
                self._broadcast_threadsafe({
                    "type": "audio_devices_changed",
                    "payload": {"inputs": len(inputs), "outputs": len(outputs)}
                })
        except Exception:
            pass  # PortAudio may be locked during stream start — skip this poll
```

Add cleanup in `AudioEngine.stop()`:
```python
self._device_poll_stop.set()
```

This pushes a lightweight `audio_devices_changed` notification. The frontend responds by calling `get_audio_devices` to fetch the full updated list.

### 3. Frontend: Wire device selection + refresh (SidePanel.tsx + useIRISWebSocket.ts)

**useIRISWebSocket.ts** — add a `selectAudioDevice` method and listen for `audio_devices_changed`:

```typescript
const selectAudioDevice = useCallback((deviceType: "input"|"output", index: number, name: string) => {
    sendMessage("select_audio_device", {
        device_type: deviceType,
        device_index: index,
        device_name: name
    })
}, [sendMessage])
```

Add WS case for `audio_devices_changed`:
```typescript
case "audio_devices_changed":
    // A device was plugged/unplugged — re-fetch the full list
    sendMessage("get_audio_devices", {})
    break
```

**SidePanel.tsx** — connect the dropdown `onChange` to `selectAudioDevice`:

The microphone-card and speaker-card dropdowns already render. Just wire `onChange`:
```typescript
case "dropdown":
    return (
        <DropdownField
            key={field.id}
            id={field.id}
            label={field.label}
            value={(fieldValue as string) ?? ""}
            options={fieldOptions}
            onChange={(value) => {
                onValueChange(field.id, value)
                // If this is an audio device dropdown, notify backend
                if (card.id === 'microphone-card' && field.id === 'input_device') {
                    const device = audioInputDevices.includes(value) ? value : null
                    if (device) {
                        selectAudioDevice('input', audioInputDeviceMap[device], device)
                    }
                }
                if (card.id === 'speaker-card' && field.id === 'output_device') {
                    const device = audioOutputDevices.includes(value) ? value : null
                    if (device) {
                        selectAudioDevice('output', audioOutputDeviceMap[device], device)
                    }
                }
            }}
            glowColor={glowColor}
        />
    )
```

Need to store device name→index maps alongside device name lists:
```typescript
// In SidePanel.tsx handleAudioDevices callback:
const inputDeviceOptions = inputDevices.map((d: any) => d.name || d.index)
const outputDeviceOptions = outputDevices.map((d: any) => d.name || d.index)
const inputMap: Record<string,number> = {}
inputDevices.forEach((d:any) => { inputMap[d.name || d.index] = d.index })
const outputMap: Record<string,number> = {}
outputDevices.forEach((d:any) => { outputMap[d.name || d.index] = d.index })
setAudioInputDevices(inputDeviceOptions)
setAudioOutputDevices(outputDeviceOptions)
setAudioInputDeviceMap(inputMap)
setAudioOutputDeviceMap(outputMap)
```

### 4. Persistence (optional but nice)

Save selected device to `data/iris_config.json` so it survives backend restarts. `_persist_audio_device(device_type, device_index, device_name)` updates `PortConfig` and saves:

```python
def _persist_audio_device(device_type, device_index, name):
    from .iris_config import load_config, save_config
    cfg = load_config()
    if device_type == "input":
        cfg.audio.input_device = device_index
    else:
        cfg.audio.output_device = device_index
    save_config(cfg)
    logger.info(f"[Audio] Persisted {device_type} device: {name} (index {device_index})")
```

**Note**: `PortConfig` may not have `audio` struct — we may need to add `audio` or just save to a separate persistent section. If `iris_config.json` doesn't have audio fields, skip persistence for now and just keep it runtime-only (user re-selects on restart — acceptable).

## Testing plan

1. **No breakage**: Restart backend, confirm AUDIO DIAG shows `READY`, frontend renders orb, voice works
2. **Device list**: Open Voice settings → microphone-card → dropdown shows current devices
3. **Device switch**: Select a different input, confirm backend log shows `update_config → stop → initialize → start` with new device index
4. **Hot-plug**: Unplug USB mic, wait 2s, confirm `audio_devices_changed` broadcast, reopen voice settings → device list updated
5. **Plug back in**: Reconnect mic, wait 2s, reopen settings → device reappears
6. **Default device**: Select "system default" (index=None/null), backend should pick system default on next boot
7. **Edge case**: Switch device while recording → recording should stop gracefully (update_config calls stop() first)

## Files to modify

1. `backend/iris_gateway.py` — add `_handle_select_audio_device` (~70 lines), message dispatch entry
2. `backend/audio/engine.py` — add `_poll_device_changes`, cleanup in `stop()`, `_device_poll_stop` attr (~40 lines)
3. `hooks/useIRISWebSocket.ts` — add `selectAudioDevice`, `audio_devices_changed` handler (~30 lines)
4. `components/wheel-view/SidePanel.tsx` — add map state, wire dropdown onChange (~20 lines)

Total: ~160 lines across 4 files. No new dependencies.
