from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from datetime import datetime
from math import radians, sin, cos, sqrt, atan2

from app.database import get_db
from app import models, schemas
from app.services import camara as camara_service
from app.logger import get_logger

logger = get_logger("routers.emergency")
router = APIRouter(prefix="/emergency", tags=["Emergency Response Module"])


# ── Haversine ─────────────────────────────────────────────────────────────────

def _haversine_km(lat1, lng1, lat2, lng2) -> float:
    R = 6371
    la1, lo1 = radians(lat1), radians(lng1)
    la2, lo2 = radians(lat2), radians(lng2)
    dlat, dlng = la2 - la1, lo2 - lo1
    a = sin(dlat / 2) ** 2 + cos(la1) * cos(la2) * sin(dlng / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


async def _nearest_facility(lat, lng, db: AsyncSession, facility_type=None) -> Optional[models.Facility]:
    query = select(models.Facility).where(
        models.Facility.is_active == True,
        models.Facility.location_lat.isnot(None),
        models.Facility.location_lng.isnot(None),
    )
    if facility_type:
        query = query.where(models.Facility.facility_type == facility_type)
    result    = await db.execute(query)
    facilities = result.scalars().all()
    if not facilities:
        return None
    return min(facilities, key=lambda f: _haversine_km(lat, lng, f.location_lat, f.location_lng))


# ─────────────────────────────────────────────────────────────────────────────
# STATIC ROUTES — must come before /{emergency_id}
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/stats/summary")
async def emergency_stats(db: AsyncSession = Depends(get_db)):
    """Real-time dashboard stats for the emergency coordination centre."""
    from sqlalchemy import func as sqlfunc
    results = {}
    for s in ("pending", "dispatched", "resolved", "cancelled"):
        r = await db.execute(
            select(models.EmergencyRequest).where(models.EmergencyRequest.status == s)
        )
        results[s] = len(r.scalars().all())

    by_type = {}
    for etype in ("medical", "drug_reaction", "ambulance", "mental_health"):
        r = await db.execute(
            select(models.EmergencyRequest).where(
                models.EmergencyRequest.emergency_type == etype
            )
        )
        by_type[etype] = len(r.scalars().all())

    all_r  = await db.execute(select(models.EmergencyRequest))
    total  = len(all_r.scalars().all())

    return {
        "total":      total,
        "pending":    results["pending"],
        "dispatched": results["dispatched"],
        "resolved":   results["resolved"],
        "cancelled":  results["cancelled"],
        "by_type":    by_type,
    }


@router.get("/by-phone/{phone_number}", response_model=List[schemas.EmergencyOut])
async def get_emergencies_by_phone(phone_number: str, db: AsyncSession = Depends(get_db)):
    """All emergencies for a phone number, newest first."""
    result = await db.execute(
        select(models.EmergencyRequest)
        .where(models.EmergencyRequest.phone_number == phone_number)
        .order_by(models.EmergencyRequest.created_at.desc())
    )
    return result.scalars().all()


@router.get("/locate/{phone_number}")
async def locate_device(phone_number: str, db: AsyncSession = Depends(get_db)):
    """
    Live device location via CAMARA + nearest hospital.
    Used by dispatchers and ambulance coordinators.
    """
    loc     = await camara_service.retrieve_location(phone_number)
    nearest = await _nearest_facility(loc.lat, loc.lng, db, facility_type="hospital")

    distance_km = None
    if nearest and nearest.location_lat:
        distance_km = round(_haversine_km(loc.lat, loc.lng,
                                          nearest.location_lat, nearest.location_lng), 2)

    logger.info("Device located", extra={
        "phone":               phone_number[-4:],
        "lat":                 loc.lat,
        "lng":                 loc.lng,
        "accuracy_m":          loc.accuracy_meters,
        "nearest_hospital":    nearest.name if nearest else None,
        "nearest_hospital_km": distance_km,
    })

    return {
        "phone_number":        phone_number,
        "latitude":            loc.lat,
        "longitude":           loc.lng,
        "accuracy_meters":     loc.accuracy_meters,
        "civic_address":       loc.civic_address,
        "maps_link":           f"https://maps.google.com/?q={loc.lat},{loc.lng}",
        "nearest_hospital":    nearest.name if nearest else None,
        "nearest_hospital_km": distance_km,
        "nearest_phone":       nearest.phone_number if nearest else None,
    }


@router.post("/qos/{phone_number}")
async def activate_priority_network(phone_number: str, profile: str = "QOS_L"):
    """
    Activate CAMARA QoS on Demand priority session.
    QOS_S = standard | QOS_M = medium | QOS_L = high (emergency use)
    """
    valid = {"QOS_S", "QOS_M", "QOS_L"}
    if profile not in valid:
        raise HTTPException(status_code=422, detail=f"profile must be one of: {sorted(valid)}")
    qos = await camara_service.create_qos_session(phone_number, profile=profile)
    logger.info("QoS session activated manually", extra={"phone": phone_number[-4:], "profile": profile})
    return {
        "phone_number": phone_number,
        "session_id":   qos.session_id,
        "profile":      qos.profile,
        "active":       qos.active,
        "expires_at":   qos.expires_at,
    }


# ─────────────────────────────────────────────────────────────────────────────
# COLLECTION ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/", response_model=schemas.EmergencyOut, status_code=status.HTTP_201_CREATED)
async def create_emergency(payload: schemas.EmergencyCreate, db: AsyncSession = Depends(get_db)):
    """
    Log and dispatch an emergency. Full pipeline:
    1. CAMARA retrieves live patient location (tower triangulation — no GPS/internet needed)
    2. CAMARA activates QoS priority network session simultaneously
    3. Haversine finds geographically nearest hospital in DB
    4. Patient name populated from DB if not provided
    5. Maps link generated — instantly usable by dispatcher
    6. Full record persisted with all location metadata
    """
    logger.warning("Emergency request received", extra={
        "phone": payload.phone_number[-4:],
        "type":  payload.emergency_type,
    })

    # Get patient region for realistic simulated location
    p_result = await db.execute(
        select(models.Patient).where(models.Patient.phone_number == payload.phone_number)
    )
    patient = p_result.scalar_one_or_none()
    region  = (patient.region or "Lagos") if patient else "Lagos"

    # Run CAMARA location + QoS in parallel
    import asyncio
    location, qos = await asyncio.gather(
        camara_service.retrieve_location(payload.phone_number, region=region),
        camara_service.create_qos_session(payload.phone_number, profile="QOS_L"),
    )

    # Prefer caller-supplied GPS coords over network-triangulated
    lat     = payload.location_lat     or location.lat
    lng     = payload.location_lng     or location.lng
    address = payload.location_address or location.civic_address

    # Nearest hospital by actual distance
    nearest      = await _nearest_facility(lat, lng, db, facility_type="hospital")
    if not nearest:
        nearest  = await _nearest_facility(lat, lng, db)

    assigned_name  = nearest.name          if nearest else "National Emergency Services"
    assigned_code  = nearest.facility_code if nearest else None
    assigned_phone = nearest.phone_number  if nearest else None
    distance_km    = (
        round(_haversine_km(lat, lng, nearest.location_lat, nearest.location_lng), 2)
        if nearest and nearest.location_lat else None
    )

    patient_name = payload.patient_name or (patient.full_name if patient else None)

    emergency = models.EmergencyRequest(
        phone_number            = payload.phone_number,
        patient_name            = patient_name,
        emergency_type          = payload.emergency_type,
        location_lat            = lat,
        location_lng            = lng,
        location_address        = address,
        location_accuracy_m     = location.accuracy_meters,
        maps_link               = f"https://maps.google.com/?q={lat},{lng}",
        status                  = "pending",
        assigned_facility       = assigned_name,
        assigned_facility_code  = assigned_code,
        distance_to_facility_km = distance_km,
        qos_session_id          = qos.session_id,
        notes                   = payload.notes or (
            f"Emergency logged via API. "
            f"CAMARA accuracy: {location.accuracy_meters}m. "
            f"QoS: {qos.session_id}. "
            f"Dispatching to: {assigned_name}"
            + (f" ({distance_km}km, tel: {assigned_phone})." if distance_km else ".")
        ),
    )
    db.add(emergency)
    await db.commit()
    await db.refresh(emergency)

    logger.warning("Emergency dispatched", extra={
        "emergency_id":   emergency.id,
        "phone":          payload.phone_number[-4:],
        "type":           payload.emergency_type,
        "assigned":       assigned_name,
        "distance_km":    distance_km,
        "accuracy_m":     location.accuracy_meters,
        "qos_session":    qos.session_id,
    })
    return emergency


@router.get("/", response_model=List[schemas.EmergencyOut])
async def list_emergencies(
    status_filter: str = None,
    skip:          int = 0,
    limit:         int = 50,
    db:            AsyncSession = Depends(get_db),
):
    query = select(models.EmergencyRequest).order_by(
        models.EmergencyRequest.created_at.desc()
    )
    if status_filter:
        query = query.where(models.EmergencyRequest.status == status_filter)
    result = await db.execute(query.offset(skip).limit(limit))
    return result.scalars().all()


# ─────────────────────────────────────────────────────────────────────────────
# PARAMETERIZED ROUTES — after all static paths
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{emergency_id}", response_model=schemas.EmergencyOut)
async def get_emergency(emergency_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.EmergencyRequest).where(models.EmergencyRequest.id == emergency_id)
    )
    em = result.scalar_one_or_none()
    if not em:
        raise HTTPException(status_code=404, detail="Emergency request not found.")
    return em


