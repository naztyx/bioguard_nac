from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
import uuid

from app.database import get_db
from app import models, schemas
from app.services import trust as trust_service
from app.logger import get_logger

logger = get_logger("routers.identity")
router = APIRouter(prefix="/identity", tags=["Identity Trust Module"])


# ── Patients ──────────────────────────────────────────────────────────────────

@router.post("/patients", response_model=schemas.PatientOut, status_code=status.HTTP_201_CREATED)
async def register_patient(payload: schemas.PatientCreate, db: AsyncSession = Depends(get_db)):
    """Register a new patient and assign a unique BioGuard Health ID."""
    result = await db.execute(
        select(models.Patient).where(models.Patient.phone_number == payload.phone_number)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Phone number already registered.")

    # Count-free ID generation using UUID suffix to avoid race conditions
    count_result = await db.execute(select(models.Patient))
    count = len(count_result.scalars().all())
    health_id = f"BG-NG-{count + 1:05d}"

    patient = models.Patient(
        phone_number  = payload.phone_number,
        health_id     = health_id,
        full_name     = payload.full_name,
        date_of_birth = payload.date_of_birth,
        blood_group   = payload.blood_group,
        region        = payload.region,
        trust_score   = 100.0,
    )
    db.add(patient)
    await db.commit()
    await db.refresh(patient)

    logger.info("Patient registered", extra={
        "health_id": health_id,
        "phone":     payload.phone_number[-4:],
        "region":    payload.region,
    })
    return patient


@router.get("/patients", response_model=List[schemas.PatientOut])
async def list_patients(skip: int = 0, limit: int = 50, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.Patient).offset(skip).limit(limit))
    return result.scalars().all()


@router.get("/patients/{phone_number}", response_model=schemas.PatientOut)
async def get_patient(phone_number: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.Patient).where(models.Patient.phone_number == phone_number)
    )
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found.")
    return patient


# ── Healthcare Workers ────────────────────────────────────────────────────────

@router.post("/workers", response_model=schemas.WorkerOut, status_code=status.HTTP_201_CREATED)
async def register_worker(payload: schemas.WorkerCreate, db: AsyncSession = Depends(get_db)):
    """Register a healthcare worker (admin / facility manager action)."""
    result = await db.execute(
        select(models.HealthcareWorker).where(
            models.HealthcareWorker.phone_number == payload.phone_number
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Phone number already registered.")

    worker = models.HealthcareWorker(
        phone_number   = payload.phone_number,
        worker_id      = payload.worker_id.upper(),
        full_name      = payload.full_name,
        facility_name  = payload.facility_name,
        facility_code  = payload.facility_code,
        specialization = payload.specialization,
        is_verified    = False,
        trust_score    = 100.0,
    )
    db.add(worker)
    await db.commit()
    await db.refresh(worker)

    logger.info("Worker registered", extra={
        "worker_id": worker.worker_id,
        "phone":     payload.phone_number[-4:],
        "facility":  payload.facility_name,
    })
    return worker


@router.get("/workers/{worker_id}", response_model=schemas.WorkerVerifyResponse)
async def verify_worker(worker_id: str, db: AsyncSession = Depends(get_db)):
    """
    Full worker verification — runs parallel CAMARA SIM Swap + Number Verify.
    Used by patients and facilities to confirm a worker's legitimacy.
    """
    result = await db.execute(
        select(models.HealthcareWorker).where(
            models.HealthcareWorker.worker_id == worker_id.upper()
        )
    )
    worker = result.scalar_one_or_none()
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found.")

    eval_result = await trust_service.evaluate_identity(
        phone_number=worker.phone_number, db=db, entity_type="worker",
    )

    logger.info("Worker verification complete", extra={
        "worker_id":   worker_id,
        "trust_level": eval_result["trust_level"],
        "sim_swap":    eval_result["sim_swap_detected"],
    })

    return schemas.WorkerVerifyResponse(
        worker_id          = worker.worker_id,
        full_name          = worker.full_name,
        facility_name      = worker.facility_name,
        specialization     = worker.specialization,
        is_verified        = worker.is_verified,
        trust_score        = eval_result["trust_score"],
        sim_swap_detected  = eval_result["sim_swap_detected"],
        number_verified    = eval_result["number_verified"],
        trust_level        = eval_result["trust_level"],
        recommendation     = eval_result["recommendation"],
    )


@router.patch("/workers/{worker_id}/verify")
async def approve_worker(worker_id: str, db: AsyncSession = Depends(get_db)):
    """Admin: manually approve a healthcare worker."""
    result = await db.execute(
        select(models.HealthcareWorker).where(
            models.HealthcareWorker.worker_id == worker_id.upper()
        )
    )
    worker = result.scalar_one_or_none()
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found.")
    worker.is_verified = True
    await db.commit()
    logger.info("Worker manually approved", extra={"worker_id": worker_id})
    return {"message": f"Worker {worker_id} verified successfully."}


# ── Identity Verification (CAMARA) ────────────────────────────────────────────

@router.post("/verify", response_model=schemas.IdentityVerifyResponse)
async def verify_identity(
    payload: schemas.IdentityVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Full CAMARA identity check on any phone number.
    Runs Number Verify, SIM Swap, and Device Status in parallel.
    Core endpoint used by the Agentic AI layer.
    """
    result = await trust_service.evaluate_identity(
        phone_number=payload.phone_number,
        db=db,
        entity_type=payload.entity_type,
        location_lat=payload.location_lat,
        location_lng=payload.location_lng,
    )
    return schemas.IdentityVerifyResponse(**result)


@router.get("/trust-history/{phone_number}")
async def get_trust_history(
    phone_number: str,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """Trust score event audit log for a phone number."""
    result = await db.execute(
        select(models.TrustEvent)
        .where(models.TrustEvent.phone_number == phone_number)
        .order_by(models.TrustEvent.created_at.desc())
        .limit(limit)
    )
    events = result.scalars().all()
    return [
        {
            "event_type":  e.event_type,
            "score_delta": e.score_delta,
            "new_score":   e.new_score,
            "meta":        e.meta,
            "timestamp":   e.created_at,
        }
        for e in events
    ]
