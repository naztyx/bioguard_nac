"""
BioGuard Agentic AI Router
Exposes the four agent decision endpoints to the API surface.
All decisions are non-blocking, fully logged, and persisted as TrustEvents.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.services import agent as agent_service
from app.logger import get_logger

logger = get_logger("routers.agent")
router = APIRouter(prefix="/agent", tags=["Agentic AI Layer"])


# ── Request schemas ───────────────────────────────────────────────────────────

class DrugDispensationRequest(BaseModel):
    phone_number:  str
    batch_code:    str
    facility_code: str
    facility_lat:  Optional[float] = None
    facility_lng:  Optional[float] = None


class WorkerAuthRequest(BaseModel):
    worker_id:      str
    verifier_phone: str


class EmergencyEscalationRequest(BaseModel):
    phone_number:   str
    emergency_type: str
    emergency_id:   int


class SuspiciousActivityRequest(BaseModel):
    phone_number:  str
    activity_type: str
    context_data:  Optional[dict] = {}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/evaluate/drug-dispensation")
async def evaluate_drug_dispensation(
    payload: DrugDispensationRequest,
    db:      AsyncSession = Depends(get_db),
):
    """
    Agentic AI Drug Dispensation Decision.

    Orchestrates CAMARA APIs in parallel:
    - Number Verification + SIM Swap + Device Status (identity)
    - Location Retrieval + Geofencing against facility (location)
    - QoS Session capture (network quality)
    - Drug record lookup (registry)

    Claude evaluates all signals simultaneously and returns:
    - approve: safe to dispense
    - flag: dispense with heightened monitoring
    - block: do NOT dispense — high risk detected

    All decisions are persisted as TrustEvents for audit.
    """
    logger.info("Drug dispensation evaluation requested", extra={
        "phone": payload.phone_number[-4:],
        "batch_code": payload.batch_code,
    })
    return await agent_service.evaluate_drug_dispensation(
        phone_number  = payload.phone_number,
        batch_code    = payload.batch_code,
        facility_code = payload.facility_code,
        facility_lat  = payload.facility_lat,
        facility_lng  = payload.facility_lng,
        db            = db,
    )


@router.post("/evaluate/worker-authentication")
async def evaluate_worker_authentication(
    payload: WorkerAuthRequest,
    db:      AsyncSession = Depends(get_db),
):
    """
    Agentic AI Healthcare Worker Authentication.

    Runs in parallel:
    - Worker's SIM swap + number verify + device status
    - Worker's live location vs registered facility (geofence)
    - Network quality check

    Claude evaluates combined signals and returns:
    - approve: worker is legitimate, allow to proceed
    - flag: concerns present, allow with monitoring
    - block: high-risk signals, do not allow medical duties
    """
    logger.info("Worker authentication requested", extra={
        "worker_id": payload.worker_id,
        "verifier":  payload.verifier_phone[-4:],
    })
    return await agent_service.evaluate_worker_authentication(
        worker_id      = payload.worker_id,
        verifier_phone = payload.verifier_phone,
        db             = db,
    )


@router.post("/evaluate/emergency-escalation")
async def evaluate_emergency_escalation(
    payload: EmergencyEscalationRequest,
    db:      AsyncSession = Depends(get_db),
):
    """
    Agentic AI Emergency Triage and Escalation.

    Runs in parallel:
    - Patient identity and device reachability
    - CAMARA live location retrieval
    - QoS priority network activation

    Claude triages the emergency severity and returns:
    - approve: standard dispatch response
    - escalate: critical — requires immediate multi-facility coordination
    - flag: location unclear or device unreachable, attempt callback first
    """
    logger.warning("Emergency escalation evaluation requested", extra={
        "phone": payload.phone_number[-4:],
        "type":  payload.emergency_type,
        "id":    payload.emergency_id,
    })
    return await agent_service.evaluate_emergency_escalation(
        phone_number   = payload.phone_number,
        emergency_type = payload.emergency_type,
        emergency_id   = payload.emergency_id,
        db             = db,
    )


@router.post("/evaluate/suspicious-activity")
async def detect_suspicious_activity(
    payload: SuspiciousActivityRequest,
    db:      AsyncSession = Depends(get_db),
):
    """
    Agentic AI Suspicious Activity Detection.

    Triggered when patterns accumulate:
    - multiple_drug_verify_fails
    - repeated_sim_swap
    - location_hopping
    - unregistered_dispenser

    Claude evaluates the full signal picture including trust event history.
    If decision is block or escalate, a trust penalty is automatically applied
    and the event is logged for regulatory review.
    """
    valid_activities = {
        "multiple_drug_verify_fails",
        "repeated_sim_swap",
        "location_hopping",
        "unregistered_dispenser",
    }
    if payload.activity_type not in valid_activities:
        raise HTTPException(
            status_code=422,
            detail=f"activity_type must be one of: {sorted(valid_activities)}",
        )

    logger.warning("Suspicious activity scan triggered", extra={
        "phone":    payload.phone_number[-4:],
        "activity": payload.activity_type,
    })
    return await agent_service.detect_suspicious_activity(
        phone_number = payload.phone_number,
        activity     = payload.activity_type,
        context_data = payload.context_data or {},
        db           = db,
    )


@router.get("/health")
async def agent_health():
    """Check Agentic AI layer status and Claude API reachability."""
    import httpx
    from app.config import get_settings
    settings = get_settings()

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get("https://api.anthropic.com")
        claude_reachable = r.status_code < 500
    except Exception:
        claude_reachable = False

    return {
        "agent_layer":      "online",
        "claude_model":     agent_service.CLAUDE_MODEL,
        "simulate_camara":  settings.NAC_SIMULATE,
        "claude_reachable": claude_reachable,
        "fallback_mode":    not claude_reachable,
        "endpoints": [
            "POST /agent/evaluate/drug-dispensation",
            "POST /agent/evaluate/worker-authentication",
            "POST /agent/evaluate/emergency-escalation",
            "POST /agent/evaluate/suspicious-activity",
        ],
    }
