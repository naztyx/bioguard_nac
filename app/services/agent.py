import asyncio
import json
import re
import httpx
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.services import camara as camara_service
from app.services.camara import EarlyExitFraudSignal
from app.services.trust import trust_level, _clamp, WEIGHTS
from app.config import get_settings
from app.logger import get_logger

logger   = get_logger("agent")
settings = get_settings()

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
# CLAUDE_MODEL      = "claude-sonnet-4-20250514"
CLAUDE_MODEL = "claude-haiku-4-5"

anthropic_client = httpx.AsyncClient(
    timeout=httpx.Timeout(
        connect=20.0,
        read=120.0,
        write=60.0,
        pool=60.0,
    ),
    limits=httpx.Limits(
        max_connections=50,
        max_keepalive_connections=20,
        keepalive_expiry=30.0,
    ),
    http2=False,
)

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are BioGuard AI. Evaluate CAMARA signals and return ONLY this JSON — no markdown, no extra text:
 
{
  "decision":        "approve" | "flag" | "block" | "escalate",
  "confidence":      <0.0–1.0>,
  "reasoning":       "<one sentence>",
  "action":          "<one sentence for the operator>",
  "risk_factors":    ["<short phrase>"],
  "recommendations": ["<short phrase>"]
}
 
Rules: approve=clean, flag=minor risk, block=high risk, escalate=emergency.
Be terse. One sentence per field. No explanations outside the JSON."""


# ─────────────────────────────────────────────────────────────────────────────
# Signal collectors
# ─────────────────────────────────────────────────────────────────────────────

async def _collect_identity_signals(phone: str, region: str = "Lagos") -> dict:
    """
    cal SIM swap first (hard signal, cheapest disqualifier).
    If swapped/unknown → EarlyExitFraudSignal raised — no further calls.
    If clean → Number Verify + Device Status in parallel.
    """
    try:
        checks = await camara_service.run_identity_checks(phone)
        ss = checks["sim_swap"]
        nv = checks["number_verification"]
        ds = checks["device_status"]
        return {
            "number_verified":    nv.verified,
            "number_unknown":     nv.unknown,
            "sim_swap_detected":  ss.swapped,
            "sim_swap_unknown":   ss.unknown,
            "sim_swap_days_ago":  ss.days_since_swap,
            "device_status":      ds.status,
            "device_reachable":   ds.reachable,
            "device_unknown":     ds.unknown,
            "early_exit":         False,
        }
    except EarlyExitFraudSignal as e:
        ss = e.result
        logger.warning("Agent: early exit triggered by SIM swap signal",
                       extra={"phone": phone[-4:], "unknown": ss.unknown})
        return {
            "number_verified":   False,
            "number_unknown":    False,
            "sim_swap_detected": ss.swapped or ss.unknown,
            "sim_swap_unknown":  ss.unknown,
            "sim_swap_days_ago": ss.days_since_swap,
            "device_status":     "not_checked",
            "device_reachable":  False,
            "device_unknown":    False,
            "early_exit":        True,
        }


async def _collect_location_signals(
    phone:        str,
    expected_lat: Optional[float] = None,
    expected_lng: Optional[float] = None,
    region:       str = "Lagos",
) -> dict:
    """Retrieve live location and optionally verify against expected coords."""
    loc = await camara_service.retrieve_location(phone, region=region)
    signals = {
        "live_lat":          loc.lat,
        "live_lng":          loc.lng,
        "accuracy_meters":   loc.accuracy_meters,
        "civic_address":     loc.civic_address,
        "maps_link":         f"https://maps.google.com/?q={loc.lat},{loc.lng}",
        "geofence_checked":  False,
        "geofence_match":    None,
        "geofence_distance_km": None,
    }
    if expected_lat is not None and expected_lng is not None:
        lv = await camara_service.verify_location(phone, expected_lat, expected_lng)
        signals.update({
            "geofence_checked":     True,
            "geofence_match":       lv.match,
            "geofence_confidence":  lv.confidence,
            "geofence_distance_km": lv.distance_km,
        })
    return signals


async def _collect_network_signals(phone: str) -> dict:
    """Activate and capture QoS session status."""
    qos = await camara_service.create_qos_session(phone, profile="QOS_L")
    return {
        "qos_session_id":  qos.session_id,
        "qos_profile":     qos.profile,
        "qos_active":      qos.active,
        "qos_expires_at":  qos.expires_at,
    }


def _compute_trust_delta(identity: dict) -> tuple[float, list[str]]:
    """Compute trust score delta from raw CAMARA signals."""
    delta  = 0.0
    events = []
    if not identity["number_verified"]:
        delta += WEIGHTS["number_not_verified"]
        events.append("number_not_verified")
    if identity["sim_swap_detected"]:
        days = identity.get("sim_swap_days_ago") or 999
        if days < 7:
            delta += WEIGHTS["sim_swap_recent"]
            events.append("sim_swap_recent")
        else:
            delta += WEIGHTS["sim_swap_old"]
            events.append("sim_swap_old")
    if not identity["device_reachable"]:
        delta += WEIGHTS["device_inactive"]
        events.append("device_inactive")
    return delta, events


# ─────────────────────────────────────────────────────────────────────────────
# Claude decision engine
# ─────────────────────────────────────────────────────────────────────────────

async def _call_claude(context_payload: dict) -> dict:
    """
    Send assembled signal payload to Claude and parse the structured decision.
    Falls back to a rule-based decision if the API call fails.
    """
    prompt = (
        f"Evaluate this BioGuard signal payload and return your decision as JSON:\n\n"
        f"{json.dumps(context_payload, indent=2, default=str)}"
    )


    try:
        response = await anthropic_client.post(
            ANTHROPIC_API_URL,
            headers={
                "Content-Type": "application/json",
                "x-api-key": settings.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 1000,
                "temperature": 0,
                "system": SYSTEM_PROMPT,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            },
        )

        if response.status_code != 200:

            logger.error(
                "Claude API returned non-200 response",
                extra={
                    "status_code": response.status_code,
                    "response_body": response.text[:500],
                },
            )

            return _fallback_decision(context_payload)

        data = response.json()

        content = (
            data.get("content", [{}])[0]
            .get("text", "")
            .strip()
        )

        if not content:

            logger.error("Claude returned empty content")

            return _fallback_decision(context_payload)

        # Remove markdown fences safely
        clean = re.sub(
            r"^```(?:json)?|```$",
            "",
            content,
            flags=re.MULTILINE,
        ).strip()

        try:

            decision = json.loads(clean)

        except json.JSONDecodeError:

            logger.error(
                "Failed to parse Claude JSON response",
                extra={
                    "raw_response": clean[:1000]
                },
            )

            return _fallback_decision(context_payload)

        logger.info(
            "Claude decision received",
            extra={
                "decision": decision.get("decision"),
                "confidence": decision.get("confidence"),
            },
        )

        return decision

    except (
        httpx.ReadTimeout,
        httpx.ConnectTimeout,
        httpx.ConnectError,
        httpx.RemoteProtocolError,
    ) as exc:

        logger.warning(
            "Claude API unreachable — using fallback decision",
            exc_info=exc,
        )

        return _fallback_decision(context_payload)

    except Exception as exc:

        logger.exception(
            "Unexpected Claude API failure",
            exc_info=exc,
        )

        return _fallback_decision(context_payload)

async def _call_deepseek(context_payload: dict) -> dict:
    prompt = (
        "Evaluate this BioGuard signal payload and return JSON only:\n\n"
        f"{json.dumps(context_payload, separators=(',', ':'), default=str)}"
    )

    try:

        response = await anthropic_client.post(
            "https://api.deepseek.com/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
            },
            json={
                "model": "deepseek-chat",
                "temperature": 0,
                "max_tokens": 1000,
                "response_format": {
                    "type": "json_object"
                },
                "messages": [
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            },
        )

        if response.status_code != 200:

            logger.error(
                "DeepSeek API returned non-200 response",
                extra={
                    "status_code": response.status_code,
                    "response_body": response.text[:500],
                },
            )

            return _fallback_decision(context_payload)

        data = response.json()

        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )

        if not content:

            logger.error(
                "DeepSeek returned empty content"
            )

            return _fallback_decision(context_payload)

        # Remove markdown fences safely
        clean = re.sub(
            r"^```(?:json)?|```$",
            "",
            content,
            flags=re.MULTILINE,
        ).strip()

        try:

            decision = json.loads(clean)

        except json.JSONDecodeError:

            logger.error(
                "Failed to parse DeepSeek JSON response",
                extra={
                    "raw_response": clean[:1000],
                },
            )

            return _fallback_decision(context_payload)

        logger.info(
            "DeepSeek decision received",
            extra={
                "decision": decision.get("decision"),
                "confidence": decision.get("confidence"),
            },
        )

        return decision

    except (
        httpx.ReadTimeout,
        httpx.ConnectTimeout,
        httpx.ConnectError,
        httpx.RemoteProtocolError,
    ) as exc:

        logger.warning(
            "DeepSeek API unreachable — using fallback decision",
            exc_info=exc,
        )

        return _fallback_decision(context_payload)

    except Exception as exc:

        logger.exception(
            "Unexpected DeepSeek API failure",
            exc_info=exc,
        )

        return _fallback_decision(context_payload)

def _fallback_decision(payload: dict) -> dict:
    """
    Rule-based fallback used when Claude API is unavailable.
    Uses trust score and signal flags directly.
    """
    trust_score = payload.get("trust_score", 100.0)
    level       = trust_level(trust_score)
    sim_swap    = payload.get("identity_signals", {}).get("sim_swap_detected", False)
    num_verify  = payload.get("identity_signals", {}).get("number_verified", True)
    geo_match   = payload.get("location_signals", {}).get("geofence_match")

    risks = []
    if sim_swap:       risks.append("SIM swap detected")
    if not num_verify: risks.append("Phone number not verified")
    if geo_match is False: risks.append("Location geofence failed")

    decision_map = {
        "HIGH":     "approve",
        "MEDIUM":   "flag",
        "LOW":      "block",
        "CRITICAL": "block",
    }

    return {
        "decision":        decision_map[level],
        "confidence":      min(trust_score / 100, 0.95),
        "reasoning":       f"Rule-based fallback (Claude unavailable). Trust level: {level}. Score: {trust_score:.0f}/100.",
        "action":          f"{'Proceed with caution.' if level in ('HIGH','MEDIUM') else 'Do NOT proceed. Escalate to supervisor.'}",
        "risk_factors":    risks or ["No significant risks detected"],
        "recommendations": ["Re-run verification when Claude API is available."],
        "fallback":        True,
    }


async def _persist_decision(
    phone:       str,
    entity_type: str,
    action_type: str,
    delta:       float,
    new_score:   float,
    decision:    dict,
    db:          AsyncSession,
) -> None:
    """Persist the agent's decision as a TrustEvent for full audit trail."""
    db.add(models.TrustEvent(
        phone_number = phone,
        entity_type  = entity_type,
        event_type   = f"agent_{action_type}_{decision['decision']}",
        score_delta  = delta,
        new_score    = new_score,
        meta         = {
            "agent_decision":    decision.get("decision"),
            "confidence":        decision.get("confidence"),
            "reasoning":         decision.get("reasoning"),
            "action":            decision.get("action"),
            "risk_factors":      decision.get("risk_factors"),
            "recommendations":   decision.get("recommendations"),
            "fallback":          decision.get("fallback", False),
            "timestamp":         datetime.utcnow().isoformat(),
        },
    ))
    await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Public agent actions
