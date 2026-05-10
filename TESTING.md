# BioGuard API — Testing Scenarios (v5, Post-Refactor)

> **Base URL:** `http://localhost:8000`  
> **Docs:** `http://localhost:8000/docs`  
> **Prerequisites:** Server running + `python seed_demo.py` executed  
> **4G/5G assumed** — USSD removed per mentor feedback.

---

## CAMARA Simulation Reference

| Last digit of phone | Signal triggered |
|---|---|
| `9` | SIM swap detected → **early exit** (zero further CAMARA calls) |
| `0` | Number verification fails (hard signal, −20) |
| `8` | Device unknown/unreachable (soft signal, −5, fail-open) |
| `7` | Geofence check fails (−25) |
| `5` | Stale location data (soft signal, 0 deduction, flag only) |
| other | All checks pass ✅ |

---

## SCENARIO GROUP A — SIM Swap Early Exit Pattern

### A1 — SIM swap: early exit, no further calls

**What it proves:** Cheapest fraud disqualifier runs first. Costs one API call, not three.

```bash
curl -s -X POST http://localhost:8000/identity/verify \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+2348056006009", "entity_type": "patient"}' \
  | python3 -m json.tool
```

**Expected:**
```json
{
  "trust_score":       35.0,
  "trust_level":       "CRITICAL",
  "sim_swap_detected": true,
  "sim_swap_date":     "2025-01-03",
  "recommendation":    "block",
  "action_message":    "BLOCKED. Escalate to facility security immediately.",
  "triggered_events":  ["sim_swap_recent"],
  "soft_flags":        []
}
```

Check the logs — you will see `SIM swap detected — early exit triggered` and nothing about number verification or device status. Those calls were never made.

---

### A2 — Clean patient: SIM clean → parallel fan-out

**What it proves:** Happy path runs SIM swap (clean) then fans out 2 more checks in parallel. Near single-call latency.

```bash
curl -s -X POST http://localhost:8000/identity/verify \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+2348056001001", "entity_type": "patient"}' \
  | python3 -m json.tool
```

**Expected:**
```json
{
  "trust_score":       100.0,
  "trust_level":       "HIGH",
  "sim_swap_detected": false,
  "number_verified":   true,
  "device_status":     "active",
  "recommendation":    "allow",
  "action_message":    "Proceed. All checks passed.",
  "triggered_events":  [],
  "soft_flags":        []
}
```

All three signals present. SIM swap first, then number verify + device status in parallel.

---

### A3 — Agent: SIM swap short-circuits full drug dispensation evaluation

**What it proves:** Early exit propagates through the entire Agentic AI layer.

```bash
curl -s -X POST http://localhost:8000/agent/evaluate/drug-dispensation \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number":  "+2348056006009",
    "batch_code":    "ACT-MALARIA-001",
    "facility_code": "FAC-LAG-001",
    "facility_lat":  6.5095,
    "facility_lng":  3.3711
  }' | python3 -m json.tool
```

**Expected:** `agent_decision.decision: "block"`. In `identity_signals`:
`early_exit: true` — location, geofence, and QoS checks were all skipped.
Claude receives the early exit flag as part of context and confirms the block.

---

## SCENARIO GROUP B — Unknown Signal Fallback Policies

### B1 — Device unknown (SOFT): fail-open, −5 only

**What it proves:** Stale device data does not block a legitimate patient.

```bash
curl -s -X POST http://localhost:8000/identity/verify \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+2348056001008", "entity_type": "patient"}' \
  | python3 -m json.tool
```

**Expected:**
```json
{
  "trust_level":      "HIGH",
  "device_status":    "unknown",
  "recommendation":   "allow",
  "triggered_events": [],
  "soft_flags": ["Device status UNKNOWN — soft penalty applied, proceeding"]
}
```

Score drops only −5. System proceeds. `soft_flags` explains what happened without alarming the operator.

---

### B2 — Stale location (SOFT): zero deduction, flag only

**What it proves:** Soft signals are logged but never penalise a score or block a transaction.

```bash
curl -s -X POST http://localhost:8000/identity/verify \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+2348056001005",
    "entity_type":  "patient",
    "location_lat": 6.5244,
    "location_lng": 3.3792
  }' | python3 -m json.tool
```

**Expected:**
```json
{
  "trust_level":      "HIGH",
  "recommendation":   "allow",
  "triggered_events": [],
  "soft_flags": ["Location UNKNOWN — stale data, flagged but not penalised"]
}
```

