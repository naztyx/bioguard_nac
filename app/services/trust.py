"""
Trust Score Engine
"Unknown" fallback policies:
  SIM swap    → HARD. unknown = fail-closed (block, score → CRITICAL).
  Number      → HARD. unknown = fail-closed (−20, flag).
  Device      → SOFT. unknown = fail-open   (−5, allow + monitor).
  Location    → SOFT. unknown = fail-open   (no deduction, flag only).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.services.camara import (
    run_identity_checks, verify_location,
    EarlyExitFraudSignal,
)
from app.logger import get_logger

logger = get_logger("trust")

MAX_SCORE = 100.0
MIN_SCORE = 0.0

WEIGHTS = {
    "sim_swap_recent":      -40,
    "sim_swap_old":         -15,
    "sim_swap_unknown":     -40,   # unknown = fail-closed, treat as swapped
    "number_not_verified":  -20,
    "number_unknown":       -20,   # hard signal — unknown = fail-closed
    "device_inactive":      -15,
    "device_unknown":        -5,   # soft signal — small penalty + flag
    "location_mismatch":    -25,
    "location_unknown":       0,   # soft signal — flag only, no score deduction
    "repeated_fraud_flag":  -30,
    "verified_interaction":  +5,
}

ACTION_MESSAGES = {
    "HIGH":     "Proceed. All checks passed.",
    "MEDIUM":   "Proceed with standard monitoring.",
    "LOW":      "Flag for secondary confirmation before proceeding.",
    "CRITICAL": "BLOCKED. Escalate to facility security immediately.",
}


def _clamp(score: float) -> float:
    return max(MIN_SCORE, min(MAX_SCORE, score))


def trust_level(score: float) -> str:
    if score >= 90: return "HIGH"
    if score >= 70: return "MEDIUM"
    if score >= 40: return "LOW"
    return "CRITICAL"


def recommendation(score: float) -> str:
    return {
        "HIGH": "allow", "MEDIUM": "allow",
        "LOW":  "flag",  "CRITICAL": "block",
    }[trust_level(score)]


async def evaluate_identity(
    phone_number:  str,
    db:            AsyncSession,
    entity_type:   str = "patient",
    location_lat:  float = None,
    location_lng:  float = None,
) -> dict:
    """
    Full identity evaluation with SIM-swap-first pattern.
    Returns a complete evaluation dict including all signal details.
    """
    logger.info("Identity evaluation started",
                extra={"phone": phone_number[-4:], "entity": entity_type})

    # Fetch current score
    if entity_type == "worker":
        res = await db.execute(select(models.HealthcareWorker).where(
            models.HealthcareWorker.phone_number == phone_number))
    else:
        res = await db.execute(select(models.Patient).where(
            models.Patient.phone_number == phone_number))
    entity     = res.scalar_one_or_none()
    base_score = entity.trust_score if entity else 80.0
    delta      = 0.0
    events     = []
    flags      = []   # soft-signal warnings that don't block but are logged

    sim_swap_detected = False
    sim_swap_date     = None
    number_verified   = True
    device_status     = "active"
    location_consistent = True

    try:
        # ── STEP 1: SIM swap (hard, cheap, first) ────────────────────────
        checks = await run_identity_checks(phone_number)
        ss = checks["sim_swap"]
        nv = checks["number_verification"]
        ds = checks["device_status"]

        # SIM swap evaluation
        sim_swap_detected = ss.swapped
        sim_swap_date     = ss.swap_date
        if ss.swapped:
            w = WEIGHTS["sim_swap_recent"] if (ss.days_since_swap or 999) < 7 \
                else WEIGHTS["sim_swap_old"]
            delta += w
            events.append("sim_swap_recent" if w == WEIGHTS["sim_swap_recent"] else "sim_swap_old")

        # Number verification (hard signal, parallel result)
        number_verified = nv.verified
        if nv.unknown:
            delta += WEIGHTS["number_unknown"]
            events.append("number_unknown")
            flags.append("Number verification returned UNKNOWN — failing closed")
        elif not nv.verified:
            delta += WEIGHTS["number_not_verified"]
            events.append("number_not_verified")

        # Device status (soft signal, fail-open)
        device_status = ds.status
        if ds.unknown:
            delta += WEIGHTS["device_unknown"]
            flags.append("Device status UNKNOWN — soft penalty applied, proceeding")
        elif not ds.reachable:
            delta += WEIGHTS["device_inactive"]
            events.append("device_inactive")

    except EarlyExitFraudSignal as e:
        # SIM swap or unknown triggered early exit — no further calls made
        ss = e.result
        sim_swap_detected = ss.swapped or ss.unknown
        sim_swap_date     = ss.swap_date

        if ss.unknown:
            delta += WEIGHTS["sim_swap_unknown"]
            events.append("sim_swap_unknown")
            logger.warning("SIM swap UNKNOWN — failing closed, early exit",
                           extra={"phone": phone_number[-4:]})
        else:
            w = WEIGHTS["sim_swap_recent"] if (ss.days_since_swap or 999) < 7 \
                else WEIGHTS["sim_swap_old"]
            delta += w
            events.append("sim_swap_recent" if w == WEIGHTS["sim_swap_recent"] else "sim_swap_old")
            logger.warning("SIM swap detected — early exit triggered",
                           extra={"phone": phone_number[-4:],
                                  "days_since_swap": ss.days_since_swap})

    # ── STEP 3: Location (soft, only when coords provided) ────────────────
    if location_lat is not None and location_lng is not None:
        lv = await verify_location(phone_number, location_lat, location_lng)
        location_consistent = lv.match
        if lv.unknown:
            delta += WEIGHTS["location_unknown"]
            flags.append("Location UNKNOWN — stale data, flagged but not penalised")
        elif not lv.match:
            delta += WEIGHTS["location_mismatch"]
            events.append("location_mismatch")

    # Positive reinforcement if completely clean
    if not events and not flags:
        delta += WEIGHTS["verified_interaction"]

    new_score = _clamp(base_score + delta)
    level     = trust_level(new_score)

    logger.info("Identity evaluation complete",
                extra={"phone": phone_number[-4:], "score": new_score,
                       "level": level, "events": events, "flags": flags})

    # Persist score update
    if entity and delta != 0:
        entity.trust_score = new_score
        await db.commit()

    # Log trust event
    if events or flags:
        db.add(models.TrustEvent(
            phone_number=phone_number,
            entity_type=entity_type,
            event_type=", ".join(events) if events else "soft_flags_only",
            score_delta=delta,
            new_score=new_score,
            meta={
                "sim_swap_detected":  sim_swap_detected,
                "sim_swap_date":      sim_swap_date,
                "number_verified":    number_verified,
                "device_status":      device_status,
                "location_consistent": location_consistent,
                "flags":              flags,
            },
        ))
        await db.commit()

    return {
        "phone_number":         phone_number,
        "trust_score":          new_score,
        "trust_level":          level,
        "number_verified":      number_verified,
        "sim_swap_detected":    sim_swap_detected,
        "sim_swap_date":        sim_swap_date,
        "device_status":        device_status,
        "location_consistent":  location_consistent,
        "recommendation":       recommendation(new_score),
        "action_message":       ACTION_MESSAGES[level],
        "score_delta":          delta,
        "triggered_events":     events,
        "soft_flags":           flags,
    }


async def apply_manual_penalty(
    phone_number: str,
    entity_type:  str,
    reason:       str,
    delta:        float,
    db:           AsyncSession,
) -> float:
    if entity_type == "worker":
        res = await db.execute(select(models.HealthcareWorker).where(
            models.HealthcareWorker.phone_number == phone_number))
    else:
        res = await db.execute(select(models.Patient).where(
            models.Patient.phone_number == phone_number))
    entity = res.scalar_one_or_none()
    if not entity:
        return 0.0
    new_score = _clamp(entity.trust_score + delta)
    entity.trust_score = new_score
    db.add(models.TrustEvent(
        phone_number=phone_number, entity_type=entity_type,
        event_type=reason, score_delta=delta, new_score=new_score,
        meta={"manual": True, "reason": reason},
    ))
    await db.commit()
    logger.warning("Manual penalty applied",
                   extra={"phone": phone_number[-4:], "delta": delta,
                          "new_score": new_score, "reason": reason})
    return new_score
