"""
Translation Manager for ebook2audiobook
Handles translation with temporary file storage and resume capabilities
"""

import os
import json
import logging
import tempfile
import shutil
from datetime import datetime
from pathlib import Path

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TranslationManager:
    """Manages translation process with temporary file storage and resume capabilities"""
    
    def __init__(self, session_dir, source_lang, target_lang, method='google'):
        """
        Initialize TranslationManager
        
        Args:
            session_dir (str): Path to session directory
            source_lang (str): Source language code
            target_lang (str): Target language code
            method (str): Translation method
        """
        self.session_dir = session_dir
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.method = method
        self.translation_dir = os.path.join(session_dir, 'translation_cache')
        self.metadata_file = os.path.join(self.translation_dir, 'translation_metadata.json')
        
        # Create translation directory
        os.makedirs(self.translation_dir, exist_ok=True)
        
        # Load or create metadata
        self.metadata = self._load_metadata()
        
    def _load_metadata(self):
        """Load translation metadata from file"""
        if os.path.exists(self.metadata_file):
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load translation metadata: {e}")
                return self._create_default_metadata()
        else:
            return self._create_default_metadata()
            
    def _create_default_metadata(self):
        """Create default metadata structure"""
        return {
            'source_lang': self.source_lang,
            'target_lang': self.target_lang,
            'method': self.method,
            'created_at': datetime.now().isoformat(),
            'last_updated': datetime.now().isoformat(),
            'chapters': {},
            'completed_chapters': [],
            'failed_chapters': [],
            'total_chapters': 0
        }
        
    def _save_metadata(self):
        """Save translation metadata to file"""
        self.metadata['last_updated'] = datetime.now().isoformat()
        try:
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(self.metadata, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save translation metadata: {e}")
            
    def save_translated_chapter(self, chapter_index, original_text, translated_text):
        """
        Save translated chapter to temporary file
        
        Args:
            chapter_index (int): Chapter index
            original_text (str): Original text
            translated_text (str): Translated text
        """
        logger.info(f"Saving translated chapter {chapter_index}")
        
        # Create chapter file
        chapter_file = os.path.join(self.translation_dir, f'chapter_{chapter_index}.json')
        chapter_data = {
            'index': chapter_index,
            'original': original_text,
            'translated': translated_text,
            'timestamp': datetime.now().isoformat()
        }
        
        try:
            with open(chapter_file, 'w', encoding='utf-8') as f:
                json.dump(chapter_data, f, ensure_ascii=False, indent=2)
                
            # Update metadata
            self.metadata['chapters'][str(chapter_index)] = {
                'file': f'chapter_{chapter_index}.json',
                'status': 'completed',
                'timestamp': datetime.now().isoformat()
            }
            
            if chapter_index not in self.metadata['completed_chapters']:
                self.metadata['completed_chapters'].append(chapter_index)
                
            # Remove from failed if it was there
            if chapter_index in self.metadata['failed_chapters']:
                self.metadata['failed_chapters'].remove(chapter_index)
                
            self._save_metadata()
            logger.info(f"Successfully saved translated chapter {chapter_index}")
            
        except Exception as e:
            logger.error(f"Failed to save translated chapter {chapter_index}: {e}")
            # Mark as failed
            if chapter_index not in self.metadata['failed_chapters']:
                self.metadata['failed_chapters'].append(chapter_index)
            self._save_metadata()
            
    def get_translated_chapter(self, chapter_index):
        """
        Get translated chapter from temporary file
        
        Args:
            chapter_index (int): Chapter index
            
        Returns:
            str: Translated text or None if not found
        """
        if str(chapter_index) in self.metadata['chapters']:
            chapter_info = self.metadata['chapters'][str(chapter_index)]
            if chapter_info['status'] == 'completed':
                chapter_file = os.path.join(self.translation_dir, chapter_info['file'])
                if os.path.exists(chapter_file):
                    try:
                        with open(chapter_file, 'r', encoding='utf-8') as f:
                            chapter_data = json.load(f)
                            return chapter_data['translated']
                    except Exception as e:
                        logger.error(f"Failed to load translated chapter {chapter_index}: {e}")
                        
        return None
        
    def mark_chapter_failed(self, chapter_index):
        """
        Mark chapter as failed
        
        Args:
            chapter_index (int): Chapter index
        """
        logger.warning(f"Marking chapter {chapter_index} as failed")
        
        if chapter_index not in self.metadata['failed_chapters']:
            self.metadata['failed_chapters'].append(chapter_index)
            
        # Remove from completed if it was there
        if chapter_index in self.metadata['completed_chapters']:
            self.metadata['completed_chapters'].remove(chapter_index)
            
        self._save_metadata()
        
    def is_chapter_completed(self, chapter_index):
        """
        Check if chapter is already translated
        
        Args:
            chapter_index (int): Chapter index
            
        Returns:
            bool: True if chapter is completed
        """
        return chapter_index in self.metadata['completed_chapters']
        
    def is_chapter_failed(self, chapter_index):
        """
        Check if chapter failed translation
        
        Args:
            chapter_index (int): Chapter index
            
        Returns:
            bool: True if chapter failed
        """
        return chapter_index in self.metadata['failed_chapters']
        
    def get_translation_progress(self):
        """
        Get translation progress
        
        Returns:
            dict: Progress information
        """
        total = self.metadata.get('total_chapters', 0)
        completed = len(self.metadata.get('completed_chapters', []))
        failed = len(self.metadata.get('failed_chapters', []))
        
        return {
            'total_chapters': total,
            'completed_chapters': completed,
            'failed_chapters': failed,
            'progress_percentage': (completed / total * 100) if total > 0 else 0
        }
        
    def set_total_chapters(self, total_chapters):
        """
        Set total number of chapters
        
        Args:
            total_chapters (int): Total number of chapters
        """
        self.metadata['total_chapters'] = total_chapters
        self._save_metadata()
        
    def create_translated_epub(self, original_epub_path, output_path):
        """
        Create translated EPUB from cached translations
        
        Args:
            original_epub_path (str): Path to original EPUB file
            output_path (str): Path for translated EPUB file
            
        Returns:
            str: Path to translated EPUB file
        """
        logger.info("Creating translated EPUB from cached translations")
        
        try:
            import ebooklib
            from ebooklib import epub
            
            # Load original EPUB
            book = epub.read_epub(original_epub_path)
            
            # Get all document items
            document_items = [item for item in book.get_items() if item.get_type() == ebooklib.ITEM_DOCUMENT]
            
            # Process each document item
            for i, item in enumerate(document_items):
                if i < len(self.metadata['completed_chapters']):
                    chapter_index = self.metadata['completed_chapters'][i]
                    translated_text = self.get_translated_chapter(chapter_index)
                    
                    if translated_text:
                        # Update item content with translated text
                        content = item.get_content().decode('utf-8')
                        # Remove XML declarations from raw HTML before processing
                        # This prevents XML declaration numbers from being converted to words
                        import re
                        xml_decl_pattern = re.compile(r'<\?xml[^>]*>', re.IGNORECASE)
                        content = xml_decl_pattern.sub('', content)
                        # This is a simplified approach - in practice, you'd want to
                        # properly map the translated text back to the HTML structure
                        item.set_content(translated_text.encode('utf-8'))
                        
            # Save translated EPUB
            epub.write_epub(output_path, book)
            logger.info(f"Translated EPUB saved to {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"Failed to create translated EPUB: {e}")
            raise
            
    def cleanup(self):
        """Clean up temporary translation files"""
        try:
            if os.path.exists(self.translation_dir):
                shutil.rmtree(self.translation_dir)
                logger.info("Cleaned up translation cache")
        except Exception as e:
            logger.error(f"Failed to clean up translation cache: {e}")

# Example usage
if __name__ == "__main__":
    # Example of how to use the TranslationManager
    manager = TranslationManager(
        session_dir="./test_session",
        source_lang="eng",
        target_lang="rus",
        method="google"
    )
    
    # Simulate translation process
    manager.set_total_chapters(5)
    
    # Save some translated chapters
    for i in range(5):
        if not manager.is_chapter_completed(i):
            original = f"Original text for chapter {i}"
            translated = f"Переведенный текст для главы {i}"
            manager.save_translated_chapter(i, original, translated)
            
    # Check progress
    progress = manager.get_translation_progress()
    print(f"Translation progress: {progress}")
    
    # Get a translated chapter
    chapter_0 = manager.get_translated_chapter(0)
    print(f"Chapter 0 translation: {chapter_0}")