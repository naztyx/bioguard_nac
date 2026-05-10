"""
BioGuard — Real CAMARA API Test Commands
=========================================
Replace PHONE with your Nokia sandbox phone number.
Get sandbox numbers: developer.networkascode.nokia.com
→ Sandbox → Connected Devices → Test Devices

Run test_token.py first to confirm your token and find working numbers.

Setup:
  .env:  NAC_TOKEN=your_token  NAC_SIMULATE=false
  Then:  uvicorn app.main:app --reload
         python seed_demo.py
"""
+36370000001 - FAcility
+36370000002 - verified worker
+36370000003 - Fraud worker
+36370000004 - Verified Patient
+36370000005 - Fraud Patient
+36370000006 - Facility

# ─── SCENARIO 1: SIM Swap early exit (hard signal, cheapest call) ────────────
# Replace PHONE with your Nokia sandbox number

SCENARIO_1 = """
# Identity check — SIM swap runs first, if clean → parallel fan-out
curl -s -X POST http://localhost:8000/identity/verify \\
  -H "Content-Type: application/json" \\
  -d '{"phone_number": "PHONE", "entity_type": "patient"}' \\
  | python3 -m json.tool

# Check the logs — real NAC calls show no "(simulated)" tag
tail -10 logs/bioguard.log
"""

# ─── SCENARIO 2: Device status + location ───────────────────────────────────

SCENARIO_2 = """
# Live location retrieval + nearest hospital
curl -s http://localhost:8000/emergency/locate/PHONE | python3 -m json.tool
"""

# ─── SCENARIO 3: Emergency dispatch ─────────────────────────────────────────

SCENARIO_3 = """
# Full emergency — CAMARA location + QoS activated in real network
curl -s -X POST http://localhost:8000/emergency/ \\
  -H "Content-Type: application/json" \\
  -d '{"phone_number": "PHONE", "emergency_type": "medical"}' \\
  | python3 -m json.tool
"""

# ─── SCENARIO 4: Drug dispensation with Agent AI ────────────────────────────

SCENARIO_4 = """
# Agent runs 6 CAMARA APIs then sends to Claude for decision
curl -s -X POST http://localhost:8000/agent/evaluate/drug-dispensation \\
  -H "Content-Type: application/json" \\
  -d '{
    "phone_number":  "PHONE",
    "batch_code":    "ACT-MALARIA-001",
    "facility_code": "FAC-LAG-001",
    "facility_lat":  6.5095,
    "facility_lng":  3.3711
  }' | python3 -m json.tool
"""

# ─── SCENARIO 5: QoS priority network ───────────────────────────────────────

SCENARIO_5 = """
# Manually activate priority network session
curl -s -X POST "http://localhost:8000/emergency/qos/PHONE?profile=QOS_L" \\
  | python3 -m json.tool
"""

# ─── SCENARIO 6: Worker authentication with geofence ────────────────────────

SCENARIO_6 = """
# First register a worker with the sandbox phone number
curl -s -X POST http://localhost:8000/identity/workers \\
  -H "Content-Type: application/json" \\
  -d '{
    "phone_number":   "PHONE",
    "worker_id":      "HW-NAC-001",
    "full_name":      "Dr. Nokia Test",
    "facility_name":  "Lagos University Teaching Hospital (LUTH)",
    "facility_code":  "FAC-LAG-001",
    "specialization": "Emergency Medicine"
  }' | python3 -m json.tool

# Then verify — real SIM swap + number verify from Nokia
curl -s http://localhost:8000/identity/workers/HW-NAC-001 | python3 -m json.tool
"""

if __name__ == "__main__":
    print("Replace PHONE in the scenarios above with your Nokia sandbox number.")
    print("Run: python test_token.py to find your working sandbox numbers.")
