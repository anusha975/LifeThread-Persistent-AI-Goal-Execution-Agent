from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.db.session import get_db
from app.dependencies.auth import get_current_active_user
from app.services.agent_evaluation.models import AgentEvaluationReport, EvaluationPillar
from app.services.agent_evaluation.suite import AgentEvaluationSuite

router = APIRouter(prefix="/evaluation", tags=["Automated Agent Evaluation"])


@router.post(
    "/run",
    response_model=AgentEvaluationReport,
    summary="Run Automated Agent Evaluation Suite",
    description="Execute scenario-based evaluation tests across all 10 agent operational pillars and generate a comprehensive report.",
)
async def run_evaluation_suite(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentEvaluationReport:
    """Execute the full 10-pillar scenario evaluation suite against real system components."""
    return await AgentEvaluationSuite.run_all_scenarios(db=db, user_id=current_user.id)


@router.get(
    "/latest",
    response_model=AgentEvaluationReport,
    summary="Get Latest Evaluation Report",
    description="Retrieve the most recent automated evaluation report, executing a fresh evaluation if none exists.",
)
async def get_latest_evaluation_report(
    current_user: Annotated[User, Depends(get_current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AgentEvaluationReport:
    """Fetch the latest evaluation report."""
    report = AgentEvaluationSuite.get_latest_report()
    if not report:
        report = await AgentEvaluationSuite.run_all_scenarios(db=db, user_id=current_user.id)
    return report


@router.get(
    "/pillars",
    summary="List Evaluation Pillars",
    description="List the 10 operational pillars tested by the automated agent evaluation suite.",
)
async def list_evaluation_pillars(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> dict[str, Any]:
    """Retrieve specifications for all 10 evaluation pillars."""
    pillars = [
        {
            "id": p.value,
            "name": p.value.replace("_", " ").title(),
            "description": f"Observable evaluation for {p.value.replace('_', ' ')}.",
        }
        for p in EvaluationPillar
    ]
    return {"total_pillars": len(pillars), "pillars": pillars}
