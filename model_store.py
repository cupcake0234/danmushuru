"""Install the pinned SenseVoice files used by Coopanion, without extra tools."""

from dataclasses import dataclass
import hashlib
from http.client import HTTPException
import os
from pathlib import Path
import threading
import time
from urllib.request import Request, urlopen

from project_paths import data_dir


MODEL_NAME = "sensevoice-small-int8-2024-07-17"


@dataclass(frozen=True)
class ModelFile:
    name: str
    size: int
    sha256: str


# Sizes, digests and source order match Coopanion's desktop-pet runtime/store.ts.
MODEL_FILES = (
    ModelFile("model.int8.onnx", 239_233_841,
              "c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51"),
    ModelFile("tokens.txt", 315_894,
              "f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc"),
)
MODEL_SOURCES = (
    ("魔搭 ModelScope", "https://modelscope.cn/models/pengzhendong/"
     "sherpa-onnx-sense-voice-zh-en-ja-ko-yue/resolve/master/"),
    ("Hugging Face", "https://huggingface.co/csukuangfj/"
     "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/resolve/main/"),
)
MODEL_BYTES = sum(item.size for item in MODEL_FILES)
_install_lock = threading.Lock()


class ModelInstallError(RuntimeError):
    pass


class ModelInstallCancelled(ModelInstallError):
    pass


def managed_model_dir():
    return data_dir() / "models" / MODEL_NAME


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise ModelInstallCancelled("模型安装已取消，可重新点击安装。")


def _valid_file(path, spec, cancel):
    if not path.is_file() or path.stat().st_size != spec.size:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            _check_cancel(cancel)
            digest.update(chunk)
    return digest.hexdigest() == spec.sha256


def install_model(target=None, *, on_progress=None, cancel=None, opener=None):
    """Return a verified install directory; never publish an incomplete file.

    Progress receives (completed_bytes, total_bytes, detail). Verified files from
    an earlier attempt are reused. Only a successfully checked partial file is
    renamed over its final destination.
    """
    if not _install_lock.acquire(blocking=False):
        raise ModelInstallError("已有模型正在安装，请等待当前任务完成。")
    try:
        return _install(target or managed_model_dir(), on_progress, cancel, opener or urlopen)
    except ModelInstallError:
        raise
    except OSError as exc:
        raise ModelInstallError(f"模型安装失败，请检查网络和安装目录的可用空间：{exc}") from exc
    finally:
        _install_lock.release()


def _install(target, on_progress, cancel, opener):
    target = Path(target).expanduser().resolve()
    total = sum(spec.size for spec in MODEL_FILES)
    last_update = 0.0

    def report(done, detail, force=False):
        nonlocal last_update
        now = time.monotonic()
        if on_progress and (force or now - last_update >= 0.1):
            last_update = now
            on_progress(done, total, detail)

    _check_cancel(cancel)
    target.mkdir(parents=True, exist_ok=True)
    before = 0
    for spec in MODEL_FILES:
        _check_cancel(cancel)
        destination = target / spec.name
        report(before, f"正在校验 {spec.name}…", True)
        if _valid_file(destination, spec, cancel):
            before += spec.size
            report(before, f"已就绪：{spec.name}", True)
            continue
        partial = target / (spec.name + ".partial")
        errors = []
        for source, base in MODEL_SOURCES:
            _check_cancel(cancel)
            detail = f"正在从{source}下载 {spec.name}"
            report(before, detail, True)
            try:
                request = Request(base + spec.name, headers={"User-Agent": "DanmuLive/0.3"})
                digest = hashlib.sha256()
                received = 0
                with opener(request, timeout=20) as response, partial.open("wb") as output:
                    while True:
                        _check_cancel(cancel)
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        received += len(chunk)
                        if received > spec.size:
                            raise ModelInstallError("下载文件大小不匹配。")
                        output.write(chunk)
                        digest.update(chunk)
                        report(before + received, detail)
                _check_cancel(cancel)
                if received != spec.size or digest.hexdigest() != spec.sha256:
                    raise ModelInstallError("下载文件未通过大小或 SHA-256 校验。")
                os.replace(partial, destination)
                break
            except ModelInstallCancelled:
                raise
            except (OSError, HTTPException, ValueError, ModelInstallError) as exc:
                errors.append(f"{source}：{exc}")
            finally:
                partial.unlink(missing_ok=True)
        else:
            raise ModelInstallError(f"{spec.name} 下载失败，可重新点击安装。\n" + "\n".join(errors))
        before += spec.size
        report(before, f"已校验：{spec.name}", True)
    _check_cancel(cancel)
    report(total, "模型已安装并通过 SHA-256 校验。", True)
    return target
