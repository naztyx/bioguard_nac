from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from datetime import datetime

from app.database import get_db
from app import models, schemas
from app.services import camara as camara_service
from app.logger import get_logger

logger = get_logger("routers.drugs")
router = APIRouter(prefix="/drugs", tags=["Drug Safety Module"])

NAFDAC_HOTLINE = "0800-1-623322"


def _safety_level(result: str, location_ok: bool, cold_ok: bool) -> tuple[str, str]:
    """Returns (safety_level, action) based on verification result."""
    if result == "authentic" and location_ok and cold_ok:
        return "SAFE",     "Safe to dispense and consume."
    if result == "authentic" and not location_ok:
        return "WARNING",  "Authentic but dispensed from unauthorized location. Flag for review."
    if result == "authentic" and not cold_ok:
        return "WARNING",  "Authentic but cold-chain integrity unconfirmed. Verify storage."
    if result == "expired":
        return "DANGER",   "Drug expired. Do NOT dispense. Remove from shelf immediately."
    if result == "recalled":
        return "CRITICAL",f"Drug RECALLED. Do NOT dispense. Quarantine batch and call NAFDAC: {NAFDAC_HOTLINE}"
    if result == "not_found":
        return "CRITICAL",f"Drug NOT in registry — possible counterfeit. Do NOT dispense. Call NAFDAC: {NAFDAC_HOTLINE}"
    return "DANGER", "Verification failed. Do not dispense."


# ── Drug registry ─────────────────────────────────────────────────────────────

@router.post("/", response_model=schemas.DrugOut, status_code=status.HTTP_201_CREATED)
async def register_drug(payload: schemas.DrugCreate, db: AsyncSession = Depends(get_db)):
    """Register a drug batch (manufacturer / NAFDAC-authorized distributor action)."""
    result = await db.execute(
        select(models.Drug).where(models.Drug.batch_code == payload.batch_code)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Batch code already registered.")

    drug = models.Drug(**payload.model_dump())
    db.add(drug)
    await db.commit()
    await db.refresh(drug)

    logger.info("Drug batch registered", extra={
        "batch_code": drug.batch_code,
        "drug_name":  drug.drug_name,
        "expiry":     drug.expiry_date,
    })
    return drug


@router.get("/", response_model=List[schemas.DrugOut])
async def list_drugs(skip: int = 0, limit: int = 50, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.Drug).offset(skip).limit(limit))
    return result.scalars().all()


@router.get("/{batch_code}", response_model=schemas.DrugOut)
async def get_drug(batch_code: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.Drug).where(models.Drug.batch_code == batch_code.upper())
    )
    drug = result.scalar_one_or_none()
    if not drug:
        raise HTTPException(status_code=404, detail="Drug batch not found.")
    return drug


# ── Drug Verification (core safety check) ─────────────────────────────────────

