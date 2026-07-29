import os
import logging

from lib.models import TTS_ENGINES

class TTSManager:
    def __init__(self, session):   
        self.session = session
        self.tts = None
        self._build()
 
    def _build(self):
        if self.session['tts_engine'] in TTS_ENGINES.values():
            # Check if the tts_engine is one of the supported engines
            supported_engines = [TTS_ENGINES['XTTSv2'], TTS_ENGINES['BARK'], TTS_ENGINES['VITS'], TTS_ENGINES['FAIRSEQ'], TTS_ENGINES['TACOTRON2'], TTS_ENGINES['YOURTTS']]
            if self.session['tts_engine'] in supported_engines:
                from lib.classes.tts_engines.coqui import Coqui
                self.tts = Coqui(self.session)
            elif self.session['tts_engine'] == TTS_ENGINES['COSYVOICE']:
                from lib.classes.tts_engines.cosyvoice import CosyVoiceEngine
                self.tts = CosyVoiceEngine(self.session)
            elif self.session['tts_engine'] == TTS_ENGINES['KOKORO']:
                from lib.classes.tts_engines.kokoro import KokoroEngine
                self.tts = KokoroEngine(self.session)
            elif self.session['tts_engine'] == TTS_ENGINES['MOSSTTSNANO']:
                from lib.classes.tts_engines.mosstts_nano import MossTtsNanoEngine
                self.tts = MossTtsNanoEngine(self.session)
            #elif self.session['tts_engine'] in [TTS_ENGINES['NEW_TTS']]:
            #    from lib.classes.tts_engines.new_tts import NewTts
            #    self.tts = NewTts(self.session)
            if self.tts:
                return True
            else:
                error = 'TTS engine could not be created!'
                print(error)
        else:
            print('Other TTS engines coming soon!')
        return False

    def convert_sentence2audio(self, sentence_number, sentence):
        try:
            logging.info(f"TTSManager.convert_sentence2audio: Processing sentence {sentence_number}")
            logging.info(f"TTSManager.convert_sentence2audio: Sentence text: {sentence[:50]}{'...' if len(sentence) > 50 else ''}")
            logging.info(f"TTSManager.convert_sentence2audio: TTS engine: {self.session['tts_engine']}")
            
            if self.session['tts_engine'] in TTS_ENGINES.values() and self.tts is not None:
                result = self.tts.convert(sentence_number, sentence)
                logging.info(f"TTSManager.convert_sentence2audio: TTS convert result for sentence {sentence_number}: {result}")
                return result
            else:
                print('Other TTS engines coming soon!')    
        except Exception as e:
            error = f'convert_sentence2audio(): {e}'
            logging.error(f"TTSManager.convert_sentence2audio: Exception occurred: {error}", exc_info=True)
            raise ValueError(e)
        return False