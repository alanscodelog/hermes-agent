# openwakeword.model does `import tflite_runtime.interpreter` — alias the
# LiteRT interpreter under that name. ai_edge_litert is declared as a
# runtime dependency of this shim on Linux (see pyproject.toml).
from ai_edge_litert import interpreter

globals().update(interpreter.__dict__ if hasattr(interpreter, "__dict__") else {})
