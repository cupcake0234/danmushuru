"""Offline SenseVoice with Coopanion's energy-based utterance segmentation."""

import queue
import re
import threading
from collections import deque
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000
FRAME_SAMPLES = 320  # 20 ms
MAX_PENDING_UTTERANCES = 4


class UtteranceSegmenter:
    """Retain 320 ms before speech; finish on silence or after 15 seconds."""

    def __init__(self, silence_ms=800, threshold_db=-42):
        self.silence_ms = silence_ms
        self.threshold_db = threshold_db
        self.pre_roll = deque(maxlen=16)
        self.frames = []
        self.speaking = False
        self.above_ms = 0
        self.below_ms = 0
        self.speech_ms = 0

    def push(self, frame):
        samples = np.frombuffer(frame, dtype="<i2").astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(samples * samples)))
        loud = rms >= 10 ** (self.threshold_db / 20)
        if not self.speaking:
            self.pre_roll.append(frame)
            self.above_ms = self.above_ms + 20 if loud else 0
            if self.above_ms >= 180:
                self.speaking = True
                self.frames = list(self.pre_roll)
                self.pre_roll.clear()
                self.speech_ms = self.above_ms
                self.below_ms = 0
            return None
        self.frames.append(frame)
        self.speech_ms += 20 if loud else 0
        self.below_ms = 0 if loud else self.below_ms + 20
        forced = len(self.frames) >= 750
        if self.below_ms < self.silence_ms and not forced:
            return None
        # Keep at most 100 ms of trailing silence for the recognizer.
        trim = max(0, self.below_ms // 20 - 5)
        frames = self.frames[:-trim] if trim else self.frames
        result = b"".join(frames) if self.speech_ms >= 180 else None
        self.frames = []
        self.above_ms = self.below_ms = self.speech_ms = 0
        self.speaking = forced  # Continue long speech without another onset test.
        return result


def create_recognizer(config):
    try:
        import sherpa_onnx
    except ImportError as exc:
        raise RuntimeError("缺少本地识别依赖；请运行 python -m pip install -r requirements.txt") from exc
    path = Path(config["local_model_dir"])
    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(path / "model.int8.onnx"), tokens=str(path / "tokens.txt"),
        num_threads=config.get("local_num_threads", 2), sample_rate=SAMPLE_RATE,
        feature_dim=80, provider="cpu", language=config.get("local_language", "auto"),
        use_itn=True, debug=False,
    )


class LocalRecognition:
    """Capture stays responsive while a separate worker decodes finished utterances."""

    def __init__(self, config, silence_ms, on_sentence, on_error):
        self.recognizer = create_recognizer(config)
        self.segmenter = UtteranceSegmenter(silence_ms, config.get("local_threshold_db", -42))
        self.on_sentence = on_sentence
        self.on_error = on_error
        self.pending = queue.Queue(maxsize=MAX_PENDING_UTTERANCES)
        self.stopped = threading.Event()
        self.thread = None
        self.remainder = b""

    def start(self):
        self.thread = threading.Thread(target=self._decode, daemon=True)
        self.thread.start()

    def send_audio_frame(self, data):
        if self.stopped.is_set():
            return
        data = self.remainder + data
        size = FRAME_SAMPLES * 2
        complete = len(data) // size * size
        self.remainder = data[complete:]
        for at in range(0, complete, size):
            pcm = self.segmenter.push(data[at:at + size])
            if pcm:
                try:
                    self.pending.put_nowait(pcm)
                except queue.Full:
                    self.stopped.set()
                    self.on_error("本地识别处理不及，待识别语音已积压；已停止录音，请减少后台负载。")
                    return

    def _decode(self):
        recognizer = self.recognizer
        try:
            while not self.stopped.is_set():
                try:
                    pcm = self.pending.get(timeout=0.1)
                except queue.Empty:
                    continue
                if self.stopped.is_set():
                    break
                samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
                stream = recognizer.create_stream()
                stream.accept_waveform(SAMPLE_RATE, samples)
                recognizer.decode_stream(stream)
                text = re.sub(r"<\|[^|]*\|>", "", stream.result.text).strip()
                if text and any(char.isalnum() for char in text) and not self.stopped.is_set():
                    self.on_sentence(text)
        except Exception as exc:
            if not self.stopped.is_set():
                self.stopped.set()
                self.on_error(f"本地语音识别失败：{exc}")

    def stop(self):
        self.stopped.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
        self.recognizer = None
