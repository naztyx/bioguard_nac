import asyncio
import random
from datetime import datetime, timedelta
from typing import Optional

from app.config import get_settings
from app.logger import get_logger

logger   = get_logger("camara")
settings = get_settings()

class NumberVerificationResult:
    def __init__(self, verified: bool, unknown: bool = False, message: str = ""):
        self.verified = verified
        self.unknown  = unknown
        self.message  = message


class SIMSwapResult:
    def __init__(self, swapped: bool, swap_date: Optional[str],
                 days_since_swap: Optional[int], unknown: bool = False):
        self.swapped         = swapped
        self.swap_date       = swap_date
        self.days_since_swap = days_since_swap
        self.unknown         = unknown


class DeviceStatusResult:
    def __init__(self, status: str, reachable: bool, unknown: bool = False):
        self.status    = status     # "active" | "inactive" | "unknown"
        self.reachable = reachable
        self.unknown   = unknown    # True = NAC returned stale/no data → soft fail-open


class LocationResult:
    def __init__(self, lat: float, lng: float, accuracy_meters: int,
                 civic_address: str, unknown: bool = False, stale: bool = False):
        self.lat             = lat
        self.lng             = lng
        self.accuracy_meters = accuracy_meters
        self.civic_address   = civic_address
        self.unknown         = unknown  # True = location could not be determined
        self.stale           = stale    # True = data older than requested max_age


class LocationVerificationResult:
    def __init__(self, match: bool, confidence: float,
                 distance_km: float, unknown: bool = False):
        self.match       = match
        self.confidence  = confidence
        self.distance_km = distance_km
        self.unknown     = unknown  # True = PARTIAL or indeterminate → soft fail-open


class QoSSessionResult:
    def __init__(self, session_id: str, profile: str,
                 active: bool, expires_at: str, unknown: bool = False):
        self.session_id = session_id
        self.profile    = profile
        self.active     = active
        self.expires_at = expires_at
        self.unknown    = unknown   # True = session failed → soft fail-open


# ─────────────────────────────────────────────────────────────────────────────
# Early exit signal
# ─────────────────────────────────────────────────────────────────────────────

