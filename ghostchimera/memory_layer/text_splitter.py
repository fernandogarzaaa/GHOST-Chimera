"""Recursive character text splitting with overlap (LangChain-inspired).

Splits documents into chunks of at most ``chunk_size`` characters, preferring
separator boundaries in order (paragraphs, lines, words, characters), with a
trailing overlap window so sentence context survives chunk boundaries.

Deliberately dependency-free (stdlib only): no ``langchain_text_splitters``,
no embeddings, no vector store. The overlap default (~10% of the default
ingestion chunk size) keeps recall stable while bounding index growth.

Usage::

    from ghostchimera.memory_layer.text_splitter import RecursiveCharacterSplitter

    splitter = RecursiveCharacterSplitter(chunk_size=2000, chunk_overlap=200)
    chunks = splitter.split_text(document)
    for chunk, start in splitter.split_with_spans(document):
        ...
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_SEPARATORS: tuple[str, ...] = ("\n\n", "\n", " ", "")


@dataclass
class RecursiveCharacterSplitter:
    """Split text recursively on separators, merging with overlap.

    Splitting is lossless: every emitted chunk (minus its overlap head) is
    an exact substring of the input, so ``start`` offsets are exact.

    Parameters
    ----------
    chunk_size:
        Maximum characters per chunk. Must be positive.
    chunk_overlap:
        Characters of trailing context repeated at the start of the next
        chunk. Must be smaller than ``chunk_size``; ``0`` disables overlap.
    separators:
        Tried in order; the first separator present in a span wins. An empty
        string means character-level splitting, exactly like
        ``RecursiveCharacterTextSplitter``.
    """

    chunk_size: int = 2000
    chunk_overlap: int = 200
    separators: tuple[str, ...] = field(default_factory=lambda: DEFAULT_SEPARATORS)

    def __post_init__(self) -> None:
        if self.chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if not 0 <= self.chunk_overlap < self.chunk_size:
            raise ValueError("chunk_overlap must satisfy 0 <= overlap < chunk_size")
        if not self.separators:
            raise ValueError("separators must not be empty")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def split_text(self, text: str) -> list[str]:
        """Split *text* into chunks of at most ``chunk_size`` characters."""
        return [chunk for chunk, _ in self.split_with_spans(text)]

    def split_with_spans(self, text: str) -> list[tuple[str, int]]:
        """Split *text* into ``(chunk, start_offset)`` pairs.

        ``start_offset`` is where the chunk's *new* (non-overlapping) content
        begins, so callers can record provenance. Blank input yields ``[]``.
        """
        text = text.strip()
        if not text:
            return []
        if len(text) <= self.chunk_size:
            return [(text, 0)]
        return self._merge(self._split_recursively(text))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _split_recursively(self, text: str, sep_from: int = 0) -> list[str]:
        """Losslessly split on the first separator at/after ``sep_from``.

        Pieces concatenate back to *text* (up to stripped trailing
        whitespace), so downstream offsets stay exact. Oversized pieces
        recurse onto the *next* separator, guaranteeing termination.
        """
        for index in range(sep_from, len(self.separators)):
            separator = self.separators[index]
            if not separator:
                return [text[i : i + self.chunk_size] for i in range(0, len(text), self.chunk_size)]
            if separator not in text:
                continue
            parts = text.split(separator)
            pieces = [part + separator for part in parts[:-1]]
            if parts[-1]:
                pieces.append(parts[-1])
            merged: list[str] = []
            for piece in pieces:
                if not piece.strip():
                    continue
                if len(piece) > self.chunk_size:
                    merged.extend(self._split_recursively(piece, index + 1))
                else:
                    merged.append(piece)
            return merged
        return [text[i : i + self.chunk_size] for i in range(0, len(text), self.chunk_size)]

    def _merge(self, pieces: list[str]) -> list[tuple[str, int]]:
        """Pack pieces into chunks, repeating an overlap tail between chunks.

        Every emitted chunk is at most ``chunk_size`` characters: the carried
        tail is shrunk when the incoming piece leaves no room for the full
        overlap, so the size contract holds exactly, not approximately.
        """
        chunks: list[tuple[str, int]] = []
        current: list[str] = []
        current_len = 0
        cursor = 0  # offset in the source where the next new content starts

        def flush() -> None:
            chunk = "".join(current)
            if chunk.strip():
                chunks.append((chunk, cursor))

        for piece in pieces:
            if current and current_len + len(piece) > self.chunk_size:
                flush()
                # Shrink the carried tail so the new chunk also respects
                # chunk_size exactly. Consecutive duplicates are impossible:
                # every post-flush chunk contains the non-empty new piece.
                tail_len = min(self.chunk_overlap, max(0, self.chunk_size - len(piece)))
                tail = chunks[-1][0][-tail_len:] if tail_len else ""
                cursor = chunks[-1][1] + (len(chunks[-1][0]) - tail_len)
                current = [tail, piece] if tail else [piece]
                current_len = len(tail) + len(piece)
            else:
                current.append(piece)
                current_len += len(piece)
        flush()
        return chunks


__all__ = ["DEFAULT_SEPARATORS", "RecursiveCharacterSplitter"]