# ─────────────────────────────────────────────────────────────────────────────

async def evaluate_drug_dispensation(
    phone_number:  str,
    batch_code:    str,
    facility_code: str,
    facility_lat:  Optional[float],
    facility_lng:  Optional[float],
    db:            AsyncSession,
) -> dict:
    """
    Agentic decision: should this drug be dispensed to this patient?

    Runs in parallel:
      - Identity signals (number verify, SIM swap, device status)
      - Location signals (live location + geofence against facility)
      - Drug record lookup
      - Network QoS capture

    Claude evaluates all signals together and decides: approve | flag | block
    """
    logger.info("Agent: evaluating drug dispensation", extra={
        "phone": phone_number[-4:], "batch_code": batch_code,
        "facility": facility_code,
    })

    # Fetch patient and drug records
    p_res = await db.execute(
        select(models.Patient).where(models.Patient.phone_number == phone_number)
    )
    patient = p_res.scalar_one_or_none()
    region  = patient.region if patient else "Lagos"

    d_res = await db.execute(
        select(models.Drug).where(models.Drug.batch_code == batch_code)
    )
    drug = d_res.scalar_one_or_none()

    # Run all CAMARA signals in parallel
    identity_signals, location_signals, network_signals = await asyncio.gather(
        _collect_identity_signals(phone_number, region),
        _collect_location_signals(phone_number, facility_lat, facility_lng, region),
        _collect_network_signals(phone_number),
    )

    # Compute trust delta
    delta, triggered = _compute_trust_delta(identity_signals)
    base_score       = patient.trust_score if patient else 80.0
    new_score        = _clamp(base_score + delta)

    # Drug safety signals
    drug_signals = {
        "batch_code":             batch_code,
        "drug_found":             drug is not None,
        "drug_name":              drug.drug_name if drug else None,
        "is_recalled":            drug.is_recalled if drug else None,
        "expiry_date":            drug.expiry_date if drug else None,
        "cold_chain_required":    drug.cold_chain_required if drug else False,
        "facility_authorized":    (
            facility_code in drug.authorized_facility_codes
            if drug and drug.authorized_facility_codes else None
        ),
        "nafdac_number":          drug.nafdac_number if drug else None,
    }

    # Assemble full context for Claude
    context = {
        "action":            "drug_dispensation_request",
        "timestamp":         datetime.utcnow().isoformat(),
        "patient": {
            "phone_last4":   phone_number[-4:],
            "health_id":     patient.health_id if patient else "UNREGISTERED",
            "region":        region,
            "trust_score":   new_score,
            "trust_level":   trust_level(new_score),
        },
        "identity_signals":  identity_signals,
        "location_signals":  location_signals,
        "network_signals":   network_signals,
        "drug_signals":      drug_signals,
        "trust_score":       new_score,
        "triggered_events":  triggered,
    }

    decision = await _call_deepseek(context)

    # Update patient trust score and persist event
    if patient and delta != 0:
        patient.trust_score = new_score
        await db.commit()
    await _persist_decision(
        phone_number, "patient", "drug_dispensation",
        delta, new_score, decision, db,
    )

    logger.warning(
        "Agent drug dispensation decision",
        extra={
            "phone":      phone_number[-4:],
            "batch_code": batch_code,
            "decision":   decision["decision"],
            "confidence": decision["confidence"],
            "trust":      new_score,
        },
    ) if decision["decision"] in ("block", "flag") else logger.info(
        "Agent drug dispensation decision",
        extra={"decision": decision["decision"], "batch_code": batch_code},
    )

    return {
        "action":            "drug_dispensation",
        "phone_number":      phone_number,
        "batch_code":        batch_code,
        "facility_code":     facility_code,
        "trust_score":       new_score,
        "trust_level":       trust_level(new_score),
        "identity_signals":  identity_signals,
        "location_signals":  location_signals,
        "drug_signals":      drug_signals,
        "agent_decision":    decision,
    }


