import os
import sys
import types
import numpy as np
import librosa
import torchaudio

# pyannote.audio 3.1.1 / speechbrain 1.0.0 call the torchaudio backend API
# (set/get/list_audio_backend(s)) at import time, but new torchaudio (e.g. the
# Colab preinstalled build) removed all three. Restore them as no-ops
# ('soundfile' is what those libraries expect to see).
if not hasattr(torchaudio, 'set_audio_backend'):
    torchaudio.set_audio_backend = lambda *args, **kwargs: None
if not hasattr(torchaudio, 'get_audio_backend'):
    torchaudio.get_audio_backend = lambda *args, **kwargs: 'soundfile'
if not hasattr(torchaudio, 'list_audio_backends'):
    torchaudio.list_audio_backends = lambda *args, **kwargs: ['soundfile']

# pyannote also does `from torchaudio.backend.common import AudioMetaData`;
# new torchaudio dropped the whole torchaudio.backend module (the class now
# lives at torchaudio.AudioMetaData), so register a stub module for it.
try:
    import torchaudio.backend.common  # noqa: F401
except ImportError:
    _common = types.ModuleType('torchaudio.backend.common')
    _common.AudioMetaData = getattr(torchaudio, 'AudioMetaData', object)
    _backend = types.ModuleType('torchaudio.backend')
    _backend.common = _common
    torchaudio.backend = _backend
    sys.modules['torchaudio.backend'] = _backend
    sys.modules['torchaudio.backend.common'] = _common

from pyannote.audio import Model
from pyannote.audio.pipelines import VoiceActivityDetection
from lib.conf import tts_dir
from lib.models import default_voice_detection_model

class BackgroundDetector:

    def __init__(self, wav_file: str):
        self.wav_file   = wav_file
        model = Model.from_pretrained(default_voice_detection_model, cache_dir=tts_dir)
        self.pipeline = VoiceActivityDetection(segmentation=model)
        hyper_params = {
          # remove speech regions shorter than that many seconds.
          "min_duration_on": 0.0,
          # fill non-speech regions shorter than that many seconds.
          "min_duration_off": 0.0
        }
        try:
            # onset/offset activation thresholds (only supported by older segmentation models)
            self.pipeline.instantiate({**hyper_params, "onset": 0.5, "offset": 0.5})
        except Exception:
            # pyannote 3.x powerset models (e.g. segmentation-3.0) have no onset/offset hyper-parameters
            self.pipeline.instantiate(hyper_params)

    def detect(self, vad_ratio_thresh: float=0.05):
        diarization     = self.pipeline(self.wav_file)
        speech_segments = [(s.start, s.end) for s in diarization.get_timeline()]
        total_duration  = librosa.get_duration(path=self.wav_file)
        speech_time     = sum(end - start for start, end in speech_segments)
        non_speech_ratio = 1 - (speech_time / total_duration)
        status = non_speech_ratio > vad_ratio_thresh
        report = {
            'non_speech_ratio': non_speech_ratio,
            'background_detected': status
        }
        return status, report