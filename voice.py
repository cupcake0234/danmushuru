"""Continuous microphone transcription with DashScope or local SenseVoice."""

import json
import os
import queue
import sys
import threading
from pathlib import Path
from typing import Optional

from model_store import MODEL_NAME, managed_model_dir
from project_paths import data_dir, project_root


SAMPLE_RATE = 16000
FRAMES_PER_CHUNK = 1600  # 100 ms of 16-bit mono PCM
MAX_PENDING_SENTENCES = 50
DEFAULT_WS_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
DEFAULT_MODEL = "paraformer-realtime-v2"
DEFAULT_PROVIDER = "dashscope"  # Keep configurations without a provider compatible.
LOCAL_MODEL_NAME = MODEL_NAME
COOPANION_MODEL_DIR = Path(r"D:\Coopanion\data\home\models\desktop-pet") / LOCAL_MODEL_NAME
CONFIG_PATH = data_dir() / "config.local.json"
LOOPBACK_NAMES = ("blackhole", "soundflower", "loopback", "virtual audio", "obs virtual")


class VoiceError(RuntimeError):
    pass


def _settings_path():
    if not CONFIG_PATH.exists() and CONFIG_PATH.parent.name == "data":
        base = CONFIG_PATH.parent.parent
        for legacy in (base / CONFIG_PATH.name, base / "dist" / CONFIG_PATH.name):
            if legacy.is_file():
                return legacy
    return CONFIG_PATH


def read_settings_file():
    path = _settings_path()
    if path.exists():
        try:
            config = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise VoiceError(f"无法读取 {path.name}：{exc}") from exc
        if not isinstance(config, dict):
            raise VoiceError(f"{path.name} 的顶层必须是 JSON 对象。")
        return config
    return {}


def default_local_model_dir():
    managed = managed_model_dir()
    if all((managed / name).is_file() for name in ("model.int8.onnx", "tokens.txt")):
        return managed
    base = project_root()
    packaged = base / "models" / LOCAL_MODEL_NAME
    if packaged.is_dir():
        return packaged
    return managed


def local_model_path(value):
    if not isinstance(value, str):
        raise VoiceError("本地模型目录必须是字符串。")
    path = Path(value.strip()).expanduser() if value.strip() else default_local_model_dir()
    if not path.is_absolute():
        path = _settings_path().parent / path
    # Accept both the desktop-pet parent and the actual model directory.
    if not (path / "model.int8.onnx").is_file() and (path / LOCAL_MODEL_NAME).is_dir():
        path = path / LOCAL_MODEL_NAME
    missing = [name for name in ("model.int8.onnx", "tokens.txt") if not (path / name).is_file()]
    if missing:
        raise VoiceError(f"本地模型目录 {path} 缺少：{'、'.join(missing)}。"
                         "请打开“语音设置”，点击“一键安装模型”，或选择已有模型目录。")
    return path.resolve()


def recognition_settings(provider=None, model_dir=None):
    config = read_settings_file()
    selected = provider if provider is not None else config.get("voice_provider", DEFAULT_PROVIDER)
    if selected not in ("dashscope", "sensevoice"):
        raise VoiceError("voice_provider 必须为 dashscope 或 sensevoice。")
    if selected == "sensevoice":
        config["local_model_dir"] = str(local_model_path(
            model_dir if model_dir is not None else config.get("local_model_dir", "")))
        _validate_local_settings(config)
    return selected, config


def _validate_local_settings(config):
    if config.get("local_language", "auto") not in ("auto", "zh", "en", "ja", "ko", "yue"):
        raise VoiceError("本地识别语言必须为 auto、zh、en、ja、ko 或 yue。")
    threads = config.get("local_num_threads", 2)
    if type(threads) is not int or not 1 <= threads <= 32:
        raise VoiceError("本地识别线程数必须在 1 到 32 之间。")
    threshold = config.get("local_threshold_db", -42)
    if type(threshold) not in (int, float) or not -90 <= threshold <= -10:
        raise VoiceError("本地识别音量门限必须在 -90 到 -10 dBFS 之间。")