async def evaluate_worker_authentication(
    worker_id:    str,
    verifier_phone: str,
    db:           AsyncSession,
) -> dict:
    """
    Agentic decision: is this healthcare worker legitimate?

    Runs in parallel:
      - Worker's identity signals (SIM swap, number verify, device)
      - Worker's live location vs their registered facility
      - Network quality assessment

    Claude evaluates the combined picture and decides: approve | flag | block
    """
    logger.info("Agent: evaluating worker authentication", extra={
        "worker_id": worker_id, "verifier": verifier_phone[-4:]
    })

    w_res = await db.execute(
        select(models.HealthcareWorker).where(
            models.HealthcareWorker.worker_id == worker_id.upper()
        )
    )
    worker = w_res.scalar_one_or_none()

    if not worker:
        return {
            "action":         "worker_authentication",
            "worker_id":      worker_id,
            "agent_decision": {
                "decision":    "block",
                "confidence":  1.0,
                "reasoning":   "Worker ID not found in BioGuard registry.",
                "action":      "Do NOT allow this person to perform medical duties.",
                "risk_factors": ["Unregistered worker ID"],
                "recommendations": ["Request official credentials and report to facility manager."],
            },
        }

    # Get worker's facility coordinates for geofence check
    f_res = await db.execute(
        select(models.Facility).where(
            models.Facility.facility_code == worker.facility_code
        )
    )
    facility = f_res.scalar_one_or_none()
    fac_lat  = facility.location_lat if facility else None
    fac_lng  = facility.location_lng if facility else None

    identity_signals, location_signals, network_signals = await asyncio.gather(
        _collect_identity_signals(worker.phone_number),
        _collect_location_signals(worker.phone_number, fac_lat, fac_lng),
        _collect_network_signals(worker.phone_number),
    )

    delta, triggered = _compute_trust_delta(identity_signals)
    new_score        = _clamp(worker.trust_score + delta)

    context = {
        "action":    "worker_authentication_request",
        "timestamp": datetime.utcnow().isoformat(),
        "worker": {
            "worker_id":      worker.worker_id,
            "full_name":      worker.full_name,
            "specialization": worker.specialization,
            "facility":       worker.facility_name,
            "is_verified":    worker.is_verified,
            "trust_score":    new_score,
            "trust_level":    trust_level(new_score),
        },
        "identity_signals":  identity_signals,
        "location_signals":  location_signals,
        "network_signals":   network_signals,
        "trust_score":       new_score,
        "triggered_events":  triggered,
        "verifier_phone_last4": verifier_phone[-4:],
    }

    decision = await _call_deepseek(context)

    # Update worker trust score
    if delta != 0:
        worker.trust_score = new_score
        await db.commit()
    await _persist_decision(
        worker.phone_number, "worker", "authentication",
        delta, new_score, decision, db,
    )

    logger.info("Agent worker authentication decision", extra={
        "worker_id": worker_id,
        "decision":  decision["decision"],
        "confidence": decision["confidence"],
    })

    return {
        "action":           "worker_authentication",
        "worker_id":        worker_id,
        "full_name":        worker.full_name,
        "facility":         worker.facility_name,
        "trust_score":      new_score,
        "trust_level":      trust_level(new_score),
        "identity_signals": identity_signals,
        "location_signals": location_signals,
        "agent_decision":   decision,
    }