Zero score deduction from location. Flagged for human review only.

---

### B3 — Number unknown (HARD): fail-closed, −20

**What it proves:** Hard signals fail-closed when CAMARA cannot determine the result.

```bash
curl -s -X POST http://localhost:8000/identity/verify \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+2348056007000", "entity_type": "patient"}' \
  | python3 -m json.tool
```

**Expected:**
```json
{
  "trust_score":      62.0,
  "trust_level":      "LOW",
  "number_verified":  false,
  "recommendation":   "flag",
  "triggered_events": ["number_not_verified"]
}
```

Hard signal, −20 penalty. Trust drops to LOW. Secondary confirmation required.

---

### B4 — Combined: device unknown + location mismatch

**What it proves:** Soft and hard signals combine correctly.

```bash
curl -s -X POST http://localhost:8000/identity/verify \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+2348056001008",
    "entity_type":  "patient",
    "location_lat": 6.5244,
    "location_lng": 3.3792
  }' | python3 -m json.tool
```

Phone ends in 8 (device unknown, −5) + location is provided but does not end in 7 (passes).
**Expected:** `trust_level: HIGH`. Small penalty from soft device signal.
`soft_flags` shows device note, `triggered_events` is empty.

---

## SCENARIO GROUP C — Drug Safety Module

### C1 — Authentic drug, authorised facility (SAFE)

```bash
curl -s -X POST http://localhost:8000/drugs/verify \
  -H "Content-Type: application/json" \
  -d '{
    "batch_code":    "ACT-MALARIA-001",
    "phone_number":  "+2348056001001",
    "facility_code": "FAC-LAG-001",
    "facility_lat":  6.5095,
    "facility_lng":  3.3711
  }' | python3 -m json.tool
```

**Expected:**
```json
{
  "result":              "authentic",
  "location_authorized": true,
  "cold_chain_ok":       true,
  "trust_score":         100.0,
  "safety_level":        "SAFE",
  "action":              "Safe to dispense and consume.",
  "nafdac_number":       "A4-0082",
  "nafdac_hotline":      "0800-1-623322"
}
```

---

### C2 — Counterfeit drug (CRITICAL)

```bash
curl -s -X POST http://localhost:8000/drugs/verify \
  -H "Content-Type: application/json" \
  -d '{"batch_code": "FAKE-PARA-001", "phone_number": "+2348056001001"}' \
  | python3 -m json.tool
```

**Expected:** `safety_level: CRITICAL`, `result: recalled`. Message includes NAFDAC recall
reference and hotline number. `alert_sent: true` in the verification record.

---

### C3 — Expired vaccine (DANGER)

```bash
curl -s -X POST http://localhost:8000/drugs/verify \
  -H "Content-Type: application/json" \
  -d '{"batch_code": "EXP-HEPB-001", "phone_number": "+2348056001001"}' \
  | python3 -m json.tool
```

**Expected:** `result: expired`, `safety_level: DANGER`, `expiry_date: 2024-05-31`.
`action: "Drug expired. Do NOT dispense. Remove from shelf immediately."`

---

### C4 — Drug dispensed from unauthorised facility (diversion detection)

```bash
curl -s -X POST http://localhost:8000/drugs/verify \
  -H "Content-Type: application/json" \
  -d '{
    "batch_code":    "ACT-ARV-001",
    "phone_number":  "+2348056001001",
    "facility_code": "PHR-LAG-001"
  }' | python3 -m json.tool
```

**Expected:** `result: counterfeit`, `location_authorized: false`, `safety_level: WARNING`.
`ACT-ARV-001` is authorised at LUTH, Abuja, Port Harcourt only.
HealthPlus Pharmacy Ikeja is not on the list — potential diversion flagged.

---

### C5 — Cold-chain vaccine, broken chain

```bash
curl -s -X POST http://localhost:8000/drugs/verify \
  -H "Content-Type: application/json" \
  -d '{
    "batch_code":    "CC-HEPB-001",
    "phone_number":  "+2348056001008",
    "facility_code": "FAC-LAG-001"
  }' | python3 -m json.tool
```

**Expected:** `cold_chain_ok: false`, `safety_level: WARNING`.
Device status unknown on the transport device (ends in 8) → cold chain unconfirmed.
Pharmacist is warned, not hard-blocked (soft signal policy).

---

### C6 — Unknown batch (not in registry)