class EarlyExitFraudSignal(Exception):
    """
    Raised when SIM swap is detected OR returns unknown.
    Callers catch this to stop all further CAMARA calls immediately.
    """
    def __init__(self, result: SIMSwapResult):
        self.result = result
        super().__init__(
            f"SIM swap {'unknown' if result.unknown else 'detected'} "
            f"— early exit, no further CAMARA calls"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Smart orchestration — SIM first, then parallel fan-out
# ─────────────────────────────────────────────────────────────────────────────

async def run_identity_checks(phone: str) -> dict:
    """
    MENTOR-RECOMMENDED PATTERN:
    Step 1: SIM swap alone — hard signal, cheapest call.
            If trips → raise EarlyExitFraudSignal immediately.
    Step 2: If clean → Number Verify + Device Status in parallel.
    """
    logger.debug("Identity check step 1: SIM swap", extra={"phone": phone[-4:]})
    ss = await check_sim_swap(phone)

    # SIM swap is a HARD signal — unknown = fail-closed
    if ss.unknown or ss.swapped:
        logger.warning(
            "SIM swap signal — early exit raised",
            extra={"phone": phone[-4:], "swapped": ss.swapped, "unknown": ss.unknown},
        )
        raise EarlyExitFraudSignal(ss)

    logger.debug("SIM clean — fanning out parallel checks", extra={"phone": phone[-4:]})
    nv, ds = await asyncio.gather(
        verify_number(phone),
        get_device_status(phone),
    )
    return {"number_verification": nv, "sim_swap": ss, "device_status": ds}


# ─────────────────────────────────────────────────────────────────────────────
# Nokia NAC client helper
# ─────────────────────────────────────────────────────────────────────────────

def _get_device(phone_number: str):
    """
    Returns a configured Nokia NAC device object.
    phone_number must be E.164 format: +<country_code><number>
    e.g. +36370000001 (Nokia sandbox) or +2348056001001 (Nigeria)
    """
    try:
        import network_as_code as nac
    except ImportError:
        raise RuntimeError("Run: pip install network-as-code")

    client = nac.NetworkAsCodeClient(token=settings.NAC_TOKEN)
    return client.devices.get(phone_number=phone_number)


# ─────────────────────────────────────────────────────────────────────────────
# Real CAMARA API implementations (NAC_SIMULATE=false)
# ─────────────────────────────────────────────────────────────────────────────

async def _real_number_verification(phone: str) -> NumberVerificationResult:
    def _call():
        try:
            device   = _get_device(phone)
            # Proxy: SIM swap check within 48 hours as number verification signal
            swapped  = device.verify_sim_swap(max_age=2880)
            verified = not swapped
            logger.info("Number verification (NAC proxy via SIM swap)",
                        extra={"phone": phone[-4:], "verified": verified})
            return NumberVerificationResult(
                verified=verified,
                unknown=False,
                message="Verified via Nokia NAC" if verified else "Unverified — SIM swap detected",
            )
        except Exception as exc:
            logger.error("Number verification NAC error — HARD fail-closed",
                         exc_info=exc, extra={"phone": phone[-4:]})
            return NumberVerificationResult(
                verified=False, unknown=True,
                message=f"NAC unavailable — failing closed: {exc}",
            )
    return await asyncio.get_event_loop().run_in_executor(None, _call)


async def _real_sim_swap(phone: str) -> SIMSwapResult:
    """
    Returns the date of the last SIM swap, or None if no swap on record.
    HARD signal: unknown → fail-closed (treated as suspected swap).
    """
    def _call():
        try:
            device   = _get_device(phone)
            swap_dt  = device.get_sim_swap_date()
            if swap_dt is None:
                logger.debug("SIM swap: none on record (NAC)",
                             extra={"phone": phone[-4:]})
                return SIMSwapResult(
                    swapped=False, swap_date=None,
                    days_since_swap=None, unknown=False,
                )
            days = (datetime.utcnow() - swap_dt.replace(tzinfo=None)).days
            logger.warning("SIM swap detected (NAC)",
                           extra={"phone": phone[-4:], "swap_date": str(swap_dt.date()),
                                  "days_ago": days})
            return SIMSwapResult(
                swapped=True,
                swap_date=swap_dt.strftime("%Y-%m-%d"),
                days_since_swap=days,
                unknown=False,
            )
        except Exception as exc:
            logger.error("SIM swap NAC error — HARD fail-closed (treating as unknown swap)",
                         exc_info=exc, extra={"phone": phone[-4:]})
            return SIMSwapResult(
                swapped=False, swap_date=None,
                days_since_swap=None, unknown=True,
            )
    return await asyncio.get_event_loop().run_in_executor(None, _call)


async def _real_device_status(phone: str) -> DeviceStatusResult:
    """
    SOFT signal: unknown → fail-open (−5 penalty, allow + flag).
    """
    def _call():
        try:
            device = _get_device(phone)
            status = device.get_reachability()
            logger.info("Device status (NAC)",
                        extra={"phone": phone[-4:], "reachable": status.reachable,
                               "connectivity": status.connectivity})
            return DeviceStatusResult(
                status="active" if status.reachable else "inactive",
                reachable=status.reachable,
                unknown=False,
            )
        except Exception as exc:
            logger.warning("Device status NAC error — SOFT fail-open",
                           exc_info=exc, extra={"phone": phone[-4:]})
            return DeviceStatusResult(status="unknown", reachable=True, unknown=True)
    return await asyncio.get_event_loop().run_in_executor(None, _call)


async def _real_location_retrieval(phone: str, region: str = "Lagos") -> LocationResult:
    """
    SOFT signal: unknown/stale → fail-open (flag only, no score deduction).
    """
    def _call():
        try:
            device = _get_device(phone)
            loc    = device.location(max_age=60)
            stale  = bool(loc.radius and loc.radius > 5000)
            logger.info("Location retrieved (NAC)",
                        extra={"phone": phone[-4:], "lat": loc.latitude,
                               "lng": loc.longitude, "radius_m": loc.radius,
                               "stale": stale})
            return LocationResult(
                lat=loc.latitude,
                lng=loc.longitude,
                accuracy_meters=int(loc.radius) if loc.radius else 999,
                civic_address=region,
                unknown=False,
                stale=stale,
            )
        except Exception as exc:
            logger.warning("Location retrieval NAC error — SOFT fail-open",
                           exc_info=exc, extra={"phone": phone[-4:]})
            base_lat, base_lng = REGION_COORDS.get(region, REGION_COORDS["default"])
            return LocationResult(
                lat=base_lat, lng=base_lng,
                accuracy_meters=9999,
                civic_address=f"{region} (NAC unavailable)",
                unknown=True,
            )
    return await asyncio.get_event_loop().run_in_executor(None, _call)


async def _real_location_verification(
    phone: str, expected_lat: float, expected_lng: float, radius_km: float,
) -> LocationVerificationResult:
    """
    Note: SDK takes longitude BEFORE latitude — opposite of typical lat/lng order.
    SOFT signal: PARTIAL or error → fail-open (flag, no score deduction).
    """
    def _call():
        try:
            device = _get_device(phone)
            result = device.verify_location(
                longitude = expected_lng,   # SDK: longitude first
                latitude  = expected_lat,
                radius    = radius_km * 1000,  # SDK expects metres
                max_age   = 60,
            )
            match      = result.result_type == "TRUE"
            partial    = result.result_type == "PARTIAL"
            confidence = (result.match_rate or 0) / 100.0
            logger.info("Location verified (NAC)",
                        extra={"phone": phone[-4:], "result": result.result_type,
                               "match_rate": result.match_rate, "radius_km": radius_km})
            return LocationVerificationResult(
                match=match,
                confidence=confidence,
                distance_km=0.0 if match else radius_km + 1,
                unknown=partial,  # PARTIAL = uncertain → treat as soft unknown
            )
        except Exception as exc:
            logger.warning("Location verification NAC error — SOFT fail-open",
                           exc_info=exc, extra={"phone": phone[-4:]})
            return LocationVerificationResult(
                match=True, confidence=0.0,
                distance_km=0.0, unknown=True,
            )
    return await asyncio.get_event_loop().run_in_executor(None, _call)


async def _real_qos_session(phone: str, profile: str = "QOS_L") -> QoSSessionResult:
    """
    Profiles: "QOS_E" (emergency) | "QOS_L" (high) | "QOS_M" (medium) | "QOS_S" (standard)
    Duration: 1800 seconds = 30 minutes
    SOFT signal: failure → fail-open (never block an emergency due to QoS failure).
    """
    def _call():
        try:
            device  = _get_device(phone)
            session = device.create_qod_session(
                profile      = profile,
                duration     = 1800,
                service_ipv4 = "0.0.0.0/0",
            )
            active     = session.status in ("REQUESTED", "AVAILABLE")
            expires_at = (
                session.expires_at.isoformat() if session.expires_at
                else (datetime.utcnow() + timedelta(minutes=30)).isoformat()
            )
            logger.info("QoS session created (NAC)",
                        extra={"phone": phone[-4:], "session_id": session.id,
                               "profile": profile, "status": session.status})
            return QoSSessionResult(
                session_id=session.id, profile=profile,
                active=active, expires_at=expires_at, unknown=False,
            )
        except Exception as exc:
            logger.warning("QoS NAC error — SOFT fail-open (emergency never blocked)",
                           exc_info=exc, extra={"phone": phone[-4:]})
            fallback_id = f"QOS-FALLBACK-{phone[-6:]}-{datetime.utcnow().strftime('%H%M%S')}"
            return QoSSessionResult(
                session_id=fallback_id, profile=profile, active=False,
                expires_at=(datetime.utcnow() + timedelta(minutes=30)).isoformat(),
                unknown=True,
            )
    return await asyncio.get_event_loop().run_in_executor(None, _call)


# ─────────────────────────────────────────────────────────────────────────────
# Simulation helpers (NAC_SIMULATE=true)
# ─────────────────────────────────────────────────────────────────────────────

REGION_COORDS = {
    "Lagos":         (6.5244,  3.3792),
    "Abuja":         (9.0579,  7.4951),
    "Kano":          (12.0022, 8.5920),
    "Port Harcourt": (4.8156,  7.0498),
    "Ibadan":        (7.3964,  3.9017),
    "Enugu":         (6.4584,  7.5464),
    "Accra, Ghana":  (5.5470, -0.2290),
    "default":       (6.5244,  3.3792),
}


async def _sim_number_verification(phone: str) -> NumberVerificationResult:
    await asyncio.sleep(0.05)
    if phone.endswith("0"):
        return NumberVerificationResult(verified=False, unknown=False,
                                        message="Number unverified (simulated)")
    return NumberVerificationResult(verified=True, unknown=False,
                                    message="Verified (simulated)")


async def _sim_sim_swap(phone: str) -> SIMSwapResult:
    await asyncio.sleep(0.05)
    if phone.endswith("9"):
        swap_date = (datetime.utcnow() - timedelta(days=2)).strftime("%Y-%m-%d")
        return SIMSwapResult(swapped=True, swap_date=swap_date,
                             days_since_swap=2, unknown=False)
    return SIMSwapResult(swapped=False, swap_date=None, days_since_swap=None)


async def _sim_device_status(phone: str) -> DeviceStatusResult:
    await asyncio.sleep(0.03)
    if phone.endswith("8"):
        return DeviceStatusResult(status="unknown", reachable=False, unknown=True)
    return DeviceStatusResult(status="active", reachable=True)


async def _sim_location_retrieval(phone: str, region: str = "default") -> LocationResult:
    await asyncio.sleep(0.08)
    base_lat, base_lng = REGION_COORDS.get(region, REGION_COORDS["default"])
    if phone.endswith("5"):
        return LocationResult(lat=base_lat, lng=base_lng,
                              accuracy_meters=9999, civic_address=f"{region} (stale)",
                              stale=True)
    return LocationResult(
        lat=round(base_lat + random.uniform(-0.04, 0.04), 6),
        lng=round(base_lng + random.uniform(-0.04, 0.04), 6),
        accuracy_meters=random.randint(50, 400),
        civic_address=region,
    )


async def _sim_location_verification(
    phone: str, expected_lat: float, expected_lng: float, radius_km: float,
) -> LocationVerificationResult:
    await asyncio.sleep(0.06)
    if phone.endswith("7"):
        return LocationVerificationResult(match=False, confidence=0.12,
                                          distance_km=random.uniform(20, 100))
    return LocationVerificationResult(match=True,
                                      confidence=random.uniform(0.85, 0.99),
                                      distance_km=random.uniform(0.1, radius_km * 0.8))


async def _sim_qos_session(phone: str, profile: str) -> QoSSessionResult:
    await asyncio.sleep(0.04)
    return QoSSessionResult(
        session_id=f"QOS-{phone[-6:]}-{datetime.utcnow().strftime('%H%M%S')}",
        profile=profile, active=True,
        expires_at=(datetime.utcnow() + timedelta(minutes=30)).isoformat(),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public async API — routes to real or simulated based on NAC_SIMULATE flag
# ─────────────────────────────────────────────────────────────────────────────

async def verify_number(phone: str) -> NumberVerificationResult:
    return await (_sim_number_verification(phone) if settings.NAC_SIMULATE
                  else _real_number_verification(phone))


async def check_sim_swap(phone: str) -> SIMSwapResult:
    return await (_sim_sim_swap(phone) if settings.NAC_SIMULATE
                  else _real_sim_swap(phone))


async def get_device_status(phone: str) -> DeviceStatusResult:
    return await (_sim_device_status(phone) if settings.NAC_SIMULATE
                  else _real_device_status(phone))


async def retrieve_location(phone: str, region: str = "Lagos") -> LocationResult:
    return await (_sim_location_retrieval(phone, region) if settings.NAC_SIMULATE
                  else _real_location_retrieval(phone, region))


async def verify_location(
    phone: str, expected_lat: float, expected_lng: float, radius_km: float = 5.0,
) -> LocationVerificationResult:
    return await (_sim_location_verification(phone, expected_lat, expected_lng, radius_km)
                  if settings.NAC_SIMULATE
                  else _real_location_verification(phone, expected_lat, expected_lng, radius_km))


async def create_qos_session(phone: str, profile: str = "QOS_L") -> QoSSessionResult:
    return await (_sim_qos_session(phone, profile) if settings.NAC_SIMULATE
                  else _real_qos_session(phone, profile))

"""
SWITCHING MODES
───────────────
NAC_SIMULATE=true  → Local simulation (no Nokia traffic, dev/hackathon default)
NAC_SIMULATE=false → Real Nokia NAC platform (requires NAC_TOKEN)

To use real CAMARA APIs:
  1. Set NAC_TOKEN=<your token> in .env
  2. Set NAC_SIMULATE=false in .env
  3. Use Nokia sandbox phone numbers (get from developer.networkascode.nokia.com
     → Sandbox → Connected Devices → Test Devices)
  4. Restart the server

CALL STRATEGY (mentor-recommended)
───────────────────────────────────
1. SIM swap runs FIRST — cheapest hard disqualifier.
   If swapped or unknown → EarlyExitFraudSignal raised immediately.
   No further CAMARA calls made. Cost and latency saved.
2. If clean → Number Verify + Device Status fan out in PARALLEL.
3. Location checked separately only when coordinates are provided.

"UNKNOWN" FALLBACK POLICY
──────────────────────────
CAMARA sometimes returns "unknown" — not just yes/no. Policies:

  SIM Swap    → HARD. unknown = fail-closed (−40, treat as swapped).
  Number      → HARD. unknown = fail-closed (−20, treat as unverified).
  Device      → SOFT. unknown = fail-open   (−5,  allow + flag).
  Location    → SOFT. unknown = fail-open   ( 0,  flag only, no deduction).
  QoS         → SOFT. unknown = fail-open   ( 0,  never block an emergency).

SIMULATION DIGIT RULES (NAC_SIMULATE=true only)
────────────────────────────────────────────────
  Last digit of phone:
  9 → SIM swap detected (recent) → EarlyExitFraudSignal raised
  0 → Number verification fails (hard, −20)
  8 → Device unknown/unreachable (soft, −5, fail-open)
  7 → Geofence check fails (hard, −25)
  5 → Stale location data (soft, 0 deduction, flag only)
  other → all checks pass ✅
"""
