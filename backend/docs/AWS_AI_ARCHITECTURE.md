# LifeThread: AWS AI Integration Architecture (Module 35)

## 1. Architectural Principles & Value Proposition

LifeThread uses AWS AI services only where they provide clear, enterprise-grade capabilities that cannot be replicated easily or efficiently on a single node without high operational overhead. We adhere to three non-negotiable architectural mandates:

1. **Clean Provider Abstraction**: All AWS AI services are accessed through domain-level abstract base classes (`BaseLLMProvider`, `BaseAgentCoreProvider`, `BaseStrandsProvider`).
2. **Decoupled Fallback**: Local development, CI/CD test runs, and offline execution remain 100% functional without requiring an active AWS account, cloud network connectivity, or incurring developer cloud costs.
3. **Enterprise Defense & Cost Governance**: Every invocation is bound by adaptive retries, timeouts, strict tenant isolation, and real-time token/USD cost tracking.

---

## 2. Evaluation & Justification of Selected AWS Services

### A. Amazon Bedrock (Foundation Models)
- **Why It Is Used**:
  - Provides unified, managed access to top-tier foundation models (Anthropic Claude 3.5 Sonnet, Claude 3 Haiku, Amazon Titan) through a standardized Converse API.
  - Eliminates the need to maintain self-hosted GPU infrastructure or manage multiple disparate vendor API schemas.
  - Native AWS compliance boundaries: data remains within VPC/AWS tenant boundaries and is not used to train external models.
- **Cost-Aware Routing Model**:
  - **Reasoning Tier (`anthropic.claude-3-5-sonnet`)**: Assigned to high-complexity cognitive tasks: multi-step goal decomposition, critical-path dependency recalculation, and autonomous replanning trade-offs ($3.00/M input, $15.00/M output).
  - **Speed & Economy Tier (`anthropic.claude-3-haiku`)**: Assigned to high-frequency, low-latency tasks: intent classification, skill routing, entity extraction, and conversational greetings ($0.25/M input, $1.25/M output).
- **Resilience**:
  - Configurable timeouts (`connect_timeout`, `read_timeout`).
  - Exponential backoff with jitter on `ThrottlingException` and `ModelTimeoutException`.
  - Fallback: Gracefully routes to secondary or local fallback providers if credentials or quotas fail.

### B. AgentCore (Amazon Bedrock Agents & Action Groups)
- **Why It Is Used**:
  - Provides a structured multi-turn orchestration framework with OpenAPI schema validation and discrete Action Groups.
  - Maps cleanly to LifeThread's 5 Agent Skills: `Goal Management`, `Planning`, `Memory`, `Evaluation`, and `Replanning`.
  - Enforces deterministic action dispatching and produces structured execution traces (`OBSERVATION`, `ACTION_CALL`, `ACTION_RESULT`, `RATIONALE`) without leaking private chain-of-thought tokens.
- **Abstraction & Local Fallback**:
  - `BaseAgentCoreProvider` defines `execute_action(request, db, user_permissions)`.
  - `BedrockAgentCoreProvider` interfaces with `bedrock-agent-runtime.invoke_agent`.
  - `LocalAgentCoreProvider` executes action groups locally using LifeThread's `SkillRegistry`.

### C. Strands (Bedrock Knowledge Bases & Semantic Context Threads)
- **Why It Is Used**:
  - Human life goals are not isolated transactions; they form interconnected semantic "strands" over months and years (linking habits, past outcomes, learned weaknesses, and shifting priorities).
  - Amazon Bedrock Knowledge Bases provide managed semantic chunking, vector indexing (via OpenSearch Serverless / Pinecone / Aurora pgvector), and hybrid retrieval with citations.
  - Strict tenant isolation is enforced at the query level via metadata filter: `{"equals": {"key": "user_id", "value": str(user_id)}}`.
- **Abstraction & Local Fallback**:
  - `BaseStrandsProvider` defines `search(...)` and `index(...)`.
  - `BedrockStrandsProvider` queries Bedrock Knowledge Base.
  - `LocalStrandsProvider` maintains an in-memory/database context thread store for zero-dependency local development and testing.

---

## 3. Services Explicitly Excluded (No "Demonstration" Services)

| Service Evaluated | Decision | Architectural Rationale |
| :--- | :--- | :--- |
| **Amazon SageMaker Endpoints** | **Excluded** | Custom endpoint hosting requires 24/7 dedicated compute instances ($$$), increasing operational costs without performance benefits over serverless Bedrock models. |
| **Amazon Comprehend** | **Excluded** | Standard sentiment/NLP extraction is redundant when Claude 3 Haiku performs zero-shot entity extraction with superior contextual understanding at lower cost. |
| **AWS Kendra** | **Excluded** | Heavy enterprise search tool tailored for SharePoint/Salesforce crawling. Bedrock Knowledge Bases natively integrates with our vector embeddings and provides tighter RAG latency. |

---

## 4. Security & Configuration Architecture

- **Credential Resolution**:
  1. Explicit configuration (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`).
  2. IAM Role Assumption via STS (`AWS_ROLE_ARN`) for cross-account or Kubernetes IRSA (IAM Roles for Service Accounts).
  3. Standard AWS environment credentials (EC2 Instance Metadata, ECS Task Role, EKS Pod Identity).
- **Masking & Audit Logging**:
  - Secret keys are never printed in application logs or API responses.
  - Status endpoints mask credentials (e.g. `AKIA...B7DF`) and indicate whether role assumption is active.
- **Environment Awareness**:
  - In `development` and `test`, missing AWS credentials automatically trigger local fallback mode without throwing unhandled exceptions.
  - In `production`, configuration can enforce mandatory AWS connectivity if desired.

---

## 5. Cost Tracking & Governance

Every Bedrock interaction records:
- Input tokens & output tokens.
- Exact calculated USD cost based on published model price sheets.
- Cumulative metrics exposed via `GET /api/v1/aws/costs` to enable budget alerts and multi-tenant billing attribution.