```bash
curl -s -X POST http://localhost:8000/drugs/verify \
  -H "Content-Type: application/json" \
  -d '{"batch_code": "MARKET-XYZ-999", "phone_number": "+2348056001001"}' \
  | python3 -m json.tool
```

**Expected:** `result: not_found`, `safety_level: CRITICAL`, `trust_score: 0.0`.
`action: "Drug NOT in registry — possible counterfeit. Do NOT dispense. Call NAFDAC: 0800-162-0020"`

---

### C7 — Issue a recall and immediately verify it is blocked

```bash
# Issue the recall
curl -s -X PATCH \
  "http://localhost:8000/drugs/TEST-DRUG-001/recall?reason=Contamination+found+in+batch" \
  | python3 -m json.tool

# Verify it is now blocked
curl -s -X POST http://localhost:8000/drugs/verify \
  -H "Content-Type: application/json" \
  -d '{"batch_code": "TEST-DRUG-001", "phone_number": "+2348056001001"}' \
  | python3 -m json.tool
```

**Expected second call:** `result: recalled`, `safety_level: CRITICAL` immediately.
Recall takes effect on the next verification with zero propagation delay.

---

## SCENARIO GROUP D — Emergency Response Module

### D1 — Emergency: CAMARA locates patient, nearest hospital assigned

```bash
curl -s -X POST http://localhost:8000/emergency/ \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number":   "+2348056001001",
    "emergency_type": "medical",
    "notes":          "Patient unresponsive"
  }' | python3 -m json.tool
```

**Expected — check every field:**
```json
{
  "patient_name":             "Chidinma Obi",
  "location_lat":             6.530273,
  "location_lng":             3.368122,
  "location_accuracy_m":      187,
  "maps_link":                "https://maps.google.com/?q=6.530273,3.368122",
  "assigned_facility":        "Lagos University Teaching Hospital (LUTH)",
  "assigned_facility_code":   "FAC-LAG-001",
  "distance_to_facility_km":  2.1,
  "qos_session_id":           "QOS-001001-143201",
  "status":                   "pending"
}
```

Patient name auto-pulled from registry. Location retrieved by CAMARA without GPS.
QoS priority network active. Maps link is click-ready for dispatch team.

---

### D2 — Emergency with stale location: dispatched anyway (never blocked)

**What it proves:** QoS is a soft signal. Stale location data never blocks an emergency.

```bash
curl -s -X POST http://localhost:8000/emergency/ \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number":   "+2348056001005",
    "emergency_type": "ambulance"
  }' | python3 -m json.tool
```

**Expected:** Emergency created, status `pending`, facility assigned from last-known coordinates.
`location_accuracy_m: 9999` signals stale data. QoS activated regardless.

---

### D3 — Dispatcher: live location + nearest hospital phone

```bash
curl -s http://localhost:8000/emergency/locate/+2348056001001 | python3 -m json.tool
```

**Expected:**
```json
{
  "latitude":            6.530273,
  "longitude":           3.368122,
  "accuracy_meters":     187,
  "maps_link":           "https://maps.google.com/?q=6.530273,3.368122",
  "nearest_hospital":    "Lagos University Teaching Hospital (LUTH)",
  "nearest_hospital_km": 2.1,
  "nearest_phone":       "+23412345001"
}
```

`nearest_phone` — dispatcher calls the hospital directly from this single API response.

---

### D4 — State machine: valid transitions

```bash
# List pending emergencies and note the ID
curl -s "http://localhost:8000/emergency/?status_filter=pending" | python3 -m json.tool

# Dispatch (replace 6 with actual ID)
curl -s -X PATCH http://localhost:8000/emergency/6/status \
  -H "Content-Type: application/json" \
  -d '{"status": "dispatched", "notes": "Ambulance dispatched, ETA 8 min"}'

# Resolve
curl -s -X PATCH http://localhost:8000/emergency/6/status \
  -H "Content-Type: application/json" \
  -d '{"status": "resolved", "notes": "Patient stabilised and admitted"}'
```

---

### D5 — Illegal state transition (409)

```bash
curl -s -X PATCH http://localhost:8000/emergency/6/status \
  -H "Content-Type: application/json" \
  -d '{"status": "dispatched"}' | python3 -m json.tool
```

**Expected:** `409 Conflict`
```json
{
  "detail": "Cannot transition 'resolved' → 'dispatched'. Allowed: none — terminal state."
}
```

---

### D6 — Dashboard stats

