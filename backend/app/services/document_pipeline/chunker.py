from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChunkData:
    """Structured data for an individual text chunk."""

    chunk_index: int
    content: str
    char_start: int
    char_end: int
    metadata: dict[str, Any] = field(default_factory=dict)


class TextChunker:
    """Recursive boundary-aware text chunker with configurable size and overlap."""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if chunk_overlap < 0:
            raise ValueError("chunk_overlap cannot be negative")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be strictly less than chunk_size")

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._separators = ["\n\n", "\n", ". ", "? ", "! ", "; ", " ", ""]

    def chunk_text(self, text: str) -> list[ChunkData]:
        """Split text into overlapping chunks respecting natural structural boundaries."""
        if not text or not text.strip():
            return []

        clean = text.strip()
        if len(clean) <= self.chunk_size:
            # Single chunk fits completely
            return [
                ChunkData(
                    chunk_index=0,
                    content=clean,
                    char_start=0,
                    char_end=len(clean),
                    metadata={
                        "chunk_index": 0,
                        "char_start": 0,
                        "char_end": len(clean),
                        "char_count": len(clean),
                        "word_count": len(clean.split()),
                    },
                )
            ]

        raw_splits = self._split_recursive(clean, self._separators)
        merged_chunks = self._merge_splits(raw_splits, clean)
        return merged_chunks

    def _split_recursive(self, text: str, separators: list[str]) -> list[str]:
        """Recursively split text by separators until pieces are under chunk_size."""
        final_pieces: list[str] = []
        separator = separators[-1]
        new_separators = []

        for i, sep in enumerate(separators):
            if sep == "":
                separator = ""
                break
            if sep in text:
                separator = sep
                new_separators = separators[i + 1 :]
                break

        splits = text.split(separator) if separator != "" else list(text)

        for split in splits:
            if not split:
                continue
            if len(split) <= self.chunk_size:
                final_pieces.append(split)
            elif new_separators:
                final_pieces.extend(self._split_recursive(split, new_separators))
            else:
                # Force split by characters if no more separators remain
                for j in range(0, len(split), self.chunk_size):
                    final_pieces.append(split[j : j + self.chunk_size])

        return final_pieces

    def _merge_splits(self, pieces: list[str], full_text: str) -> list[ChunkData]:
        """Merge pieces into overlapping chunks up to chunk_size."""
        chunks: list[ChunkData] = []
        current_pieces: list[str] = []
        current_len = 0
        search_cursor = 0

        for piece in pieces:
            piece_len = len(piece)
            if (
                current_len + piece_len + (1 if current_pieces else 0) > self.chunk_size
                and current_pieces
            ):
                # Flush current chunk
                chunk_str = " ".join(current_pieces).strip()
                if chunk_str:
                    c_start = full_text.find(chunk_str[: min(30, len(chunk_str))], search_cursor)
                    if c_start == -1:
                        c_start = search_cursor
                    c_end = c_start + len(chunk_str)
                    search_cursor = max(search_cursor, c_start)

                    chunks.append(
                        ChunkData(
                            chunk_index=len(chunks),
                            content=chunk_str,
                            char_start=c_start,
                            char_end=c_end,
                            metadata={
                                "chunk_index": len(chunks),
                                "char_start": c_start,
                                "char_end": c_end,
                                "char_count": len(chunk_str),
                                "word_count": len(chunk_str.split()),
                            },
                        )
                    )

                # Keep overlap pieces from the tail of current_pieces
                overlap_pieces: list[str] = []
                overlap_len = 0
                for p in reversed(current_pieces):
                    if overlap_len + len(p) <= self.chunk_overlap:
                        overlap_pieces.insert(0, p)
                        overlap_len += len(p) + 1
                    else:
                        break
                current_pieces = overlap_pieces
                current_len = sum(len(p) for p in current_pieces) + max(0, len(current_pieces) - 1)

            current_pieces.append(piece)
            current_len += piece_len + (1 if len(current_pieces) > 1 else 0)

        # Final remaining piece
        if current_pieces:
            chunk_str = " ".join(current_pieces).strip()
            if chunk_str:
                c_start = full_text.find(chunk_str[: min(30, len(chunk_str))], search_cursor)
                if c_start == -1:
                    c_start = search_cursor
                c_end = c_start + len(chunk_str)

                chunks.append(
                    ChunkData(
                        chunk_index=len(chunks),
                        content=chunk_str,
                        char_start=c_start,
                        char_end=c_end,
                        metadata={
                            "chunk_index": len(chunks),
                            "char_start": c_start,
                            "char_end": c_end,
                            "char_count": len(chunk_str),
                            "word_count": len(chunk_str.split()),
                        },
                    )
                )

        return chunks