@router.patch("/{emergency_id}/status", response_model=schemas.EmergencyOut)
async def update_emergency_status(
    emergency_id: int,
    payload:      schemas.EmergencyUpdateStatus,
    db:           AsyncSession = Depends(get_db),
):
    """
    Update emergency status. Enforced state machine:
      pending    → dispatched | cancelled
      dispatched → resolved   | cancelled
      resolved   → (terminal)
      cancelled  → (terminal)
    """
    result = await db.execute(
        select(models.EmergencyRequest).where(models.EmergencyRequest.id == emergency_id)
    )
    em = result.scalar_one_or_none()
    if not em:
        raise HTTPException(status_code=404, detail="Emergency not found.")

    TRANSITIONS = {
        "pending":    {"dispatched", "cancelled"},
        "dispatched": {"resolved",   "cancelled"},
        "resolved":   set(),
        "cancelled":  set(),
    }
    allowed = TRANSITIONS.get(em.status, set())
    if payload.status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot transition '{em.status}' → '{payload.status}'. "
                f"Allowed: {sorted(allowed) or 'none — terminal state'}."
            ),
        )

    prev_status   = em.status
    em.status     = payload.status
    if payload.assigned_facility:
        em.assigned_facility = payload.assigned_facility
    if payload.notes:
        em.notes = (em.notes or "") + f" | {payload.notes}"
    if payload.status == "resolved":
        em.resolved_at = datetime.utcnow()

    await db.commit()
    await db.refresh(em)

    logger.info("Emergency status updated", extra={
        "emergency_id": emergency_id,
        "from":         prev_status,
        "to":           payload.status,
    })
    return em
