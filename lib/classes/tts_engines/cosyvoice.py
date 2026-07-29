import hashlib, os, sys, tempfile, threading
import numpy as np, regex as re, soundfile as sf, torch, torchaudio

from pathlib import Path
import logging

from lib import *
from lib.classes.tts_engines.common.utils import unload_tts, append_sentence2vtt
from lib.classes.tts_engines.common.audio_filters import detect_gender, trim_audio, normalize_audio, is_audio_data_valid

lock = threading.Lock()

# CosyVoice repo shipped inside the project root (./CosyVoice)
cosyvoice_repo_dir = os.path.join(Path(__file__).resolve().parents[3], 'CosyVoice')
cosyvoice_matcha_dir = os.path.join(cosyvoice_repo_dir, 'third_party', 'Matcha-TTS')

class CosyVoiceEngine:

    def __init__(self, session):
        try:
            self.session = session
            self.cache_dir = tts_dir
            self.tts_key = f"{self.session['tts_engine']}-{self.session['fine_tuned']}"
            self.tts_vc_key = default_vc_model.rsplit('/', 1)[-1]
            self.sentences_total_time = 0.0
            self.sentence_idx = 1
            self.params = {TTS_ENGINES['COSYVOICE']: {"registered_spk_ids": {}}}
            self.params[self.session['tts_engine']]['samplerate'] = models[self.session['tts_engine']][self.session['fine_tuned']]['samplerate']
            self.vtt_path = os.path.join(self.session['process_dir'], Path(self.session['final_name']).stem + '.vtt')
            self.resampler_cache = {}
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
                    model_path = models[self.session['tts_engine']][self.session['fine_tuned']]['repo']
                    local_dir = os.path.join(self.cache_dir, os.path.basename(model_path))
                    if os.path.isdir(local_dir):
                        model_path = local_dir
                    tts = self._load_api(self.tts_key, model_path, self.session['device'])
            self.tts = (loaded_tts.get(self.tts_key) or {}).get('engine', False)
            return self.tts
        except Exception as e:
            error = f'build() error: {e}'
            print(error)
            return False

    def _load_api(self, key, model_path, device):
        global lock
        try:
            if key in loaded_tts.keys():
                return loaded_tts[key]['engine']
            unload_tts(device, [self.tts_key, self.tts_vc_key])
            # keep modelscope downloads inside the project models directory
            os.environ.setdefault('MODELSCOPE_CACHE', self.cache_dir)
            for repo_path in [cosyvoice_repo_dir, cosyvoice_matcha_dir]:
                if repo_path not in sys.path:
                    sys.path.insert(0, repo_path)
            from cosyvoice.cli.cosyvoice import AutoModel
            with lock:
                fp16 = True if device == 'cuda' else False
                tts = AutoModel(model_dir=model_path, fp16=fp16)
                if tts:
                    # actual model samplerate may differ from the static default
                    self.params[self.session['tts_engine']]['samplerate'] = tts.sample_rate
                    loaded_tts[key] = {"engine": tts, "config": None}
                    msg = f'{model_path} Loaded!'
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

    def _get_resampler(self, orig_sr, target_sr):
        key = (orig_sr, target_sr)
        if key not in self.resampler_cache:
            self.resampler_cache[key] = torchaudio.transforms.Resample(
                orig_freq=orig_sr, new_freq=target_sr
            )
        return self.resampler_cache[key]

    def _resample_wav(self, wav_path, expected_sr):
        waveform, orig_sr = torchaudio.load(wav_path)
        if orig_sr == expected_sr and waveform.size(0) == 1:
            return wav_path
        if waveform.size(0) > 1:
            waveform = waveform.mean(dim=0, keepdim=True)
        if orig_sr != expected_sr:
            resampler = self._get_resampler(orig_sr, expected_sr)
            waveform = resampler(waveform)
        wav_tensor = waveform.squeeze(0)
        wav_numpy = wav_tensor.cpu().numpy()
        tmp_fh = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_path = tmp_fh.name
        tmp_fh.close()
        sf.write(tmp_path, wav_numpy, expected_sr, subtype="PCM_16")
        return tmp_path

    def _get_prompt_text(self, voice_path):
        # optional transcript of the voice sample stored next to it (same name, .txt)
        # enables the more accurate inference_zero_shot() path
        txt_path = os.path.splitext(voice_path)[0] + '.txt'
        if os.path.exists(txt_path):
            try:
                with open(txt_path, 'r', encoding='utf-8') as f:
                    prompt_text = f.read().strip()
                if prompt_text:
                    return prompt_text
            except Exception as e:
                logging.warning(f"CosyVoiceEngine._get_prompt_text: could not read {txt_path}: {e}")
        return ''

    def _register_speaker(self, tts, voice_path):
        # CosyVoice add_zero_shot_spk(): compute the speaker prompt features once
        # and reuse them for every sentence instead of recomputing per call
        settings = self.params[self.session['tts_engine']]
        if voice_path in settings['registered_spk_ids']:
            return settings['registered_spk_ids'][voice_path]
        try:
            spk_id = hashlib.md5(voice_path.encode()).hexdigest()[:16]
            prompt_wav = self._resample_wav(voice_path, settings['samplerate'])
            prompt_text = self._get_prompt_text(voice_path)
            if tts.add_zero_shot_spk(prompt_text, prompt_wav, spk_id):
                settings['registered_spk_ids'][voice_path] = spk_id
                logging.info(f"CosyVoiceEngine._register_speaker: speaker {spk_id} registered for {voice_path}")
                return spk_id
        except Exception as e:
            logging.warning(f"CosyVoiceEngine._register_speaker: fallback to per-sentence prompt: {e}")
        settings['registered_spk_ids'][voice_path] = ''
        return ''

    def convert_voice(self, source_wav, target_voice_path, output_path):
        # CosyVoice inference_vc(): speech-to-speech voice conversion (CosyVoice-300M only)
        try:
            tts = (loaded_tts.get(self.tts_key) or {}).get('engine', False)
            if tts and hasattr(tts, 'inference_vc'):
                settings = self.params[self.session['tts_engine']]
                source = self._resample_wav(source_wav, 16000)
                prompt = self._resample_wav(target_voice_path, settings['samplerate'])
                speech_chunks = [chunk['tts_speech'] for chunk in tts.inference_vc(source, prompt, stream=False)]
                if speech_chunks:
                    audio_tensor = torch.cat(speech_chunks, dim=-1)
                    torchaudio.save(output_path, audio_tensor, settings['samplerate'])
                    return output_path
            else:
                msg = 'inference_vc is only available with the CosyVoice-300M model!'
                print(msg)
        except Exception as e:
            error = f'convert_voice() error: {e}'
            print(error)
        return False

    def convert(self, sentence_number, sentence):
        try:
            speaker = None
            trim_audio_buffer = 0.004
            settings = self.params[self.session['tts_engine']]
            final_sentence_file = os.path.join(self.session['chapters_dir_sentences'], f'{sentence_number}.{default_audio_proc_format}')
            sentence = sentence.strip()

            logging.info(f"CosyVoiceEngine.convert: Processing sentence {sentence_number}: {sentence[:50]}{'...' if len(sentence) > 50 else ''}")
            logging.info(f"CosyVoiceEngine.convert: Language: {self.session['language']}")
            logging.info(f"CosyVoiceEngine.convert: Output file: {final_sentence_file}")

            settings['voice_path'] = (
                self.session['voice'] if self.session['voice'] is not None
                else os.path.join(self.session['custom_model_dir'], self.session['tts_engine'], self.session['custom_model'], 'ref.wav') if self.session['custom_model'] is not None
                else models[self.session['tts_engine']][self.session['fine_tuned']]['voice']
            )
            if settings['voice_path'] is not None:
                speaker = re.sub(r'\.wav$', '', os.path.basename(settings['voice_path']))
            tts = (loaded_tts.get(self.tts_key) or {}).get('engine', False)
            if tts:
                if sentence == TTS_SML['break']:
                    silence_time = int(np.random.uniform(0.3, 0.6) * 100) / 100
                    break_tensor = torch.zeros(1, int(settings['samplerate'] * silence_time))
                    self.audio_segments.append(break_tensor.clone())
                    logging.info(f"CosyVoiceEngine.convert: Created break silence for sentence {sentence_number}")
                    return True
                elif sentence == TTS_SML['pause']:
                    silence_time = int(np.random.uniform(1.0, 1.8) * 100) / 100
                    pause_tensor = torch.zeros(1, int(settings['samplerate'] * silence_time))
                    self.audio_segments.append(pause_tensor.clone())
                    logging.info(f"CosyVoiceEngine.convert: Created pause silence for sentence {sentence_number}")
                    return True
                else:
                    if sentence[-1].isalnum():
                        sentence = f'{sentence} —'
                    speed = float(self.session.get('speed') or default_engine_settings[TTS_ENGINES['COSYVOICE']]['speed'])
                    stream = bool(default_engine_settings[TTS_ENGINES['COSYVOICE']]['stream'])
                    text_frontend = bool(default_engine_settings[TTS_ENGINES['COSYVOICE']]['text_frontend'])
                    instruct_text = (self.session.get('instruct_text') or default_engine_settings[TTS_ENGINES['COSYVOICE']]['instruct_text']).strip()
                    spk_id = self._register_speaker(tts, settings['voice_path'])
                    prompt_wav = None
                    if not spk_id:
                        prompt_wav = self._resample_wav(settings['voice_path'], settings['samplerate'])
                    prompt_text = self._get_prompt_text(settings['voice_path'])
                    with torch.no_grad():
                        if instruct_text and hasattr(tts, 'inference_instruct2'):
                            # natural language style control taken from CosyVoice2/3
                            result = tts.inference_instruct2(
                                sentence, instruct_text, prompt_wav, zero_shot_spk_id=spk_id,
                                stream=stream, speed=speed, text_frontend=text_frontend
                            )
                        elif prompt_text and not spk_id:
                            # zero-shot cloning with transcript of the voice sample
                            result = tts.inference_zero_shot(
                                sentence, prompt_text, prompt_wav, zero_shot_spk_id=spk_id,
                                stream=stream, speed=speed, text_frontend=text_frontend
                            )
                        else:
                            # cross-lingual cloning, no transcript required
                            result = tts.inference_cross_lingual(
                                sentence, prompt_wav, zero_shot_spk_id=spk_id,
                                stream=stream, speed=speed, text_frontend=text_frontend
                            )
                        speech_chunks = [chunk['tts_speech'] for chunk in result]
                    audio_sentence = torch.cat(speech_chunks, dim=-1).squeeze(0) if speech_chunks else False
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
                            logging.error(f"CosyVoiceEngine.convert: {error}")
            else:
                error = f"convert() error: {self.session['tts_engine']} is None"
                print(error)
        except Exception as e:
            error = f'CosyVoiceEngine.convert(): {e}'
            logging.error(error, exc_info=True)
            raise ValueError(e)
        return False
