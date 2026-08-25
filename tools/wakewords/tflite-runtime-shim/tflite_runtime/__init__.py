# tflite-runtime shim — satisfies openwakeword's Linux-only
# `tflite-runtime>=2.8` requirement on Python >= 3.12, where Google stopped
# shipping interpreter wheels. Re-exports LiteRT (ai-edge-litert, the
# maintained successor) under the module name openWakeWord imports. The
# runtime bridge in tools/wake_word.py (ensure_tflite_runtime) performs the
# same aliasing in-process for macOS; this package covers sealed Nix venvs,
# which cannot receive that fix at import time.