```bash
curl -s http://localhost:8000/emergency/stats/summary | python3 -m json.tool
```

**Expected:**
```json
{
  "total": 10, "pending": 3, "dispatched": 3, "resolved": 3, "cancelled": 1,
  "by_type": {"medical": 4, "drug_reaction": 1, "ambulance": 4, "mental_health": 1}
}
```

---

## SCENARIO GROUP E — Agentic AI Layer

### E1 — Drug dispensation: clean path (Claude approves)

```bash
curl -s -X POST http://localhost:8000/agent/evaluate/drug-dispensation \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number":  "+2348056001001",
    "batch_code":    "ACT-MALARIA-001",
    "facility_code": "FAC-LAG-001",
    "facility_lat":  6.5095,
    "facility_lng":  3.3711
  }' | python3 -m json.tool
```

**Expected:** Claude receives all 6 CAMARA signals + drug record in one structured context.
`agent_decision.decision: "approve"`, confidence > 0.9.
`reasoning` field explains exactly why approval was granted.

---

### E2 — Worker authentication: SIM swap → early exit → block

```bash
curl -s -X POST http://localhost:8000/agent/evaluate/worker-authentication \
  -H "Content-Type: application/json" \
  -d '{"worker_id": "HW-006", "verifier_phone": "+2348056001001"}' \
  | python3 -m json.tool
```

**Expected:** `agent_decision.decision: "block"`.
`identity_signals.early_exit: true` — number verify and device status were skipped.
`risk_factors` list includes SIM swap.

---

### E3 — Emergency escalation

```bash
# Create emergency first
EMID=$(curl -s -X POST http://localhost:8000/emergency/ \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+2348056001001", "emergency_type": "medical"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# Escalate
curl -s -X POST http://localhost:8000/agent/evaluate/emergency-escalation \
  -H "Content-Type: application/json" \
  -d "{\"phone_number\": \"+2348056001001\", \"emergency_type\": \"medical\", \"emergency_id\": $EMID}" \
  | python3 -m json.tool
```

**Expected:** Claude receives identity, live location, QoS status, nearest hospital
name, distance, and phone. Returns `approve` (standard) or `escalate` (multi-facility).
`nearest_hospital` block shows the exact facility assigned.

---

### E4 — Suspicious activity: fraud pattern

```bash
curl -s -X POST http://localhost:8000/agent/evaluate/suspicious-activity \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number":  "+2348056006009",
    "activity_type": "multiple_drug_verify_fails",
    "context_data":  {
      "failed_batches":  ["FAKE-PARA-001", "RECALL-COUGH-001"],
      "attempts_in_1h":  4,
      "locations_seen":  ["Ikeja", "Surulere", "Victoria Island"]
    }
  }' | python3 -m json.tool
```

**Expected:** Claude receives identity signals + last 5 trust events + activity context.
Phone already at trust score 35 with SIM swap history.
`agent_decision.decision: "block"`. Automatic fraud penalty applied and persisted.

---

### E5 — Agent health (Claude reachability check)

```bash
curl -s http://localhost:8000/agent/health | python3 -m json.tool
```

**Expected:**
```json
{
  "agent_layer":      "online",
  "claude_model":     "claude-sonnet-4-20250514",
  "simulate_camara":  true,
  "claude_reachable": true,
  "fallback_mode":    false
}
```

If `claude_reachable: false` → `fallback_mode: true` → rule-based decisions active.
System never goes offline.

---

## SCENARIO GROUP F — Healthcare Worker Module

### F1 — Verify trusted doctor (HIGH trust)

```bash
curl -s http://localhost:8000/identity/workers/HW-001 | python3 -m json.tool
```

**Expected:** `trust_level: HIGH`, `is_verified: true`, `sim_swap_detected: false`,
`recommendation: allow`.

---

### F2 — Verify fraud worker (CRITICAL trust, SIM swap)

```bash
curl -s http://localhost:8000/identity/workers/HW-006 | python3 -m json.tool
```

**Expected:** `trust_level: CRITICAL`, `sim_swap_detected: true`, `recommendation: block`.
Trust score 38. Worker not verified. SIM swapped 2 days ago.

---

### F3 — Worker with location context (geofence vs registered facility)

```bash
curl -s -X POST http://localhost:8000/identity/verify \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+2348011007007",
    "entity_type":  "worker",
    "location_lat": 6.5095,
    "location_lng": 3.3711
  }' | python3 -m json.tool
```

