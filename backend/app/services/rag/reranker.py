import re

from app.services.rag.models import RetrievedChunk


class Reranker:
    """Hybrid reranker combining vector semantic similarity with lexical term overlap and position matching."""

    def __init__(
        self,
        semantic_weight: float = 0.65,
        lexical_weight: float = 0.35,
    ) -> None:
        self.semantic_weight = semantic_weight
        self.lexical_weight = lexical_weight

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Extract alphanumeric tokens from text."""
        return set(re.findall(r"\b[a-zA-Z0-9_-]{2,}\b", text.lower()))

    def _compute_lexical_score(self, query: str, chunk: RetrievedChunk) -> float:
        """Compute lexical overlap score between query and chunk text."""
        q_tokens = self._tokenize(query)
        if not q_tokens:
            return 0.0

        c_tokens = self._tokenize(chunk.content)
        f_tokens = self._tokenize(chunk.filename)
        combined_target_tokens = c_tokens | f_tokens

        # Token overlap ratio (Jaccard-like recall)
        matched_tokens = q_tokens & combined_target_tokens
        token_recall = len(matched_tokens) / len(q_tokens)

        # Bonus for exact substring match of query
        exact_bonus = 0.0
        q_clean = query.lower().strip()
        if len(q_clean) > 3 and q_clean in chunk.content.lower():
            exact_bonus = 0.25

        score = min(1.0, (token_recall * 0.75) + exact_bonus)
        return score

    def rerank(self, query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """Rerank retrieved chunks using hybrid semantic and lexical scoring."""
        if not chunks or not query.strip():
            return chunks

        scored_chunks: list[RetrievedChunk] = []
        for chunk in chunks:
            lex_score = self._compute_lexical_score(query, chunk)
            composite_score = round(
                (self.semantic_weight * chunk.similarity_score) + (self.lexical_weight * lex_score),
                4,
            )
            chunk.rerank_score = composite_score
            scored_chunks.append(chunk)

        # Sort descending by composite rerank score
        scored_chunks.sort(key=lambda c: (-(c.rerank_score or 0.0), -c.similarity_score))
        return scored_chunks