def save_settings(api_key, websocket_url, *, provider=None, local_model_dir=None,
                  local_language=None, local_num_threads=None, local_threshold_db=None):
    api_key = api_key.strip()
    websocket_url = websocket_url.strip()
    config = read_settings_file()
    selected = provider if provider is not None else config.get("voice_provider", DEFAULT_PROVIDER)
    if selected not in ("dashscope", "sensevoice"):
        raise VoiceError("请选择百炼或本地 SenseVoice。")
    if selected == "dashscope" and not api_key:
        raise VoiceError("请填写百炼 API Key。")
    if selected == "dashscope" and not websocket_url.startswith("wss://"):
        raise VoiceError("WebSocket 地址必须以 wss:// 开头。")
    if selected == "sensevoice":
        local_model_dir = str(local_model_path(
            local_model_dir if local_model_dir is not None else config.get("local_model_dir", "")))
    path = CONFIG_PATH
    if local_model_dir is not None:
        model_path = Path(local_model_dir)
        try:
            local_model_dir = model_path.relative_to(path.parent.resolve()).as_posix()
        except ValueError:
            pass
    config.update(dashscope_api_key=api_key, model=DEFAULT_MODEL, websocket_url=websocket_url)
    if provider is not None:
        config["voice_provider"] = selected
    for name, value in (("local_model_dir", local_model_dir), ("local_language", local_language),
                        ("local_num_threads", local_num_threads),
                        ("local_threshold_db", local_threshold_db)):
        if value is not None:
            config[name] = value
    if selected == "sensevoice":
        _validate_local_settings(config)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise VoiceError(f"无法保存 {path.name}：{exc}") from exc
    return path


def load_settings():
    config = read_settings_file()
    path = _settings_path()

    key = os.environ.get("DASHSCOPE_API_KEY") or config.get("dashscope_api_key", "")
    if not isinstance(key, str) or not key.strip():
        raise VoiceError(f"请在 {path} 的 dashscope_api_key 中填写百炼 API Key。")
    model = config.get("model", DEFAULT_MODEL)
    if model != DEFAULT_MODEL:
        raise VoiceError(f"当前仅支持 {DEFAULT_MODEL}，请检查 {path} 的 model。")
    websocket_url = os.environ.get("DASHSCOPE_WEBSOCKET_URL") or config.get(
        "websocket_url", DEFAULT_WS_URL
    )
    if not isinstance(websocket_url, str) or not websocket_url.startswith("wss://"):
        raise VoiceError(f"{path} 的 websocket_url 必须是 wss:// 地址。")
    return key.strip(), model, websocket_url


def _dependencies():
    try:
        import dashscope
        import pyaudio
        from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult
    except ImportError as exc:
        raise VoiceError("缺少语音依赖；先运行 python3 -m pip install -r requirements.txt") from exc
    return dashscope, pyaudio, Recognition, RecognitionCallback, RecognitionResult


def _audio_dependency():
    try:
        import pyaudio
    except ImportError as exc:
        raise VoiceError("缺少 PyAudio；请运行 python -m pip install -r requirements.txt") from exc
    return pyaudio


def list_input_devices():
    pyaudio = _audio_dependency()
    mic = pyaudio.PyAudio()
    try:
        devices = []
        for index in range(mic.get_device_count()):
            info = mic.get_device_info_by_index(index)
            if info.get("maxInputChannels", 0) > 0:
                devices.append((index, info.get("name", "未知设备")))
        return devices
    finally:
        mic.terminate()


def _select_input_device(mic, requested_index):
    devices = [
        mic.get_device_info_by_index(index)
        for index in range(mic.get_device_count())
    ]
    inputs = [info for info in devices if info.get("maxInputChannels", 0) > 0]

    def is_loopback(info):
        return any(word in str(info.get("name", "")).lower() for word in LOOPBACK_NAMES)

    if requested_index is not None:
        selected = next((info for info in inputs if info["index"] == requested_index), None)
        if selected is None:
            raise VoiceError(f"输入设备 {requested_index} 不存在或没有麦克风输入；可用 --list-input-devices 查看。")
    else:
        try:
            default = mic.get_default_input_device_info()
        except OSError:
            default = None
        if default and not is_loopback(default):
            selected = default
        else:
            physical = [info for info in inputs if not is_loopback(info)]
            named_mics = [
                info for info in physical
                if "microphone" in str(info.get("name", "")).lower()
                or "麦克风" in str(info.get("name", ""))
            ]
            selected = (named_mics or physical or [None])[0]
    if selected is None:
        raise VoiceError("没有找到可用的麦克风；请检查 macOS 输入设备及麦克风权限。")
    if is_loopback(selected):
        raise VoiceError(
            f"输入设备 {selected['index']}（{selected['name']}）是电脑声音回传设备；"
            "请用 --list-input-devices 查看并通过 --input-device 指定实体麦克风。"
        )
    return int(selected["index"]), str(selected.get("name", "未知设备"))


