# Hold-to-Talk Implementation Plan (Revised)

## What the user wants

New config option `voice.hold_to_talk: true` that changes the voice recording behavior:

- **Current behavior:** Press record key → starts VAD recording (auto-stops on silence after `silence_duration` seconds). Second press force-stops. VAD auto-restarts if `auto_continuous: true`.
- **Hold-to-talk behavior:** Press record key → starts recording (NO VAD, NO silence detection). Recording stays open. While holding the key down, repeat keypress events fire (terminal key repeat). Each repeat resets a "release timer". When the key is released, repeat events stop, the timer fires (after ~500ms debounce), and recording stops + transcribes.

## How key repeat detection works

When you hold a key down in a terminal, the terminal sends repeated keypress events (initial press + repeat at ~30-50ms intervals depending on terminal key repeat rate). The approach:

1. **First press:** Start recording, set `_hold_timer = 500ms`
2. **Repeat presses (while holding):** Each event fires the handler. Since recording is already active AND the event arrived within 500ms of the last event, ignore it (just reset the timer). This is the "still holding" signal.
3. **Key release:** Repeat events stop. After 500ms with no new event, the timer fires → stop recording and transcribe.

The 500ms debounce prevents premature stop if the user briefly lifts their finger, and gives enough margin for the last repeat event to arrive.

**Both TUI (Ink `useInput`) and classic CLI (prompt_toolkit handler) fire on every key repeat**, so this works in both runtimes.

## Config change

**File:** `hermes_cli/config.py` (DEFAULT_CONFIG, line ~1632)

Add `hold_to_talk: False` to the `voice` section:

```python
"voice": {
    "record_key": "ctrl+b",
    "max_recording_seconds": 120,
    "auto_tts": False,
    "auto_continuous": True,
    "hold_to_talk": False,          # NEW: hold key to record, release to stop
    "beep_enabled": True,
    "silence_threshold": 200,
    "silence_duration": 3.0,
    "silence_retries": 3,
},
```

Bump `_config_version` by 1.

## How it works (TUI path)

The TUI's `useInputHandlers.ts` has the `voiceRecordToggle` function called when `isVoiceToggleKey` matches. Currently it toggles: first press = start, second press = stop.

In hold-to-talk mode, the handler changes:

1. **Press fires → not recording:** Start recording (call `voice.record` RPC with `action: 'start'`). Set a timer ref (500ms).
2. **Press fires → recording active:** Reset the timer (clear old, set new 500ms). This means "still holding."
3. **Timer fires (no press within 500ms):** Key was released. Stop recording (call `voice.record` RPC with `action: 'stop'`). Clear timer.

Implementation in `useInputHandlers.ts`:
- Add a `useRef` for the release timer (Node.js `setTimeout` handle)
- In `voiceRecordToggle`, when `voice.recording` is true and `hold_to_talk` is enabled, reset the timer instead of stopping
- The timer callback calls the stop RPC

## How it works (backend path)

The TUI gateway's `voice.record` handler currently uses `start_continuous(auto_restart=False)` which still has VAD. For hold-to-talk mode, switch to the simpler `start_recording()` / `stop_and_transcribe()` pair from `hermes_cli/voice.py` which has NO VAD at all.

**File:** `tui_gateway/server.py` — `voice.record` handler (line ~7274)

- Read `voice.hold_to_talk` from config
- When `hold_to_talk` is true AND action is "start": call `hermes_cli.voice.start_recording()` instead of `start_continuous()`
- When `hold_to_talk` is true AND action is "stop": call `hermes_cli.voice.stop_and_transcribe()` instead of `stop_continuous(force_transcribe=True)`. Emit `voice.transcript` event with the result.
- Return `{"status": "recording"}` on start, `{"status": "stopped", "transcript": "..."}` on stop (transcript may be null if no speech detected)

## Files to change

### 1. `hermes_cli/config.py`
- Add `"hold_to_talk": False` to DEFAULT_CONFIG voice section
- Bump `_config_version`

### 2. `hermes_cli/voice.py`
- Add `_hold_to_talk_enabled()` helper (reads `voice.hold_to_talk` from config, same pattern as `_beeps_enabled()`)

### 3. `tui_gateway/server.py` — `voice.record` handler (line ~7274)
- Read `voice.hold_to_talk` from config
- When true: use `start_recording()` / `stop_and_transcribe()` instead of `start_continuous()` / `stop_continuous()`
- On stop, emit `voice.transcript` event with transcript text
- Include `hold_to_talk` in the response payload so frontend knows the mode

### 4. `tui_gateway/server.py` — `voice.toggle` status handler (line ~7193)
- Include `hold_to_talk` in the status response payload

### 5. `ui-tui/src/app/useInputHandlers.ts` — `voiceRecordToggle` (line ~224)
- Add `useRef` for release timer
- When `voice.recording` is true AND hold_to_talk mode is active: reset timer instead of stopping
- Timer fires after 500ms → call stop RPC
- Clear timer on component unmount

### 6. `ui-tui/src/gatewayTypes.ts`
- Add `hold_to_talk?: boolean` to voice status/response types

### 7. `ui-tui/src/app/createGatewayEventHandler.ts`
- Handle `hold_to_talk` field in `voice.status` events

### 8. `apps/desktop/src/app/settings/constants.ts`
- Add `'voice.hold_to_talk'` to settings labels and voice section list

### 9. `hermes_cli/tips.py`
- Add tip about `voice.hold_to_talk`

### 10. Classic CLI (`cli.py`) — optional for later
- Same pattern: in `_voice_start_recording`, if hold_to_talk is enabled, start recording without VAD. In the key handler, reset timer on repeat presses. Timer fires → stop and transcribe.
- Can be done after TUI path is working.

## Timing constants

- **Release debounce:** 500ms — time after last keypress event before we consider the key "released"
- This is configurable but hardcoded for now. Can be a config option (`voice.hold_release_debounce_ms`) later if needed.

## Edge cases

1. **User presses key twice quickly (tap-tap):** First tap starts recording, 500ms passes, timer fires and stops. Second tap starts again. This is fine — it's equivalent to the current toggle behavior for quick taps.
2. **User holds for a very long time (minutes):** Recording continues. `max_recording_seconds` still caps it (the recorder enforces this).
3. **Agent is speaking (TTS) when user presses key:** The TTS-vs-STT feedback guard (`_tts_playing` Event) already handles this. Recording won't start until TTS finishes.
4. **Terminal key repeat rate is very slow:** If the terminal sends repeats slower than 500ms, the timer would fire prematurely. Most terminals repeat at 30-50ms intervals. If this is an issue, increase debounce to 1000ms.

## Testing

1. Set `voice.hold_to_talk: true` in config
2. `/voice on` then press and HOLD record key → recording starts
3. Keep holding for 5+ seconds → recording continues (no VAD silence stop)
4. Release key → after ~500ms, recording stops and transcribes
5. Verify no auto-restart happens
6. Quick tap (press and release immediately) → starts recording, 500ms timer fires, stops. Equivalent to toggle behavior.
7. Set `voice.hold_to_talk: false` → verify VAD toggle behavior returns to normal
