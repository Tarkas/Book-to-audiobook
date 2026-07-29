#!/usr/bin/env python3
"""
Custom exceptions for the translation module.
"""

class TranslationError(Exception):
    """Base exception for translation errors."""
    pass

class TranslationFailedError(TranslationError):
    """Exception raised when translation fails."""
    def __init__(self, message, original_text=None, source_lang=None, target_lang=None):
        super().__init__(message)
        self.original_text = original_text
        self.source_lang = source_lang
        self.target_lang = target_lang

class RepetitiveContentError(TranslationError):
    """Exception raised when repetitive content is detected."""
    def __init__(self, message, content=None, count=None):
        super().__init__(message)
        self.content = content
        self.count = count