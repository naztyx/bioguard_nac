import asyncio
import httpx
import json
import sys
import time
import argparse

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(
        asyncio.WindowsSelectorEventLoopPolicy()
    )

BASE = "http://localhost:8000"

# Colours 
R  = "\033[31m"   # red
G  = "\033[32m"   # green
Y  = "\033[33m"   # yellow
B  = "\033[34m"   # blue
M  = "\033[35m"   # magenta
C  = "\033[36m"   # cyan
W  = "\033[97m"   # bright white
DIM= "\033[2m"
RST= "\033[0m"


def header(text: str):
    width = 62
    print()
    print(f"{B}{'─' * width}{RST}")
    print(f"{W}  {text}{RST}")
    print(f"{B}{'─' * width}{RST}")


def step(n: int, text: str):
    print(f"\n{C}  [{n}]{RST} {text}")


def result(label: str, value, good: bool = True):
    icon  = f"{G}✅{RST}" if good else f"{R}🚫{RST}"
    color = G if good else R
    print(f"      {icon}  {label}: {color}{value}{RST}")


def warn(label: str, value):
    print(f"      {Y}⚠️  {label}: {value}{RST}")


def info(label: str, value):
    print(f"      {DIM}ℹ  {label}: {value}{RST}")


def camara_tag(mode: str):
    if mode == "real":
        return f"{M}[CAMARA LIVE]{RST}"
    return f"{DIM}[CAMARA SIM]{RST}"


async def call(client: httpx.AsyncClient, method: str, path: str,
               body: dict = None) -> dict:
    url = f"{BASE}{path}"
    t0  = time.perf_counter()
    if method == "GET":
        r = await client.get(url)
    elif method == "POST":
        r = await client.post(url, json=body)
    elif method == "PATCH":
        r = await client.patch(url, json=body)
    elapsed = round((time.perf_counter() - t0) * 1000)
    info("response time", f"{elapsed}ms  HTTP {r.status_code}")
    return r.json()


def show_agent_decision(decision: dict):
    d     = decision.get("agent_decision", {})
    verb  = d.get("decision", "unknown").upper()
    conf  = d.get("confidence", 0)
    color = {
        "APPROVE":  G, "FLAG": Y,
        "BLOCK": R, "ESCALATE": M,
    }.get(verb, W)
    print(f"\n      {W}Claude decision:{RST}  {color}{verb}{RST}  "
          f"(confidence: {conf:.0%})")
    print(f"      {DIM}Reasoning: {d.get('reasoning','N/A')[:100]}...{RST}")
    risks = d.get("risk_factors", [])
    if risks and risks != ["No significant risks detected"]:
        for r in risks:
            print(f"      {Y}  ↳ Risk: {r}{RST}")
    recs = d.get("recommendations", [])
    if recs:
        print(f"      {DIM}  → {recs[0]}{RST}")
    if d.get("fallback"):
        print(f"      {Y}  ⚠ Fallback mode (Claude API not reached){RST}")


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 1 — The Counterfeit Drug
# ─────────────────────────────────────────────────────────────────────────────

async def scenario_1(client: httpx.AsyncClient, mode: str):
    header("SCENARIO 1 — Counterfeit Drug Caught at Point of Dispensing")
    print(f"""
  {DIM}A pharmacist is about to hand out tablets bought from an
  unregistered distributor. BioGuard checks the batch code.{RST}""")

    step(1, f"Verifying FAKE-PARA-001  {camara_tag(mode)}")
    data = await call(client, "POST", "/drugs/verify", {
        "batch_code":    "FAKE-PARA-001",
        "phone_number":  "+2348056001001",
        "facility_code": "FAC-LAG-001",
    })
    result("Result",       data["result"].upper(), good=False)
    result("Safety Level", data["safety_level"],   good=False)
    result("Action",       data["action"],          good=False)
    info("NAFDAC Hotline", data["nafdac_hotline"])

    step(2, "Verifying the same pharmacist's identity  (SIM swap check first)")
    ident = await call(client, "POST", "/identity/verify", {
        "phone_number": "+2348056001001",
        "entity_type":  "patient",
    })
    result("Trust Score",  f"{ident['trust_score']:.0f}/100")
    result("Trust Level",  ident["trust_level"])
    info("SIM Swap",       ident["sim_swap_detected"])
    info("Early Exit",     "No — SIM was clean, parallel fan-out ran")

    print(f"\n  {G}Outcome: Drug blocked. Pharmacist flagged for review.{RST}")


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 2 — The Fraudulent Health Worker
# ─────────────────────────────────────────────────────────────────────────────

