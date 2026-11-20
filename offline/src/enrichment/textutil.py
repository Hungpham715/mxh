"""Sentence splitting with character offsets, for evidence extraction.

Naive splitter tuned for scientific abstracts: split after [.!?] followed by whitespace.
Known limitations (accepted, documented): decimals inside names ("Phi-1.5") and abbreviations
("et al.") create extra boundaries. Evidence text always stays a verbatim substring of the
abstract, so downstream audit is unaffected — only the sentence framing can be imperfect.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# The delimiter is a sentence-ending punctuation followed by whitespace. re.split with a
# capture group keeps the delimiters so offsets can be rebuilt exactly.
_DELIMITER = re.compile(r"((?<=[.!?])\s+)")


@dataclass(frozen=True)
class Sentence:
    index: int
    text: str
    start: int  # inclusive offset in the original text
    end: int    # exclusive offset in the original text


def split_sentences(text: str) -> list[Sentence]:
    """Split text into sentences with exact offsets. Never returns empty sentences."""
    parts = _DELIMITER.split(text)
    sentences: list[Sentence] = []
    cursor = 0
    for part in parts:
        length = len(part)
        is_delimiter = bool(_DELIMITER.fullmatch(part))
        if not is_delimiter and part.strip():
            sentences.append(Sentence(index=len(sentences), text=part.strip(),
                                      start=cursor, end=cursor + length))
        cursor += length
    return sentences


def sentence_at(sentences: list[Sentence], position: int) -> Sentence | None:
    """Return the sentence containing the given character offset (linear scan; abstracts are short)."""
    for sentence in sentences:
        if sentence.start <= position < sentence.end:
            return sentence
    return None