Phone ends in 0 (number unverified, −20) and 7 (geofence fails, −25).
**Expected:** `trust_level: LOW`, triggered_events includes both penalties.
`recommendation: flag`.

---

### F4 — Register + approve a new worker

```bash
# Register
curl -s -X POST http://localhost:8000/identity/workers \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number":   "+2348099001001",
    "worker_id":      "HW-099",
    "full_name":      "Dr. Amina Bello",
    "facility_name":  "National Hospital Abuja",
    "facility_code":  "FAC-ABJ-001",
    "specialization": "Emergency Medicine"
  }' | python3 -m json.tool

# Approve (admin action)
curl -s -X PATCH http://localhost:8000/identity/workers/HW-099/verify | python3 -m json.tool

# Verify approval
curl -s http://localhost:8000/identity/workers/HW-099 | python3 -m json.tool
```

**Expected after approval:** `is_verified: true`, `recommendation: allow`.

---

## Full 2-Minute Demo (copy-paste ready)

```bash
echo "=== 1. SYSTEM LIVE ==="
curl -s http://localhost:8000/ | python3 -m json.tool

echo "=== 2. SIM SWAP → EARLY EXIT (one API call, zero waste) ==="
curl -s -X POST http://localhost:8000/identity/verify \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+2348056006009", "entity_type": "patient"}' \
  | python3 -m json.tool

echo "=== 3. CLEAN PATIENT → PARALLEL FAN-OUT ==="
curl -s -X POST http://localhost:8000/identity/verify \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+2348056001001", "entity_type": "patient"}' \
  | python3 -m json.tool

echo "=== 4. COUNTERFEIT DRUG (CRITICAL) ==="
curl -s -X POST http://localhost:8000/drugs/verify \
  -H "Content-Type: application/json" \
  -d '{"batch_code": "FAKE-PARA-001", "phone_number": "+2348056001001"}' \
  | python3 -m json.tool

echo "=== 5. AUTHENTIC DRUG (SAFE) ==="
curl -s -X POST http://localhost:8000/drugs/verify \
  -H "Content-Type: application/json" \
  -d '{"batch_code": "ACT-MALARIA-001", "phone_number": "+2348056001001", "facility_code": "FAC-LAG-001"}' \
  | python3 -m json.tool

echo "=== 6. EMERGENCY (CAMARA locates, hospital assigned, QoS active) ==="
curl -s -X POST http://localhost:8000/emergency/ \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+2348056001001", "emergency_type": "ambulance"}' \
  | python3 -m json.tool

echo "=== 7. AGENT: 6 CAMARA SIGNALS → CLAUDE DECIDES ==="
curl -s -X POST http://localhost:8000/agent/evaluate/drug-dispensation \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+2348056001001", "batch_code": "ACT-MALARIA-001", "facility_code": "FAC-LAG-001", "facility_lat": 6.5095, "facility_lng": 3.3711}' \
  | python3 -m json.tool

echo "=== 8. SOFT SIGNAL: stale location, system proceeds ==="
curl -s -X POST http://localhost:8000/identity/verify \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+2348056001005", "entity_type": "patient", "location_lat": 6.5, "location_lng": 3.3}' \
  | python3 -m json.tool

echo "=== 9. DASHBOARD ==="
curl -s http://localhost:8000/emergency/stats/summary | python3 -m json.tool

echo "=== 10. LOGS ==="
tail -3 logs/bioguard.log
```

---

## What Each Test Proves to a Judge

| Test | What it demonstrates |
|---|---|
| A1 — SIM early exit | Mentor pattern: cheapest check first, fraud detected in 1 call |
| A2 — Clean parallel | Happy path near single-call latency via asyncio.gather |
| A3 — Agent early exit | Short-circuit propagates through AI layer |
| B1 — Device unknown | Soft signal: system stays live, stale data doesn't block patients |
| B2 — Location stale | Zero-penalty flag: location uncertainty never stops transactions |
| B3 — Number unknown | Hard signal: fail-closed, appropriate penalty applied |
| C4 — Diversion | CAMARA geofencing catches drug being dispensed in wrong location |
| D2 — Stale emergency | Emergencies never blocked regardless of network data quality |
| D5 — 409 transition | State machine prevents impossible status reversals |
| E1 — Agent approve | 6 simultaneous CAMARA signals evaluated by Claude in one context |
| E2 — Agent block | Early exit + AI reasoning converge on same block decision |
| E5 — Fallback mode | System works even when Claude API is unreachable |