@router.post("/verify", response_model=schemas.DrugVerifyResponse)
async def verify_drug(payload: schemas.DrugVerifyRequest, db: AsyncSession = Depends(get_db)):
    """
    Full drug authenticity pipeline:
    1. Registry lookup (existence check)
    2. Recall status
    3. Expiry date
    4. CAMARA geofencing — authorized facility check
    5. Cold-chain integrity signal
    Returns safety_level + action for immediate dispensing decision.
    """
    batch_code = payload.batch_code.strip().upper()
    logger.info("Drug verification requested", extra={
        "batch_code":    batch_code,
        "phone":         payload.phone_number[-4:],
        "facility_code": payload.facility_code,
    })

    result = await db.execute(select(models.Drug).where(models.Drug.batch_code == batch_code))
    drug   = result.scalar_one_or_none()

    # ── Not found ──────────────────────────────────────────────────────────
    if not drug:
        logger.warning("Drug not found in registry", extra={"batch_code": batch_code})
        db.add(models.DrugVerification(
            batch_code=batch_code, verified_by_phone=payload.phone_number,
            verification_channel="api", result="not_found",
            trust_score_at_time=0, alert_sent=True,
            notes="Batch not in BioGuard registry — possible counterfeit.",
        ))
        await db.commit()
        level, action = _safety_level("not_found", False, True)
        return schemas.DrugVerifyResponse(
            batch_code=batch_code, drug_name=None, manufacturer=None,
            expiry_date=None, result="not_found",
            location_authorized=False, cold_chain_ok=True,
            trust_score=0.0, safety_level=level, message=action,
            action=action, nafdac_number=None,
        )

    # ── Recalled ───────────────────────────────────────────────────────────
    if drug.is_recalled:
        logger.warning("Recalled drug verification attempt", extra={"batch_code": batch_code})
        level, action = _safety_level("recalled", False, True)
        return schemas.DrugVerifyResponse(
            batch_code=batch_code, drug_name=drug.drug_name,
            manufacturer=drug.manufacturer, expiry_date=drug.expiry_date,
            result="recalled", location_authorized=False, cold_chain_ok=True,
            trust_score=0.0, safety_level=level,
            message=f"RECALLED: {drug.recall_reason or 'Safety recall'}",
            action=action, nafdac_number=drug.nafdac_number,
        )

    # ── Expiry ─────────────────────────────────────────────────────────────
    try:
        expired = datetime.strptime(drug.expiry_date, "%Y-%m-%d") < datetime.utcnow()
    except Exception:
        expired = False

    if expired:
        logger.warning("Expired drug verification attempt", extra={
            "batch_code": batch_code, "expiry": drug.expiry_date
        })
        level, action = _safety_level("expired", True, True)
        return schemas.DrugVerifyResponse(
            batch_code=batch_code, drug_name=drug.drug_name,
            manufacturer=drug.manufacturer, expiry_date=drug.expiry_date,
            result="expired", location_authorized=True, cold_chain_ok=True,
            trust_score=5.0, safety_level=level,
            message=f"Drug expired on {drug.expiry_date}. Do NOT dispense.",
            action=action, nafdac_number=drug.nafdac_number,
        )

    # ── Location + cold-chain checks (parallel) ────────────────────────────
    location_authorized = True
    cold_chain_ok       = True

    async def _check_location():
        if payload.facility_code and drug.authorized_facility_codes:
            return payload.facility_code in drug.authorized_facility_codes
        if payload.location_lat and payload.location_lng:
            lv = await camara_service.verify_location(
                payload.phone_number,
                payload.location_lat, payload.location_lng,
                radius_km=5.0,
            )
            return lv.match
        return True  # no location data — pass through (log warning)

    async def _check_cold_chain():
        if not drug.cold_chain_required:
            return True
        ds = await camara_service.get_device_status(payload.phone_number)
        return ds.reachable

    location_authorized, cold_chain_ok = await asyncio.gather(
        _check_location(), _check_cold_chain()
    )

    if not location_authorized:
        logger.warning("Drug dispensed from unauthorized location", extra={
            "batch_code": batch_code, "facility_code": payload.facility_code
        })
    if not cold_chain_ok:
        logger.warning("Cold-chain integrity unconfirmed", extra={"batch_code": batch_code})

    trust_score = 100.0
    if not location_authorized: trust_score -= 40.0
    if not cold_chain_ok:       trust_score -= 20.0

    result_str = "authentic" if location_authorized else "counterfeit"
    level, action = _safety_level(result_str, location_authorized, cold_chain_ok)

    message_parts = [f"{drug.drug_name} verified authentic."]
    if not location_authorized:
        message_parts = ["Drug dispensed from UNAUTHORIZED location. Possible diversion."]
    if not cold_chain_ok:
        message_parts.append("Cold-chain integrity cannot be confirmed.")

    logger.info("Drug verification complete", extra={
        "batch_code":   batch_code,
        "result":       result_str,
        "safety_level": level,
        "location_ok":  location_authorized,
        "cold_chain_ok": cold_chain_ok,
    })

    db.add(models.DrugVerification(
        batch_code=batch_code, verified_by_phone=payload.phone_number,
        verification_channel="api",
        verification_location=payload.facility_code or "UNKNOWN",
        result=result_str, trust_score_at_time=trust_score,
        camara_location_match=location_authorized,
        alert_sent=not location_authorized,
        notes=" | ".join(message_parts),
    ))
    await db.commit()

    return schemas.DrugVerifyResponse(
        batch_code=batch_code, drug_name=drug.drug_name,
        manufacturer=drug.manufacturer, expiry_date=drug.expiry_date,
        result=result_str, location_authorized=location_authorized,
        cold_chain_ok=cold_chain_ok, trust_score=trust_score,
        safety_level=level, message=" ".join(message_parts),
        action=action, nafdac_number=drug.nafdac_number,
    )


# ── Recall management ─────────────────────────────────────────────────────────

@router.patch("/{batch_code}/recall")
async def recall_drug(batch_code: str, reason: str, db: AsyncSession = Depends(get_db)):
    """Issue a drug recall (admin / NAFDAC action)."""
    result = await db.execute(
        select(models.Drug).where(models.Drug.batch_code == batch_code.upper())
    )
    drug = result.scalar_one_or_none()
    if not drug:
        raise HTTPException(status_code=404, detail="Drug batch not found.")
    drug.is_recalled  = True
    drug.recall_reason = reason
    await db.commit()
    logger.warning("Drug batch recalled", extra={"batch_code": batch_code, "reason": reason})
    return {"message": f"Batch {batch_code} recalled.", "reason": reason}


@router.get("/{batch_code}/verifications")
async def get_verification_history(batch_code: str, db: AsyncSession = Depends(get_db)):
    """Audit trail of all verifications for a drug batch."""
    result = await db.execute(
        select(models.DrugVerification)
        .where(models.DrugVerification.batch_code == batch_code.upper())
        .order_by(models.DrugVerification.created_at.desc())
    )
    verifications = result.scalars().all()
    return [
        {
            "verified_by":    v.verified_by_phone,
            "channel":        v.verification_channel,
            "result":         v.result,
            "location_match": v.camara_location_match,
            "alert_sent":     v.alert_sent,
            "trust_score":    v.trust_score_at_time,
            "timestamp":      v.created_at,
        }
        for v in verifications
    ]


# ── Facilities ────────────────────────────────────────────────────────────────

@router.post("/facilities", response_model=schemas.FacilityOut,
             status_code=status.HTTP_201_CREATED, tags=["Facilities"])
async def register_facility(payload: schemas.FacilityCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.Facility).where(models.Facility.facility_code == payload.facility_code)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Facility code already registered.")
    facility = models.Facility(**payload.model_dump())
    db.add(facility)
    await db.commit()
    await db.refresh(facility)
    logger.info("Facility registered", extra={"facility_code": facility.facility_code})
    return facility


@router.get("/facilities/search", tags=["Facilities"])
async def search_facilities(region: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.Facility).where(
            models.Facility.is_active == True,
            models.Facility.region.ilike(f"%{region}%"),
        ).limit(10)
    )
    return [schemas.FacilityOut.model_validate(f) for f in result.scalars().all()]


import asyncio  # noqa: E402 — needed for gather in verify_drug