async def evaluate_emergency_escalation(
    phone_number:    str,
    emergency_type:  str,
    emergency_id:    int,
    db:              AsyncSession,
) -> dict:
    """
    Agentic decision: how critical is this emergency and what must happen?

    Runs in parallel:
      - Patient identity and device reachability
      - Live location retrieval
      - Priority network activation

    Claude triages the emergency and recommends: approve (standard) | escalate (critical)
    """
    logger.warning("Agent: evaluating emergency escalation", extra={
        "phone": phone_number[-4:], "type": emergency_type, "id": emergency_id
    })

    p_res = await db.execute(
        select(models.Patient).where(models.Patient.phone_number == phone_number)
    )
    patient = p_res.scalar_one_or_none()
    region  = patient.region if patient else "Lagos"

    identity_signals, location_signals, network_signals = await asyncio.gather(
        _collect_identity_signals(phone_number, region),
        _collect_location_signals(phone_number, region=region),
        _collect_network_signals(phone_number),
    )

    # Find nearest hospital for context
    from math import radians, sin, cos, sqrt, atan2
    lat = location_signals["live_lat"]
    lng = location_signals["live_lng"]

    def haversine(f):
        R = 6371
        la1, lo1 = radians(lat), radians(lng)
        la2, lo2 = radians(f.location_lat), radians(f.location_lng)
        d = la2 - la1; dl = lo2 - lo1
        a = sin(d/2)**2 + cos(la1)*cos(la2)*sin(dl/2)**2
        return R * 2 * atan2(sqrt(a), sqrt(1-a))

    f_res     = await db.execute(
        select(models.Facility).where(
            models.Facility.is_active == True,
            models.Facility.facility_type == "hospital",
            models.Facility.location_lat.isnot(None),
        )
    )
    hospitals = f_res.scalars().all()
    nearest   = min(hospitals, key=haversine) if hospitals else None

    context = {
        "action":         "emergency_escalation_assessment",
        "timestamp":      datetime.utcnow().isoformat(),
        "emergency": {
            "id":             emergency_id,
            "type":           emergency_type,
            "patient_phone_last4": phone_number[-4:],
            "patient_name":   patient.full_name if patient else "Unknown",
            "patient_region": region,
            "patient_trust":  patient.trust_score if patient else 80.0,
        },
        "identity_signals":  identity_signals,
        "location_signals":  location_signals,
        "network_signals":   network_signals,
        "nearest_hospital": {
            "name":        nearest.name if nearest else None,
            "phone":       nearest.phone_number if nearest else None,
            "distance_km": round(haversine(nearest), 2) if nearest else None,
        },
        "trust_score": patient.trust_score if patient else 80.0,
    }

    decision = await _call_deepseek(context)

    await _persist_decision(
        phone_number, "patient", "emergency_escalation",
        0.0, patient.trust_score if patient else 80.0, decision, db,
    )

    logger.warning("Agent emergency escalation decision", extra={
        "emergency_id": emergency_id,
        "decision":     decision["decision"],
        "confidence":   decision["confidence"],
    })

    return {
        "action":           "emergency_escalation",
        "emergency_id":     emergency_id,
        "emergency_type":   emergency_type,
        "phone_number":     phone_number,
        "location_signals": location_signals,
        "network_signals":  network_signals,
        "nearest_hospital": context["nearest_hospital"],
        "agent_decision":   decision,
    }


