"""Check the actual frozen runtime and bundled model without recording or sending."""

import json
from pathlib import Path
import platform
import time
import wave

from model_store import MODEL_FILES, _valid_file
from project_paths import data_dir, project_root


def run_check(output, audio=None):
    started = time.monotonic()
    report = {"ok": False, "root": str(project_root()), "architecture": platform.machine(),
              "checks": [], "errors": []}
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.update_idletasks()
        root.destroy()
        report["checks"].append("Tk UI runtime")

        import pyaudio
        report["audio_runtime"] = pyaudio.get_portaudio_version_text()
        report["checks"].append("PortAudio runtime (no microphone opened)")

        from windows_extension_setup import EXTENSION_FILES, prepare_extension
        folder = prepare_extension()
        assert all((folder / relative).is_file() for relative in EXTENSION_FILES)
        assert folder.is_relative_to(project_root())
        report["checks"].append("browser extension assets")

        from voice import recognition_settings
        _, config = recognition_settings("sensevoice")
        model = Path(config["local_model_dir"])
        assert model.is_relative_to(data_dir()), "Model is outside the portable data directory"
        for spec in MODEL_FILES:
            assert _valid_file(model / spec.name, spec, None), f"Invalid model file: {spec.name}"
        report["model_dir"] = str(model)
        report["checks"].append("model SHA-256")

        import numpy as np
        from local_voice import create_recognizer
        recognizer = create_recognizer(config)
        if audio:
            with wave.open(str(audio), "rb") as wav:
                assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
                samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(np.float32) / 32768
        else:
            samples = np.zeros(16000, dtype=np.float32)
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, samples)
        recognizer.decode_stream(stream)
        report["recognized_text"] = stream.result.text
        report["checks"].append("CPU offline speech inference")
        report["ok"] = True
    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")
    report["elapsed_seconds"] = round(time.monotonic() - started, 2)
    output = Path(output).resolve()
    if not output.is_relative_to(project_root()):
        raise ValueError("Self-check report must stay inside the application folder")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1
