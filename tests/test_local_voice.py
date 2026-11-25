"""Utterance boundaries and worker lifecycle without a microphone or network."""

import queue
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from local_voice import LocalRecognition, UtteranceSegmenter
from voice import VoiceStream


SILENCE = bytes(640)
SPEECH = (np.sin(np.arange(320) * 0.15) * 6000).astype("<i2").tobytes()


class SegmenterTests(unittest.TestCase):
    def feed(self, segmenter, frame, count):
        return [pcm for _ in range(count) if (pcm := segmenter.push(frame)) is not None]

    def test_silence_and_short_clicks_do_not_trigger_recognition(self):
        segmenter = UtteranceSegmenter(silence_ms=500)
        self.assertEqual(self.feed(segmenter, SILENCE, 200), [])
        self.assertEqual(self.feed(segmenter, SPEECH, 5), [])
        self.assertEqual(self.feed(segmenter, SILENCE, 100), [])

    def test_retains_onset_and_emits_once_after_configured_silence(self):
        segmenter = UtteranceSegmenter(silence_ms=500)
        self.feed(segmenter, SILENCE, 50)
        self.assertEqual(self.feed(segmenter, SPEECH, 30), [])
        self.assertEqual(self.feed(segmenter, SILENCE, 24), [])
        result = self.feed(segmenter, SILENCE, 1)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].startswith(SILENCE * 7 + SPEECH * 9))
        self.assertTrue(result[0].endswith(SILENCE * 5))
        self.assertEqual(self.feed(segmenter, SILENCE, 100), [])

    def test_short_pause_remains_one_sentence(self):
        segmenter = UtteranceSegmenter(silence_ms=800)
        for frame, count in ((SPEECH, 25), (SILENCE, 15), (SPEECH, 25)):
            self.assertEqual(self.feed(segmenter, frame, count), [])
        self.assertEqual(len(self.feed(segmenter, SILENCE, 40)), 1)

    def test_long_speech_is_bounded_without_losing_continuation(self):
        segmenter = UtteranceSegmenter(silence_ms=500)
        results = self.feed(segmenter, SPEECH, 800)
        results += self.feed(segmenter, SILENCE, 25)
        self.assertEqual(len(results), 2)
        self.assertLessEqual(max(map(len, results)), 15 * 16000 * 2)
        self.assertEqual(sum(result.count(SPEECH) for result in results), 800)


class LocalWorkerTests(unittest.TestCase):
    def make_engine(self, recognizer):
        self.sentences = queue.Queue()
        self.errors = queue.Queue()
        with patch("local_voice.create_recognizer", return_value=recognizer):
            return LocalRecognition({}, 500, self.sentences.put, self.errors.put)

    def test_decodes_ordered_sentences_and_normalizes_pcm(self):
        stream = SimpleNamespace(accept_waveform=Mock(), result=SimpleNamespace(text="<|zh|>测试。"))
        recognizer = SimpleNamespace(create_stream=Mock(return_value=stream), decode_stream=Mock())
        engine = self.make_engine(recognizer)
        engine.start()
        try:
            pcm = SPEECH * 30 + SILENCE * 25
            # The audio source is allowed to hand us arbitrary byte boundaries.
            for at in range(0, len(pcm), 137):
                engine.send_audio_frame(pcm[at:at + 137])
            self.assertEqual(self.sentences.get(timeout=2), "测试。")
            rate, samples = stream.accept_waveform.call_args.args
            self.assertEqual(rate, 16000)
            self.assertEqual(samples.dtype, np.float32)
            self.assertLessEqual(float(np.max(np.abs(samples))), 1)
            self.assertTrue(self.errors.empty())
        finally:
            engine.stop()

    def test_stopping_during_inference_discards_late_result(self):
        entered, release = threading.Event(), threading.Event()
        stream = SimpleNamespace(accept_waveform=Mock(), result=SimpleNamespace(text="不应发送"))

        def decode(_stream):
            entered.set()
            release.wait(3)

        engine = self.make_engine(SimpleNamespace(create_stream=lambda: stream, decode_stream=decode))
        engine.start()
        engine.send_audio_frame(SPEECH * 30 + SILENCE * 25)
        self.assertTrue(entered.wait(2))
        engine.stopped.set()
        release.set()
        engine.stop()
        self.assertTrue(self.sentences.empty())

    def test_decode_failure_reports_error(self):
        stream = SimpleNamespace(accept_waveform=Mock())
        engine = self.make_engine(SimpleNamespace(create_stream=lambda: stream,
                                                 decode_stream=Mock(side_effect=RuntimeError("broken"))))
        engine.start()
        try:
            engine.send_audio_frame(SPEECH * 30 + SILENCE * 25)
            self.assertIn("broken", self.errors.get(timeout=2))
        finally:
            engine.stop()

    def test_overload_stops_capture_instead_of_growing_queue(self):
        engine = self.make_engine(Mock())
        for _ in range(5):
            engine.send_audio_frame(SPEECH * 30 + SILENCE * 25)
        self.assertTrue(engine.stopped.is_set())
        self.assertIn("积压", self.errors.get_nowait())
        engine.stop()

    def test_closed_voice_stream_does_not_open_microphone_after_model_load(self):
        stream = VoiceStream(provider="sensevoice")
        audio, recognizer = Mock(), Mock()
        stream.close()
        stream._start_capture(audio, recognizer)
        audio.PyAudio.assert_not_called()
        recognizer.start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