async def detect_suspicious_activity(
    phone_number: str,
    activity:     str,
    context_data: dict,
    db:           AsyncSession,
) -> dict:
    """
    Agentic scan for suspicious activity patterns.
    Used when multiple failed verifications or fraud signals accumulate.

    activity: "multiple_drug_verify_fails" | "repeated_sim_swap" |
              "location_hopping" | "unregistered_dispenser"
    """
    logger.warning("Agent: suspicious activity scan", extra={
        "phone": phone_number[-4:], "activity": activity
    })

    identity_signals, location_signals = await asyncio.gather(
        _collect_identity_signals(phone_number),
        _collect_location_signals(phone_number),
    )

    # Pull trust event history
    te_res = await db.execute(
        select(models.TrustEvent)
        .where(models.TrustEvent.phone_number == phone_number)
        .order_by(models.TrustEvent.created_at.desc())
        .limit(5)
    )
    recent_events = [
        {"event": e.event_type, "delta": e.score_delta, "score": e.new_score}
        for e in te_res.scalars().all()
    ]

    context = {
        "action":            "suspicious_activity_detection",
        "timestamp":         datetime.utcnow().isoformat(),
        "activity_type":     activity,
        "additional_context": context_data,
        "identity_signals":  identity_signals,
        "location_signals":  location_signals,
        "recent_trust_events": recent_events,
    }

    decision = await _call_deepseek(context)

    # Apply fraud penalty if agent decides to block
    if decision["decision"] in ("block", "escalate"):
        p_res = await db.execute(
            select(models.Patient).where(models.Patient.phone_number == phone_number)
        )
        entity = p_res.scalar_one_or_none()
        if not entity:
            w_res = await db.execute(
                select(models.HealthcareWorker).where(
                    models.HealthcareWorker.phone_number == phone_number
                )
            )
            entity = w_res.scalar_one_or_none()

        if entity:
            penalty   = WEIGHTS["repeated_fraud_flag"]
            new_score = _clamp(entity.trust_score + penalty)
            entity.trust_score = new_score
            await db.commit()
            await _persist_decision(
                phone_number,
                "patient" if isinstance(entity, models.Patient) else "worker",
                "suspicious_activity",
                penalty, new_score, decision, db,
            )

    logger.warning("Agent suspicious activity decision", extra={
        "phone":    phone_number[-4:],
        "activity": activity,
        "decision": decision["decision"],
    })

    return {
        "action":           "suspicious_activity_detection",
        "phone_number":     phone_number,
        "activity_type":    activity,
        "identity_signals": identity_signals,
        "location_signals": location_signals,
        "agent_decision":   decision,
    }
