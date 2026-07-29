import os, threading
import numpy as np, regex as re, torch, torchaudio

from pathlib import Path
import logging

from lib import *
from lib.classes.tts_engines.common.utils import unload_tts, append_sentence2vtt
from lib.classes.tts_engines.common.audio_filters import trim_audio, is_audio_data_valid
from lib.lang import language_tts

lock = threading.Lock()

class KokoroEngine:
    # Kokoro-82M engine ported from the audiblez project (KPipeline based).
    # Lightweight named-voice TTS, no voice cloning: the "voice" is a preset id
    # like af_heart where the first letter selects the language pipeline.

    def __init__(self, session):
        try:
            self.session = session
            self.cache_dir = tts_dir
            self.tts_key = f"{self.session['tts_engine']}-{self.session['fine_tuned']}"
            self.tts_vc_key = default_vc_model.rsplit('/', 1)[-1]
            self.sentences_total_time = 0.0
            self.sentence_idx = 1
            self.params = {TTS_ENGINES['KOKORO']: {}}
            self.params[self.session['tts_engine']]['samplerate'] = models[self.session['tts_engine']][self.session['fine_tuned']]['samplerate']
            self.vtt_path = os.path.join(self.session['process_dir'], Path(self.session['final_name']).stem + '.vtt')
            self.audio_segments = []
            self.lang_code = language_tts.get(TTS_ENGINES['KOKORO'], {}).get(self.session['language'], 'a')
            self._build()
        except Exception as e:
            error = f'__init__() error: {e}'
            print(error)

    def _build(self):
        try:
            tts = (loaded_tts.get(self.tts_key) or {}).get('engine', False)
            if not tts:
                if self.session['custom_model'] is not None:
                    msg = f"{self.session['tts_engine']} custom model not implemented yet!"
                    print(msg)
                    return False
                else:
                    msg = f"Loading TTS {self.session['tts_engine']} model, it takes a while, please be patient..."
                    print(msg)
                    tts = self._load_api(self.tts_key, self.session['device'])
            self.tts = (loaded_tts.get(self.tts_key) or {}).get('engine', False)
            return self.tts
        except Exception as e:
            error = f'build() error: {e}'
            print(error)
            return False

    def _load_api(self, key, device):
        global lock
        try:
            if key in loaded_tts.keys():
                # pipeline is language specific: rebuild when the language changed
                if (loaded_tts[key].get('config') or {}).get('lang_code') == self.lang_code:
                    return loaded_tts[key]['engine']
                del loaded_tts[key]
            unload_tts(device, [self.tts_key, self.tts_vc_key])
            os.environ.setdefault('HF_HOME', self.cache_dir)
            from kokoro import KPipeline
            with lock:
                tts = KPipeline(lang_code=self.lang_code)
                if tts:
                    loaded_tts[key] = {"engine": tts, "config": {"lang_code": self.lang_code}}
                    msg = f"{models[self.session['tts_engine']][self.session['fine_tuned']]['repo']} Loaded!"
                    print(msg)
                    return tts
                else:
                    error = 'TTS engine could not be created!'
                    print(error)
        except Exception as e:
            error = f'_load_api() error: {e}'
            print(error)
        return False

    def _tensor_type(self, audio_data):
        if isinstance(audio_data, torch.Tensor):
            return audio_data
        elif isinstance(audio_data, np.ndarray):
            return torch.from_numpy(audio_data).float()
        elif isinstance(audio_data, list):
            return torch.tensor(audio_data, dtype=torch.float32)
        else:
            raise TypeError(f"Unsupported type for audio_data: {type(audio_data)}")

    def _get_voice(self):
        # session['voice'] may hold a Kokoro preset id; anything else (wav path, None)
        # falls back to the first preset matching the language letter, then af_heart
        voices = default_engine_settings[TTS_ENGINES['KOKORO']]['voices']
        voice = self.session.get('voice')
        if voice in voices.values():
            return voice
        if voice in voices.keys():
            return voices[voice]
        for preset in voices.values():
            if preset.startswith(self.lang_code):
                return preset
        return models[self.session['tts_engine']][self.session['fine_tuned']]['voice']

    def convert(self, sentence_number, sentence):
        try:
            trim_audio_buffer = 0.004
            settings = self.params[self.session['tts_engine']]
            final_sentence_file = os.path.join(self.session['chapters_dir_sentences'], f'{sentence_number}.{default_audio_proc_format}')
            sentence = sentence.strip()

            logging.info(f"KokoroEngine.convert: Processing sentence {sentence_number}: {sentence[:50]}{'...' if len(sentence) > 50 else ''}")
            logging.info(f"KokoroEngine.convert: Language: {self.session['language']}")
            logging.info(f"KokoroEngine.convert: Output file: {final_sentence_file}")

            tts = (loaded_tts.get(self.tts_key) or {}).get('engine', False)
            if tts:
                if sentence == TTS_SML['break']:
                    silence_time = int(np.random.uniform(0.3, 0.6) * 100) / 100
                    break_tensor = torch.zeros(1, int(settings['samplerate'] * silence_time))
                    self.audio_segments.append(break_tensor.clone())
                    logging.info(f"KokoroEngine.convert: Created break silence for sentence {sentence_number}")
                    return True
                elif sentence == TTS_SML['pause']:
                    silence_time = int(np.random.uniform(1.0, 1.8) * 100) / 100
                    pause_tensor = torch.zeros(1, int(settings['samplerate'] * silence_time))
                    self.audio_segments.append(pause_tensor.clone())
                    logging.info(f"KokoroEngine.convert: Created pause silence for sentence {sentence_number}")
                    return True
                else:
                    if sentence[-1].isalnum():
                        sentence = f'{sentence} —'
                    voice = self._get_voice()
                    speed = float(self.session.get('speed') or default_engine_settings[TTS_ENGINES['KOKORO']]['speed'])
                    split_pattern = default_engine_settings[TTS_ENGINES['KOKORO']]['split_pattern']
                    chunks = []
                    with torch.no_grad():
                        # KPipeline yields (graphemes, phonemes, audio) per chunk (audiblez pattern)
                        for gs, ps, audio in tts(sentence, voice=voice, speed=speed, split_pattern=split_pattern):
                            if audio is not None:
                                chunks.append(self._tensor_type(audio))
                    audio_sentence = torch.cat(chunks, dim=-1) if chunks else False
                    if is_audio_data_valid(audio_sentence):
                        sourceTensor = self._tensor_type(audio_sentence)
                        audio_tensor = sourceTensor.clone().detach().unsqueeze(0).cpu()
                        if sentence[-1].isalnum() or sentence[-1] == '—':
                            audio_tensor = trim_audio(audio_tensor.squeeze(), settings['samplerate'], 0.003, trim_audio_buffer).unsqueeze(0)
                        self.audio_segments.append(audio_tensor)
                        if not re.search(r'\w$', sentence, flags=re.UNICODE):
                            silence_time = int(np.random.uniform(0.3, 0.6) * 100) / 100
                            break_tensor = torch.zeros(1, int(settings['samplerate'] * silence_time))
                            self.audio_segments.append(break_tensor.clone())
                        if self.audio_segments:
                            audio_tensor = torch.cat(self.audio_segments, dim=-1)
                            start_time = self.sentences_total_time
                            duration = audio_tensor.shape[-1] / settings['samplerate']
                            end_time = start_time + duration
                            self.sentences_total_time = end_time
                            sentence_obj = {
                                "start": start_time,
                                "end": end_time,
                                "text": sentence,
                                "resume_check": self.sentence_idx
                            }
                            self.sentence_idx = append_sentence2vtt(sentence_obj, self.vtt_path)
                            if self.sentence_idx:
                                torchaudio.save(final_sentence_file, audio_tensor, settings['samplerate'], format=default_audio_proc_format)
                                del audio_tensor
                        self.audio_segments = []
                        if os.path.exists(final_sentence_file):
                            return True
                        else:
                            error = f"Cannot create {final_sentence_file}"
                            print(error)
                            logging.error(f"KokoroEngine.convert: {error}")
            else:
                error = f"convert() error: {self.session['tts_engine']} is None"
                print(error)
        except Exception as e:
            error = f'KokoroEngine.convert(): {e}'
            logging.error(error, exc_info=True)
            raise ValueError(e)
        return False