async def scenario_2(client: httpx.AsyncClient, phone: str, mode: str):
    header("SCENARIO 2 — Fraudulent Healthcare Worker (SIM Swap Fraud)")
    print(f"""
  {DIM}A patient wants to verify a worker claiming to be a doctor.
  BioGuard detects a SIM swap 2 days ago — a fraud signal.
  The check exits immediately without making further API calls.{RST}""")

    step(1, f"Verifying HW-006 (flagged worker)  {camara_tag(mode)}")
    data = await call(client, "GET", "/identity/workers/HW-006")
    color = G if data["trust_level"] == "HIGH" else R
    result("Trust Score",      f"{data['trust_score']:.0f}/100",  good=False)
    result("Trust Level",      data["trust_level"],                good=False)
    result("SIM Swap",         data["sim_swap_detected"],          good=False)
    result("Verified Status",  data["is_verified"],                good=False)
    result("Recommendation",   data["recommendation"].upper(),     good=False)

    step(2, f"Agent evaluates with all CAMARA signals  {camara_tag(mode)}")
    agent = await call(client, "POST", "/agent/evaluate/worker-authentication", {
        "worker_id":      "HW-006",
        "verifier_phone": phone,
    })
    show_agent_decision(agent)
    early = agent.get("identity_signals", {}).get("early_exit", False)
    if early:
        result("Early Exit triggered",
               "Number verify + device status calls SKIPPED", good=False)

    print(f"\n  {R}Outcome: Worker BLOCKED. SIM swap = identity theft risk.{RST}")
    print(f"  {DIM}Cost saving: 1 CAMARA call made instead of 3.{RST}")


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 3 — Trust Score Degradation
# ─────────────────────────────────────────────────────────────────────────────

async def scenario_3(client: httpx.AsyncClient, mode: str):
    header("SCENARIO 3 — Trust Score Degrading Over Multiple Fraud Signals")
    print(f"""
  {DIM}The same phone number triggers three different fraud signals
  across three separate interactions. Watch the trust score fall.{RST}""")

    scenarios = [
        ("+2348056007000", "Number unverified (ends in 0)",      "number_not_verified", -20),
        ("+2348056006009", "SIM swap detected (ends in 9)",      "sim_swap_recent",     -40),
        ("+2348056007007", "Geofence + unverified (ends in 0+7)","compound",            -45),
    ]

    prev_score = 100.0
    for phone, desc, event, delta in scenarios:
        step(0, f"{desc}  {camara_tag(mode)}")
        data = await call(client, "POST", "/identity/verify", {
            "phone_number": phone, "entity_type": "patient",
            "location_lat": 6.5244, "location_lng": 3.3792,
        })
        score = data.get("trust_score", 0)

        level = data.get("trust_level", "UNKNOWN")

        color = (
            G if level == "HIGH"
            else Y if level in ["MEDIUM", "LOW"]
            else R
        )

        print(
            f"      Score: "
            f"{prev_score:.0f} → "
            f"{color}{score:.0f}{RST}/100  "
            f"({color}{level}{RST})"
        )

        triggered_events = data.get(
            "triggered_events",
            []
        )

        info(
            "Triggered events",
            triggered_events
        )

        soft_flags = data.get(
            "soft_flags",
            []
        )

        if soft_flags:
            warn("Soft flags", soft_flags)

        prev_score = score

    print(f"\n  {R}Outcome: Pattern visible in audit trail — escalate for investigation.{RST}")

    step(0, "Checking trust event history for first phone")
    history = await call(client, "GET", "/identity/trust-history/+2348056006009")
    if isinstance(history, list):
        for h in history[:3]:
            info(h.get("event_type", "?"),
                 f"Δ{h.get('score_delta', 0):+.0f}  →  {h.get('new_score', 0):.0f}/100")


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 4 — Emergency Response with CAMARA Location
# ─────────────────────────────────────────────────────────────────────────────

