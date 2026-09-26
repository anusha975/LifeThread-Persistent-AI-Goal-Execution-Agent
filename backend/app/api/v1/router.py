from fastapi import APIRouter

from app.api.v1 import (
    agent,
    auth,
    aws_ai,
    context,
    demo,
    documents,
    evaluation,
    goals,
    health,
    learning,
    memories,
    observability,
    permissions,
    rag,
    recovery,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["Health & Readiness"])
api_router.include_router(auth.router)
api_router.include_router(goals.router)
api_router.include_router(documents.router)
api_router.include_router(rag.router)
api_router.include_router(context.router)
api_router.include_router(learning.router)
api_router.include_router(recovery.router)
api_router.include_router(permissions.router)
api_router.include_router(agent.router)
api_router.include_router(memories.router)
api_router.include_router(aws_ai.router)
api_router.include_router(observability.router)
api_router.include_router(evaluation.router)
api_router.include_router(demo.router)

