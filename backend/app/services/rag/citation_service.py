from app.services.rag.models import Citation, RetrievedChunk


class CitationService:
    """Extracts, formats, and validates source citations for RAG responses."""

    @staticmethod
    def extract_citations(
        chunks: list[RetrievedChunk],
        answer_text: str | None = None,
    ) -> list[Citation]:
        """Generate structured citations from retrieved chunks."""
        citations: list[Citation] = []

        for idx, chunk in enumerate(chunks, start=1):
            # Take a concise, clean excerpt from chunk
            clean_snippet = " ".join(chunk.content.split())
            excerpt = clean_snippet[:140] + ("..." if len(clean_snippet) > 140 else "")

            score = chunk.rerank_score if chunk.rerank_score is not None else chunk.similarity_score

            citation = Citation(
                citation_index=idx,
                document_id=chunk.document_id,
                filename=chunk.filename,
                chunk_id=chunk.chunk_id,
                chunk_index=chunk.chunk_index,
                page_number=chunk.page_number,
                excerpt=excerpt,
                relevance_score=round(score, 4),
            )
            citations.append(citation)

        return citations

    @staticmethod
    def format_citations_markdown(citations: list[Citation]) -> str:
        """Format citation list into a clean markdown reference appendix."""
        if not citations:
            return ""

        lines = ["\n\n### Sources & Citations:"]
        for c in citations:
            page_str = f", Page {c.page_number}" if c.page_number else ""
            lines.append(
                f'- **[{c.citation_index}]** `{c.filename}` (Chunk {c.chunk_index}{page_str}): "{c.excerpt}"'
            )

        return "\n".join(lines)