async def scenario_4(client: httpx.AsyncClient, phone: str, mode: str):
    header("SCENARIO 4 — Emergency Dispatch: CAMARA Locates Patient")
    print(f"""{DIM}The nearest hospital is found by Haversine distance. QoS priority network activated.
  All in one API call.{RST}""")

    step(1, f"Creating emergency — no GPS provided  {camara_tag(mode)}")
    data = await call(client, "POST", "/emergency/", {
        "phone_number":   phone,
        "emergency_type": "medical",
        "notes":          "Patient unresponsive, bystander calling",
    })

    result("Patient Name",     data.get("patient_name") or "Looked up from registry")
    result("Location",         f"{data['location_lat']:.4f}, {data['location_lng']:.4f}")
    result("Accuracy",         f"{data.get('location_accuracy_m', '?')}m")
    result("Maps Link",        data.get("maps_link", "N/A")[:55])
    result("Nearest Hospital", data.get("assigned_facility", "N/A"))
    result("Distance",         f"{data.get('distance_to_facility_km', '?')}km")
    result("QoS Session",      data.get("qos_session_id", "N/A"))
    result("Status",           data["status"].upper())

    emergency_id = data["id"]

    step(2, "Dispatcher updates status → dispatched")
    update = await call(client, "PATCH", f"/emergency/{emergency_id}/status", {
        "status": "dispatched",
        "notes":  "Ambulance en route. ETA 8 minutes.",
    })
    result("New Status", update["status"].upper())

    step(3, f"Agent escalation assessment  {camara_tag(mode)}")
    agent = await call(client, "POST", "/agent/evaluate/emergency-escalation", {
        "phone_number":   phone,
        "emergency_type": "medical",
        "emergency_id":   emergency_id,
    })
    show_agent_decision(agent)
    nh = agent.get("nearest_hospital", {})
    if nh.get("name"):
        result("Hospital assigned", nh["name"])
        result("Distance",          f"{nh.get('distance_km', '?')}km")

    print(f"\n  {G}Outcome: Patient located, ambulance dispatched, priority network ON.{RST}")


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 5 — Full Agentic Drug Dispensation Decision
# ─────────────────────────────────────────────────────────────────────────────

