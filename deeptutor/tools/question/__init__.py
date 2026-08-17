"""
Question Tools - question generation toolset

Provides question extraction helpers consumed by the question pipeline
(used by the BookEngine quiz block).
"""

from .question_extractor import extract_questions_from_paper

__all__ = [
    "extract_questions_from_paper",
]
