import os, sys, threading
import numpy as np, regex as re, torch, torchaudio

from pathlib import Path
import logging

from lib import *
from lib.classes.tts_engines.common.utils import unload_tts, append_sentence2vtt
from lib.classes.tts_engines.common.audio_filters import trim_audio, is_audio_data_valid

lock = threading.Lock()

# MOSS-TTS-Nano repo shipped inside the project root (./MOSS-TTS-Nano)
mosstts_repo_dir = os.path.join(Path(__file__).resolve().parents[3], 'MOSS-TTS-Nano')

class MossTtsNanoEngine:
    # MOSS-TTS-Nano 0.1B engine (OpenMOSS) running on the ONNX CPU runtime.
    # Multilingual (20 languages), zero-shot voice cloning from a reference wav,
    # 48 kHz output, no GPU required. ONNX assets are auto-downloaded into
    # MOSS-TTS-Nano/models on first use.

    def __init__(self, session):
        try:
            self.session = session
            self.cache_dir = tts_dir
            self.tts_key = f"{self.session['tts_engine']}-{self.session['fine_tuned']}"
            self.tts_vc_key = default_vc_model.rsplit('/', 1)[-1]
            self.sentences_total_time = 0.0
            self.sentence_idx = 1
            self.params = {TTS_ENGINES['MOSSTTSNANO']: {}}
            self.params[self.session['tts_engine']]['samplerate'] = models[self.session['tts_engine']][self.session['fine_tuned']]['samplerate']
            self.vtt_path = os.path.join(self.session['process_dir'], Path(self.session['final_name']).stem + '.vtt')
            self.audio_segments = []
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
                return loaded_tts[key]['engine']
            unload_tts(device, [self.tts_key, self.tts_vc_key])
            os.environ.setdefault('HF_HOME', self.cache_dir)
            if mosstts_repo_dir not in sys.path:
                sys.path.insert(0, mosstts_repo_dir)
            from onnx_tts_runtime import OnnxTtsRuntime
            with lock:
                execution_provider = 'cuda' if device == 'cuda' else 'cpu'
                try:
                    tts = OnnxTtsRuntime(
                        thread_count=max(1, (os.cpu_count() or 4) - 1),
                        execution_provider=execution_provider,
                        output_dir=self.session['process_dir']
                    )
                except Exception as cuda_error:
                    if execution_provider == 'cuda':
                        logging.warning(f'MossTtsNanoEngine: cuda execution provider failed ({cuda_error}), falling back to cpu')
                        tts = OnnxTtsRuntime(
                            thread_count=max(1, (os.cpu_count() or 4) - 1),
                            execution_provider='cpu',
                            output_dir=self.session['process_dir']
                        )
                    else:
                        raise
                if tts:
                    # sample rate comes from the MOSS audio tokenizer codec (48 kHz)
                    self.params[self.session['tts_engine']]['samplerate'] = int(tts.codec_meta['codec_config']['sample_rate'])
                    loaded_tts[key] = {"engine": tts, "config": None}
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

    def convert(self, sentence_number, sentence):
        try:
            trim_audio_buffer = 0.004
            settings = self.params[self.session['tts_engine']]
            final_sentence_file = os.path.join(self.session['chapters_dir_sentences'], f'{sentence_number}.{default_audio_proc_format}')
            sentence = sentence.strip()

            logging.info(f"MossTtsNanoEngine.convert: Processing sentence {sentence_number}: {sentence[:50]}{'...' if len(sentence) > 50 else ''}")
            logging.info(f"MossTtsNanoEngine.convert: Language: {self.session['language']}")
            logging.info(f"MossTtsNanoEngine.convert: Output file: {final_sentence_file}")

            settings['voice_path'] = (
                self.session['voice'] if self.session['voice'] is not None
                else models[self.session['tts_engine']][self.session['fine_tuned']]['voice']
            )
            tts = (loaded_tts.get(self.tts_key) or {}).get('engine', False)
            if tts:
                if sentence == TTS_SML['break']:
                    silence_time = int(np.random.uniform(0.3, 0.6) * 100) / 100
                    break_tensor = torch.zeros(1, int(settings['samplerate'] * silence_time))
                    self.audio_segments.append(break_tensor.clone())
                    logging.info(f"MossTtsNanoEngine.convert: Created break silence for sentence {sentence_number}")
                    return True
                elif sentence == TTS_SML['pause']:
                    silence_time = int(np.random.uniform(1.0, 1.8) * 100) / 100
                    pause_tensor = torch.zeros(1, int(settings['samplerate'] * silence_time))
                    self.audio_segments.append(pause_tensor.clone())
                    logging.info(f"MossTtsNanoEngine.convert: Created pause silence for sentence {sentence_number}")
                    return True
                else:
                    defaults = default_engine_settings[TTS_ENGINES['MOSSTTSNANO']]
                    # reference wav (voice cloning) or a built-in preset name
                    voice_path = settings['voice_path']
                    prompt_audio_path = voice_path if voice_path is not None and os.path.isfile(voice_path) else None
                    builtin_voice = None if prompt_audio_path else voice_path
                    tmp_wav = os.path.join(self.session['process_dir'], f'moss_{sentence_number}.wav')
                    with lock:
                        # WeTextProcessing (pynini) is optional and hard to install on
                        # Windows: the built-in robust normalizer is enough here
                        result = tts.synthesize(
                            text=sentence,
                            voice=builtin_voice,
                            prompt_audio_path=prompt_audio_path,
                            output_audio_path=tmp_wav,
                            max_new_frames=defaults['max_new_frames'],
                            voice_clone_max_text_tokens=defaults['voice_clone_max_text_tokens'],
                            enable_wetext=False,
                            enable_normalize_tts_text=True
                        )
                    audio_sentence = result.get('waveform') if isinstance(result, dict) else None
                    settings['samplerate'] = int(result.get('sample_rate', settings['samplerate'])) if isinstance(result, dict) else settings['samplerate']
                    if os.path.exists(tmp_wav):
                        os.remove(tmp_wav)
                    if is_audio_data_valid(audio_sentence):
                        sourceTensor = self._tensor_type(audio_sentence)
                        # (samples, channels) stereo 48 kHz -> mono (1, samples)
                        if sourceTensor.dim() == 2:
                            sourceTensor = sourceTensor.mean(dim=-1)
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
                            logging.error(f"MossTtsNanoEngine.convert: {error}")
            else:
                error = f"convert() error: {self.session['tts_engine']} is None"
                print(error)
        except Exception as e:
            error = f'MossTtsNanoEngine.convert(): {e}'
            logging.error(error, exc_info=True)
            raise ValueError(e)
        return False
