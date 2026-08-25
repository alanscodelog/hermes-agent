# Bundled wake-word models

`hey_hermes.onnx` / `hey_hermes.tflite` — the on-device "Hey Hermes" hotword
model. This is the default detector for the wake word feature (see
`website/docs/user-guide/features/wake-word.md`); no training or setup is
required to say "hey hermes".

- **Engine:** [openWakeWord](https://github.com/dscripka/openWakeWord) (Apache-2.0).
- **Provenance:** trained with the openWakeWord training pipeline (synthetic
  TTS-generated speech), which produces both the `.onnx` and `.tflite` artifacts.
  Redistribution is permitted under the openWakeWord license.
- **Label:** the model registers as `hey_hermes` (matches the filename).
- **Runtime:** openWakeWord's shared feature-extraction models (melspectrogram +
  embedding) are NOT bundled here. `tools/wake_word.py` resolves them from
  `HERMES_WAKE_WORD_MODELS` when set (the Nix desktop derivation bundles them
  at build time and points the var there), otherwise fetches them once on
  first use into the writable `~/.hermes/cache/wakewords/openwakeword/`
  directory — never into the install dir, which is read-only under Nix/frozen
  installs — and passes them to the engine as explicit model paths. Built-in
  wake words (e.g. `hey_jarvis`) auto-download their own model file into the
  same directory on first use.

To use a different phrase, train your own model and point
`wake_word.openwakeword.model` at its path, or set a built-in openWakeWord name
(`hey_jarvis`, `alexa`, `hey_mycroft`, …). See the wake-word docs for the
training guide.