class VoiceStream:
    def __init__(self, device_index: Optional[int] = None, silence_ms: int = 800,
                 provider=None, model_dir=None):
        self.device_index = device_index
        self.silence_ms = silence_ms
        self.provider = provider
        self.model_dir = model_dir
        self.backend_label = ""
        self.sentences = queue.Queue(maxsize=MAX_PENDING_SENTENCES)
        self.stop_event = threading.Event()
        self._lifecycle_lock = threading.RLock()
        self.error = None
        self._mic = None
        self._stream = None
        self._recognition = None
        self._recognition_started = False
        self._thread = None

    def _set_error(self, message):
        if self.error is None:
            self.error = str(message)
        self.stop_event.set()

    def start(self):
        self.provider, config = recognition_settings(self.provider, self.model_dir)
        if self.provider == "sensevoice":
            self._start_local(config)
            return
        self.backend_label = "百炼 paraformer-realtime-v2"
        key, model, websocket_url = load_settings()
        dashscope, pyaudio, Recognition, RecognitionCallback, RecognitionResult = _dependencies()
        dashscope.api_key = key
        dashscope.base_websocket_api_url = websocket_url
        owner = self

        class Callback(RecognitionCallback):
            def __init__(self):
                self.seen_sentence_ids = set()

            def on_open(self):
                pass

            def on_close(self):
                pass

            def on_complete(self):
                pass

            def on_error(self, result):
                owner._set_error(getattr(result, "message", str(result)))

            def on_event(self, result):
                sentence = result.get_sentence()
                if not isinstance(sentence, dict) or not sentence.get("text"):
                    return
                if not RecognitionResult.is_sentence_end(sentence):
                    return
                text = sentence["text"].strip()
                if not text:
                    return
                begin_time = sentence.get("begin_time")
                request_id = result.get_request_id()
                identity = (request_id, begin_time) if begin_time is not None else None
                if identity is not None:
                    if identity in self.seen_sentence_ids:
                        return
                    self.seen_sentence_ids.add(identity)
                owner._put_sentence(text)

        try:
            recognition = Recognition(
                model=model,
                format="pcm",
                sample_rate=SAMPLE_RATE,
                semantic_punctuation_enabled=False,
                max_sentence_silence=self.silence_ms,
                heartbeat=True,
                callback=Callback(),
            )
            self._start_capture(pyaudio, recognition)
        except Exception as exc:
            self.close()
            raise VoiceError(f"无法启动麦克风或百炼识别：{exc}") from exc

    def _start_local(self, config):
        try:
            from local_voice import LocalRecognition
            self.backend_label = "本地 SenseVoiceSmall INT8（CPU）"
            recognition = LocalRecognition(config, self.silence_ms,
                                           self._put_sentence, self._set_error)
            self._start_capture(_audio_dependency(), recognition)
        except Exception as exc:
            self.close()
            raise VoiceError(f"无法启动本地 SenseVoice 识别：{exc}") from exc

    def _put_sentence(self, text):
        if not text or self.stop_event.is_set():
            return
        try:
            self.sentences.put_nowait(text)
        except queue.Full:
            self._set_error("待发送句子已超过 50 条；已停止录音，避免丢失或积压。")

    def _start_capture(self, pyaudio, recognition):
        with self._lifecycle_lock:
            if self.stop_event.is_set():
                return
            self._recognition = recognition
            self._open_capture(pyaudio)

    def _open_capture(self, pyaudio):
        if self.stop_event.is_set():
            self.close()
            return
        self._mic = pyaudio.PyAudio()
        self.device_index, device_name = _select_input_device(self._mic, self.device_index)
        print(f"语音识别：{self.backend_label}")
        print(f"录音输入：{device_name}（设备 {self.device_index}）")
        self._stream = self._mic.open(
            format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE, input=True,
            input_device_index=self.device_index, frames_per_buffer=FRAMES_PER_CHUNK,
        )
        if self.stop_event.is_set():
            self.close()
            return
        self._recognition.start()
        self._recognition_started = True
        self._thread = threading.Thread(target=self._feed_audio, daemon=True)
        self._thread.start()

    def _feed_audio(self):
        stream, recognition = self._stream, self._recognition
        try:
            while not self.stop_event.is_set():
                data = stream.read(FRAMES_PER_CHUNK, exception_on_overflow=False)
                if not self.stop_event.is_set():
                    recognition.send_audio_frame(data)
        except Exception as exc:
            if not self.stop_event.is_set():
                self._set_error(f"麦克风或语音连接中断：{exc}")

    def get_sentence(self, timeout=0.25):
        if self.error:
            raise VoiceError(self.error)
        try:
            text = self.sentences.get(timeout=timeout)
        except queue.Empty:
            if self.error:
                raise VoiceError(self.error)
            return None
        if self.error:
            raise VoiceError(self.error)
        return text

    def discard_pending(self):
        discarded = 0
        while True:
            try:
                self.sentences.get_nowait()
                discarded += 1
            except queue.Empty:
                return discarded

    def close(self):
        self.stop_event.set()
        with self._lifecycle_lock:
            self._close_resources()

    def _close_resources(self):
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        if self._recognition and self._recognition_started:
            try:
                self._recognition.stop()
            except Exception:
                pass
        self._recognition = None
        self._recognition_started = False
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._mic:
            self._mic.terminate()
            self._mic = None