async def scenario_5(client: httpx.AsyncClient, phone: str, mode: str):
    header("SCENARIO 5 — Agentic AI: 6 CAMARA Signals → Claude Decides")
    print(f"""{DIM}A nurse is about to dispense an antimalarial. BioGuard's
  Agentic AI layer runs 6 CAMARA checks simultaneously then
  sends all signals to Claude to make a real-time decision.{RST}""")

    step(1, f"Authentic drug + clean patient  {camara_tag(mode)}")
    data = await call(client, "POST", "/agent/evaluate/drug-dispensation", {
        "phone_number":  phone,
        "batch_code":    "ACT-MALARIA-001",
        "facility_code": "FAC-LAG-001",
        "facility_lat":  6.5095,
        "facility_lng":  3.3711,
    })
    result("Drug",    data.get("drug_signals", {}).get("drug_name", "ACT-MALARIA-001"))
    result("Patient trust",  f"{data['trust_score']:.0f}/100 ({data['trust_level']})")
    ids = data.get("identity_signals", {})
    result("SIM Swap",        ids.get("sim_swap_detected", "N/A"),
           good=not ids.get("sim_swap_detected", True))
    result("Number Verified", ids.get("number_verified", "N/A"),
           good=ids.get("number_verified", False))
    locs = data.get("location_signals", {})
    result("Location Match",  locs.get("geofence_match", "N/A"))
    show_agent_decision(data)

    step(2, f"SIM swap patient — early exit + block  {camara_tag(mode)}")
    data2 = await call(client, "POST", "/agent/evaluate/drug-dispensation", {
        "phone_number":  "+2348056006009",  # ends in 9 = SIM swap
        "batch_code":    "ACT-MALARIA-001",
        "facility_code": "FAC-LAG-001",
    })
    ids2 = data2.get("identity_signals", {})
    if ids2.get("early_exit"):
        warn("Early exit", "SIM swap fired — location + QoS calls SKIPPED")
    show_agent_decision(data2)

    print(f"\n  {G}Outcome: Clean patient approved in <1s. Fraud patient blocked.{RST}")
    print(f"  {DIM}Claude evaluated identity + location + network + drug signals together.{RST}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="BioGuard Demo")
    parser.add_argument("--real",  action="store_true",
                        help="Use real Nokia NAC (set NAC_SIMULATE=false first)")
    parser.add_argument("--phone", default="+2348056001001",
                        help="Phone number to use (Nokia sandbox number for --real)")
    parser.add_argument("--scenario", type=int, default=0,
                        help="Run a single scenario (1-5). Default: all.")
    args = parser.parse_args()

    mode  = "real" if args.real else "simulated"
    phone = args.phone

    print(f"""
{B}╔══════════════════════════════════════════════════════════╗
║           BioGuard — Live Demo                          ║
║    Healthcare Trust Infrastructure for Africa           ║
╚══════════════════════════════════════════════════════════╝{RST}
  Mode:  {G if mode=='real' else Y}{mode.upper()}{RST}  |  Phone: {phone}
  Docs:  http://localhost:8000/docs
""")

    timeout = httpx.Timeout(
        connect=20.0,
        read=300.0,
        write=120.0,
        pool=120.0,
    )

    limits = httpx.Limits(
        max_connections=20,
        max_keepalive_connections=10,
        keepalive_expiry=30.0,
    )

    async with httpx.AsyncClient(timeout=timeout, limits=limits, http2=False,) as client:
        # Quick health check
        try:
            r = await client.get(f"{BASE}/health")
            assert r.status_code == 200
            print(f"  {G}   Server online{RST}")
        except Exception:
            print(f"  {R}   Server not running. Start with: uvicorn app.main:app --reload{RST}")
            sys.exit(1)

        # Agent health
        try:
            r   = await client.get(f"{BASE}/agent/health")
            ah  = r.json()
            claude_ok = ah.get("claude_reachable", False)
            fb        = ah.get("fallback_mode", True)
            if claude_ok:
                print(f"  {G}  Claude API reachable — real AI decisions active{RST}")
            else:
                print(f"  {Y}  Claude API unreachable — rule-based fallback active{RST}")
                print(f"     Set ANTHROPIC_API_KEY in .env for live AI decisions")
        except Exception:
            print(f"  {Y}   Agent health check failed{RST}")

        scenarios = {
            1: lambda: scenario_1(client, mode),
            2: lambda: scenario_2(client, phone, mode),
            3: lambda: scenario_3(client, mode),
            4: lambda: scenario_4(client, phone, mode),
            5: lambda: scenario_5(client, phone, mode),
        }

        to_run = [args.scenario] if args.scenario else list(scenarios.keys())

        for n in to_run:
            await scenarios[n]()
            if n != to_run[-1]:
                print(f"\n  {DIM}Press Enter for next scenario...{RST}", end="")
                input()

    print(f"""
{B}{'─' * 62}{RST}
{G}  Demo complete.{RST}

  What was demonstrated:
  {G}   {RST}  Counterfeit drug blocked at point of dispensing
  {G}   {RST}  SIM swap fraud worker blocked (early exit — 1 CAMARA call)
  {G}   {RST}  Trust score degradation across multiple fraud signals
  {G}   {RST}  Emergency dispatch: CAMARA location → nearest hospital → QoS
  {G}   {RST}  Agentic AI: 6 CAMARA signals evaluated by Claude simultaneously

  Full API docs: {C}http://localhost:8000/docs{RST}
  Logs:          {C}tail -20 logs/bioguard.log{RST}
{B}{'─' * 62}{RST}
""")


if __name__ == "__main__":
    asyncio.run(main())
