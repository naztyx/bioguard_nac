### Nokia NAC Token Tester

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.config import get_settings

settings = get_settings()

TOKEN = settings.NAC_TOKEN

if not TOKEN or TOKEN == "your_nokia_nac_token_here":
    print("ERROR: Set NAC_TOKEN in your .env file first.")
    sys.exit(1)

NAC_SIMULATE=settings.NAC_SIMULATE
LOG_LEVEL=settings.LOG_LEVEL
LOG_FILE=settings.LOG_FILE


# ── Nokia sandbox phone numbers ──
SANDBOX_PHONES = [
    "+99999991000",
    "+36370000001",
    "+36370000002",
    "+36370000003",
    "+36370000004",
    "+36370000005",
]

# Allow override from command line
if len(sys.argv) > 1:
    SANDBOX_PHONES = [sys.argv[1]]
    print(f"Testing with provided number: {sys.argv[1]}\n")
else:
    print("Testing with Nokia sandbox phone numbers.")
    print("Tip: pass a specific number → python test_token.py +36370000001\n")


def _get_device(phone: str):
    import network_as_code as nac
    client = nac.NetworkAsCodeClient(token=TOKEN)
    return client.devices.get(phone_number=phone)


def test_sim_swap(phone: str) -> dict:
    try:
        device  = _get_device(phone)
        swap_dt = device.get_sim_swap_date()
        result  = {
            "api":     "SIM Swap Detection",
            "status":  "SUCCESS",
            "swapped": swap_dt is not None,
            "date":    str(swap_dt.date()) if swap_dt else None,
        }
    except Exception as e:
        result = {"api": "SIM Swap Detection", "status": f"FAILED — {e}"}
    return result


def test_sim_swap_verify(phone: str) -> dict:
    try:
        device  = _get_device(phone)
        swapped = device.verify_sim_swap(max_age=2400)  # 48h window
        result  = {
            "api":     "SIM Swap Verify (proxy for Number Verify)",
            "status":  "SUCCESS",
            "swapped_in_48h": swapped,
        }
    except Exception as e:
        result = {"api": "SIM Swap Verify", "status": f"FAILED — {e}"}
    return result


def test_device_status(phone: str) -> dict:
    try:
        device = _get_device(phone)
        status = device.get_reachability()
        result = {
            "api":          "Device Status",
            "status":       "SUCCESS",
            "reachable":    status.reachable,
            "connectivity": status.connectivity,
        }
    except Exception as e:
        result = {"api": "Device Status", "status": f"FAILED — {e}"}
    return result


def test_location(phone: str) -> dict:
    try:
        device = _get_device(phone)
        loc    = device.location(max_age=60)
        result = {
            "api":          "Location Retrieval",
            "status":       "SUCCESS",
            "latitude":     loc.latitude,
            "longitude":    loc.longitude,
            "accuracy_m":   int(loc.radius) if loc.radius else None,
            "maps_link":    f"https://maps.google.com/?q={loc.latitude},{loc.longitude}",
        }
    except Exception as e:
        result = {"api": "Location Retrieval", "status": f"FAILED — {e}"}
    return result


def test_location_verify(phone: str, lat: float, lng: float) -> dict:
    try:
        device = _get_device(phone)
        # verify_location: longitude FIRST, then latitude (Nokia SDK order)
        res    = device.verify_location(
            longitude=lng, latitude=lat, radius=5000, max_age=60
        )
        result = {
            "api":         "Location Verification (Geofence)",
            "status":      "SUCCESS",
            "result_type": res.result_type,       # TRUE | FALSE | PARTIAL
            "match_rate":  res.match_rate,
            "coords_used": f"lat={lat}, lng={lng}, radius=5km",
        }
    except Exception as e:
        result = {"api": "Location Verification", "status": f"FAILED — {e}"}
    return result


def test_qos(phone: str) -> dict:
    try:
        device  = _get_device(phone)
        session = device.create_qod_session(
            profile="QOS_L", duration=60, service_ipv4="0.0.0.0/0"
        )
        result = {
            "api":        "QoS on Demand",
            "status":     "SUCCESS",
            "session_id": session.id,
            "qos_status": session.status,
            "expires_at": str(session.expires_at),
        }
    except Exception as e:
        result = {"api": "QoS on Demand", "status": f"FAILED — {e}"}
    return result


def run_all_tests(phone: str):
    print(f"Phone: {phone}")
    print("-" * 55)

    results = [
        test_sim_swap(phone),
        test_sim_swap_verify(phone),
        test_device_status(phone),
        test_location(phone),
        test_location_verify(phone, lat=6.5244, lng=3.3792),
        test_qos(phone),
    ]

    passed = 0
    for r in results:
        api    = r.pop("api")
        status = r.pop("status")
        print(f"  {api:<42} {status}")
        for k, v in r.items():
            print(f"    {k}: {v}")
        if "SUCCESS" in status:   # ← check status string directly
            passed += 1
    return passed, len(results)


async def main():
    print("=" * 55)
    print("BioGuard — Nokia NAC Token Test")
    print(f"Token: ...{TOKEN[-8:]}")
    print("=" * 55)
    print()

    total_passed = 0
    total_tests  = 0

    for phone in SANDBOX_PHONES:
        p, t = run_all_tests(phone)
        total_passed += p
        total_tests  += t
        print()

    print("=" * 55)
    print(f"Results: {total_passed}/{total_tests} API calls succeeded")
    print()

    if total_passed == total_tests:
        print(" All CAMARA APIs working.")
        print()
        print("Next steps:")
        print("  1. Copy a working phone number from above")
        print("  2. Use it in your API calls (replace +2348056001001 in examples)")
        print("  3. Server is already set to NAC_SIMULATE=false in .env")
        print("  4. Start: uvicorn app.main:app --reload")
    elif total_passed > 0:
        print("  Some APIs failed. Check error messages above.")
        print("   Common cause: Nokia sandbox phone number not active.")
        print("   Get your numbers from: developer.networkascode.nokia.com")
        print("   → Sandbox → Connected Devices → Test Devices")
    else:
        print("  All calls failed.")
        print("   Check that NAC_TOKEN is correct in your .env file.")
        print("   Check your internet connection.")


if __name__ == "__main__":
    asyncio.run(main())
