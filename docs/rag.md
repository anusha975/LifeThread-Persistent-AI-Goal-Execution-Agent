# LifeThread Semantic Retrieval & RAG Engine

## 1. Overview

LifeThread incorporates a specialized Retrieval-Augmented Generation (RAG) and Semantic Retrieval subsystem designed for agent context assembly. Rather than overloading LLM prompts with complete historical transcripts, the RAG engine queries the pgvector store to surface the most relevant, high-importance memories and constraints within strict token budgets.

```
+---------------------------------------------------------------------------------------+
|                                    SEARCH QUERY                                       |
|               e.g. "Tokio async actor mailbox backpressure handling"                 |
+-------------------------------------------+-------------------------------------------+
                                            |
                                            v
+---------------------------------------------------------------------------------------+
|                                 EMBEDDING PROVIDER                                    |
|               BaseEmbeddingProvider -> 1536-dimensional unit vector                   |
+-------------------------------------------+-------------------------------------------+
                                            |
                                            v
+---------------------------------------------------------------------------------------+
|                                POSTGRESQL (pgvector)                                  |
|        SELECT ... ORDER BY embedding <=> query_vector LIMIT 50                        |
+-------------------------------------------+-------------------------------------------+
                                            |
                                            v
+---------------------------------------------------------------------------------------+
|                                  HYBRID RERANKER                                      |
|    Score = (w_sim * CosineSim) + (w_imp * Importance) + (w_rec * RecencyDecay)        |
+-------------------------------------------+-------------------------------------------+
                                            |
                                            v
+---------------------------------------------------------------------------------------+
|                                  CONTEXT ENGINE                                       |
|               Pack ranked memories into LLM prompt within token budget                |
+---------------------------------------------------------------------------------------+
```

---

## 2. Vector Embedding Architecture

- **Vector Dimension:** Standardized to **1536 dimensions** matching state-of-the-art embedding models.
- **Provider Abstraction (`BaseEmbeddingProvider`):**
  - Allows swapping between real cloud embedding services (e.g. OpenAI `text-embedding-3-small`, Gemini Embeddings) and deterministic local providers without changing domain logic.
  - `MockEmbeddingProvider`: Generates deterministic, unit-normalized vectors ($\sqrt{\sum x_i^2} \approx 1.0$) for high-speed local unit and integration testing.
- **pgvector Indexing:** Uses PostgreSQL Hierarchical Navigable Small World (HNSW) indexing with `vector_cosine_ops` for sub-20ms p95 retrieval latency.

---

## 3. Hybrid Reranking Formula

Pure cosine similarity often surfaces trivial or outdated matches. The LifeThread retriever (`SemanticMemoryRetriever`) scores candidates using a multi-factor hybrid function:

$$\text{FinalScore} = (w_{\text{sim}} \cdot \text{CosineSim}) + (w_{\text{imp}} \cdot \text{Importance}) + (w_{\text{rec}} \cdot \text{RecencyFactor})$$

Where:
- **$\text{CosineSim} \in [0.0, 1.0]$:** Calculated as $1.0 - \text{cosine\_distance}$.
- **$\text{Importance} \in [0.0, 1.0]$:** Stored weight on the memory record.
- **$\text{RecencyFactor} \in [0.0, 1.0]$:** Exponential time-decay function based on the elapsed hours since `last_accessed_at` or `created_at`:
  $$\text{RecencyFactor} = e^{-\lambda \cdot \Delta t}$$
- **Default Weights:** $w_{\text{sim}} = 0.50$, $w_{\text{imp}} = 0.30$, $w_{\text{rec}} = 0.20$.

---

## 4. Context Window Assembly (`ContextEngine`)

When preparing prompts for Goal Decomposition, Task Execution, or Replanning:
1. **Category Budgeting:** Reserves specific token quotas for Goal Constraints (30%), Semantic Weaknesses/Learnings (30%), Relevant Past Outcomes (25%), and User Preferences (15%).
2. **Token Truncation:** Ensures the aggregated context fits comfortably within the LLM's working window without prompt truncation.
3. **Structured Prompt Injection:** Formats retrieved memories into markdown sections (`### Active Goal Constraints`, `### Relevant Past Outcomes`, `### Known Weaknesses & Remedial Policies`).
