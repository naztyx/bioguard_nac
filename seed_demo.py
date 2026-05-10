"""
Run:
    python seed_demo.py
"""

import asyncio
import random
import sys
import os
import json
from datetime import datetime, timedelta
from app.config import get_settings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

settings = get_settings()

DATABASE_URL=settings.DATABASE_URL
NAC_SIMULATE=settings.NAC_SIMULATE
LOG_LEVEL=settings.LOG_LEVEL
LOG_FILE=settings.LOG_FILE

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.config import get_settings
from app.database import Base
from app import models   # safe now — no broken relationships in models.py

settings = get_settings()
engine   = create_async_engine(settings.DATABASE_URL, echo=False)
Session  = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def ago(days=0, hours=0, minutes=0):
    return datetime.utcnow() - timedelta(days=days, hours=hours, minutes=minutes)


# ─────────────────────────────────────────────────────────────────────────────
# Seed data
# ─────────────────────────────────────────────────────────────────────────────

NATIONAL = [
    "FAC-LAG-001", "FAC-LAG-002", "FAC-ABJ-001",
    "FAC-KAN-001", "FAC-PHC-001", "FAC-ENU-001", "FAC-IBD-001",
]
ALL_FAC = NATIONAL + ["PHR-LAG-001", "LAB-LAG-001", "PHR-KAN-001", "FAC-ACC-001"]

FACILITIES = [
    dict(facility_code="FAC-LAG-001", name="Lagos University Teaching Hospital (LUTH)",   facility_type="hospital",  region="Lagos",         location_lat=6.5095,  location_lng=3.3711,  phone_number="+36370000001"),
    dict(facility_code="FAC-LAG-002", name="Reddington Hospital Victoria Island",          facility_type="hospital",  region="Lagos",         location_lat=6.4281,  location_lng=3.4217,  phone_number="+23412345002"),
    dict(facility_code="PHR-LAG-001", name="HealthPlus Pharmacy Ikeja",                    facility_type="pharmacy",  region="Lagos",         location_lat=6.6018,  location_lng=3.3515,  phone_number="+23412345003"),
    dict(facility_code="LAB-LAG-001", name="Synlab Nigeria Lekki",                         facility_type="lab",       region="Lagos",         location_lat=6.4698,  location_lng=3.5852,  phone_number="+23412345004"),
    dict(facility_code="FAC-ABJ-001", name="National Hospital Abuja",                      facility_type="hospital",  region="Abuja",         location_lat=9.0579,  location_lng=7.4951,  phone_number="+23412345005"),
    dict(facility_code="FAC-ABJ-002", name="Garki Hospital Abuja",                         facility_type="hospital",  region="Abuja",         location_lat=9.0367,  location_lng=7.4883,  phone_number="+23412345006"),
    dict(facility_code="FAC-KAN-001", name="Aminu Kano Teaching Hospital",                 facility_type="hospital",  region="Kano",          location_lat=12.0022, location_lng=8.5920,  phone_number="+23412345007"),
    dict(facility_code="PHR-KAN-001", name="Kano State Drug Store",                        facility_type="pharmacy",  region="Kano",          location_lat=12.0054, location_lng=8.5915,  phone_number="+36370000006"),
    dict(facility_code="FAC-PHC-001", name="University of Port Harcourt Teaching Hospital",facility_type="hospital",  region="Port Harcourt", location_lat=4.8156,  location_lng=7.0498,  phone_number="+23412345009"),
    dict(facility_code="FAC-ENU-001", name="Enugu State University Teaching Hospital",     facility_type="hospital",  region="Enugu",         location_lat=6.4584,  location_lng=7.5464,  phone_number="+23412345010"),
    dict(facility_code="FAC-IBD-001", name="University College Hospital Ibadan",           facility_type="hospital",  region="Ibadan",        location_lat=7.3964,  location_lng=3.9017,  phone_number="+23412345011"),
    dict(facility_code="FAC-ACC-001", name="Korle Bu Teaching Hospital",                   facility_type="hospital",  region="Accra, Ghana",  location_lat=5.5470,  location_lng=-0.2290, phone_number="+23312345001"),
]

WORKERS = [
    dict(phone_number="+36370000002", worker_id="HW-001", full_name="Dr. Amaka Okonkwo",     facility_name="Lagos University Teaching Hospital (LUTH)",    facility_code="FAC-LAG-001", specialization="Emergency Medicine",  is_verified=True,  trust_score=98.0),
    dict(phone_number="+2348011002002", worker_id="HW-002", full_name="Dr. Chukwuemeka Nwosu", facility_name="Lagos University Teaching Hospital (LUTH)",    facility_code="FAC-LAG-001", specialization="Internal Medicine",   is_verified=True,  trust_score=97.0),
    dict(phone_number="+2348011003003", worker_id="HW-003", full_name="Nurse Blessing Eze",     facility_name="Reddington Hospital Victoria Island",           facility_code="FAC-LAG-002", specialization="ICU Nursing",         is_verified=True,  trust_score=95.0),
    dict(phone_number="+2348011004004", worker_id="HW-004", full_name="Pharm. Bola Adeyemi",   facility_name="HealthPlus Pharmacy Ikeja",                    facility_code="PHR-LAG-001", specialization="Clinical Pharmacy",   is_verified=True,  trust_score=100.0),
    dict(phone_number="+2348011005005", worker_id="HW-005", full_name="Dr. Tunde Fashola",     facility_name="Reddington Hospital Victoria Island",           facility_code="FAC-LAG-002", specialization="Cardiology",          is_verified=True,  trust_score=99.0),
    # Fraud scenarios — last digit drives CAMARA simulation:
    # ends in 9 → SIM swap detected, ends in 0 → number unverified
    dict(phone_number="+36370000003", worker_id="HW-006", full_name="Mr. Dare Olusegun",     facility_name="HealthPlus Pharmacy Ikeja",                    facility_code="PHR-LAG-001", specialization="Dispensary",          is_verified=False, trust_score=38.0),
    dict(phone_number="+2348011007000", worker_id="HW-007", full_name="Pharm. Ngozi Igwe",     facility_name="Synlab Nigeria Lekki",                         facility_code="LAB-LAG-001", specialization="Lab Science",         is_verified=False, trust_score=55.0),
    dict(phone_number="+2348022001001", worker_id="HW-008", full_name="Dr. Fatima Al-Hassan",  facility_name="National Hospital Abuja",                      facility_code="FAC-ABJ-001", specialization="Paediatrics",         is_verified=True,  trust_score=96.0),
    dict(phone_number="+2348022002002", worker_id="HW-009", full_name="Dr. Emeka Obi",         facility_name="Garki Hospital Abuja",                         facility_code="FAC-ABJ-002", specialization="Surgery",             is_verified=True,  trust_score=94.0),
    dict(phone_number="+2348033001001", worker_id="HW-010", full_name="Dr. Musa Ibrahim",      facility_name="Aminu Kano Teaching Hospital",                 facility_code="FAC-KAN-001", specialization="Internal Medicine",   is_verified=True,  trust_score=91.0),
    dict(phone_number="+2348044001001", worker_id="HW-011", full_name="Dr. Tonye Briggs",      facility_name="University of Port Harcourt Teaching Hospital",facility_code="FAC-PHC-001", specialization="Oncology",            is_verified=True,  trust_score=97.0),
    dict(phone_number="+2348066001001", worker_id="HW-012", full_name="Prof. Wale Adedoyin",   facility_name="University College Hospital Ibadan",           facility_code="FAC-IBD-001", specialization="Haematology",         is_verified=True,  trust_score=99.0),
]

PATIENTS = [
    dict(phone_number="+36370000004", health_id="BG-NG-00001", full_name="Chidinma Obi",      date_of_birth="1990-05-14", blood_group="O+",  region="Lagos",         trust_score=100.0),
    dict(phone_number="+2348056002002", health_id="BG-NG-00002", full_name="Emeka Dike",         date_of_birth="1985-11-22", blood_group="A+",  region="Lagos",         trust_score=97.0),
    dict(phone_number="+2348056003003", health_id="BG-NG-00003", full_name="Adaeze Nwosu",       date_of_birth="1995-03-08", blood_group="B-",  region="Lagos",         trust_score=99.0),
    dict(phone_number="+2348056004004", health_id="BG-NG-00004", full_name="Lanre Abiodun",      date_of_birth="1978-07-30", blood_group="AB+", region="Lagos",         trust_score=95.0),
    # Fraud patients — last digit triggers CAMARA simulation
    dict(phone_number="+36370000005", health_id="BG-NG-00005", full_name="Tunde Oladele",      date_of_birth="1983-09-10", blood_group="A-",  region="Lagos",         trust_score=35.0),
    dict(phone_number="+2348056007000", health_id="BG-NG-00006", full_name="Kemi Fashola",       date_of_birth="1999-12-25", blood_group="B+",  region="Lagos",         trust_score=62.0),
    dict(phone_number="+2348067001001", health_id="BG-NG-00007", full_name="Fatima Shehu",       date_of_birth="1992-04-18", blood_group="O+",  region="Abuja",         trust_score=98.0),
    dict(phone_number="+2348067002002", health_id="BG-NG-00008", full_name="Mohammed Al-Amin",   date_of_birth="1975-08-05", blood_group="A+",  region="Abuja",         trust_score=96.0),
    dict(phone_number="+2348067003003", health_id="BG-NG-00009", full_name="Amina Bello",        date_of_birth="2001-06-22", blood_group="AB-", region="Abuja",         trust_score=100.0),
    dict(phone_number="+2348078001001", health_id="BG-NG-00010", full_name="Yusuf Abdullahi",    date_of_birth="1980-11-03", blood_group="A+",  region="Kano",          trust_score=85.0),
    dict(phone_number="+2348078002002", health_id="BG-NG-00011", full_name="Aisha Garba",        date_of_birth="1993-07-19", blood_group="O-",  region="Kano",          trust_score=88.0),
    dict(phone_number="+2348089001001", health_id="BG-NG-00012", full_name="Ngozi Williams",     date_of_birth="2000-03-08", blood_group="B-",  region="Port Harcourt", trust_score=72.0),
    dict(phone_number="+2348089002002", health_id="BG-NG-00013", full_name="Tonye Amadi",        date_of_birth="1987-09-14", blood_group="O+",  region="Port Harcourt", trust_score=95.0),
    dict(phone_number="+2348090001001", health_id="BG-NG-00014", full_name="Obiora Eze",         date_of_birth="1982-05-25", blood_group="AB+", region="Enugu",         trust_score=94.0),
    dict(phone_number="+2348091001001", health_id="BG-NG-00015", full_name="Wale Adeleke",       date_of_birth="1977-08-22", blood_group="A+",  region="Ibadan",        trust_score=89.0),
    dict(phone_number="+2348092001001", health_id="BG-NG-00016", full_name="Malam Audu Bello",   date_of_birth="1965-03-01", blood_group="O+",  region="Kano",          trust_score=80.0),
    dict(phone_number="+2348092002002", health_id="BG-NG-00017", full_name="Mama Ngozi",         date_of_birth="1960-07-04", blood_group="A+",  region="Enugu",         trust_score=75.0),
    dict(phone_number="+2348092003003", health_id="BG-NG-00018", full_name="Pastor Elijah",      date_of_birth="1972-12-20", blood_group="B-",  region="Port Harcourt", trust_score=83.0),
    dict(phone_number="+23324001001",   health_id="BG-GH-00001", full_name="Kofi Mensah",        date_of_birth="1985-04-11", blood_group="O+",  region="Accra, Ghana",  trust_score=96.0),
    dict(phone_number="+23324002002",   health_id="BG-GH-00002", full_name="Abena Asante",       date_of_birth="1993-08-17", blood_group="B+",  region="Accra, Ghana",  trust_score=94.0),
]

DRUGS = [
    dict(batch_code="ACT-MALARIA-001",    drug_name="Artemether-Lumefantrine 20/120mg (Coartem)",         manufacturer="Novartis Pharma Nigeria",         manufacture_date="2024-01-10", expiry_date="2026-12-31", cold_chain_required=False, min_temp_celsius=None, max_temp_celsius=None, authorized_facility_codes=NATIONAL+["FAC-ACC-001"], quantity=25000, is_recalled=False, recall_reason=None, nafdac_number="A4-0082"),
    dict(batch_code="ACT-ANTIBIOTIC-001", drug_name="Amoxicillin 500mg Capsules",                         manufacturer="Emzor Pharmaceutical Industries", manufacture_date="2024-03-01", expiry_date="2026-06-30", cold_chain_required=False, min_temp_celsius=None, max_temp_celsius=None, authorized_facility_codes=NATIONAL,                quantity=50000, is_recalled=False, recall_reason=None, nafdac_number="A7-1234"),
    dict(batch_code="ACT-PARACETAMOL-001",drug_name="Paracetamol 500mg Tablets (May & Baker)",            manufacturer="May & Baker Nigeria",            manufacture_date="2024-09-01", expiry_date="2027-08-31", cold_chain_required=False, min_temp_celsius=None, max_temp_celsius=None, authorized_facility_codes=ALL_FAC,                  quantity=200000,is_recalled=False, recall_reason=None, nafdac_number="A1-0012"),
    dict(batch_code="ACT-METFORMIN-001",  drug_name="Metformin Hydrochloride 500mg",                      manufacturer="Fidson Healthcare",               manufacture_date="2024-06-15", expiry_date="2027-06-14", cold_chain_required=False, min_temp_celsius=None, max_temp_celsius=None, authorized_facility_codes=NATIONAL,                quantity=30000, is_recalled=False, recall_reason=None, nafdac_number="A9-3344"),
    dict(batch_code="ACT-ORS-001",        drug_name="Oral Rehydration Salts (ORS) Sachets",               manufacturer="Pharma-Deko Plc",                manufacture_date="2024-08-01", expiry_date="2027-07-31", cold_chain_required=False, min_temp_celsius=None, max_temp_celsius=None, authorized_facility_codes=ALL_FAC,                  quantity=500000,is_recalled=False, recall_reason=None, nafdac_number="A1-0090"),
    dict(batch_code="ACT-ARV-001",        drug_name="Tenofovir/Lamivudine/Efavirenz 300/300/600mg (ARV)", manufacturer="Aspen Pharmacare Nigeria",        manufacture_date="2024-02-01", expiry_date="2026-01-31", cold_chain_required=False, min_temp_celsius=None, max_temp_celsius=None, authorized_facility_codes=["FAC-LAG-001","FAC-ABJ-001","FAC-PHC-001"], quantity=8000, is_recalled=False, recall_reason=None, nafdac_number="A6-8899"),
    dict(batch_code="CC-HEPB-001",        drug_name="Hepatitis B Vaccine 10mcg/mL",                       manufacturer="Bio Farma Indonesia",             manufacture_date="2024-08-01", expiry_date="2026-07-31", cold_chain_required=True,  min_temp_celsius=2.0,  max_temp_celsius=8.0,  authorized_facility_codes=["FAC-LAG-001","FAC-ABJ-001","FAC-KAN-001"], quantity=10000,is_recalled=False, recall_reason=None, nafdac_number="V1-5678"),
    dict(batch_code="CC-INSULIN-001",     drug_name="Insulin Glargine 100U/mL (Lantus)",                  manufacturer="Sanofi Nigeria",                  manufacture_date="2024-07-01", expiry_date="2026-06-30", cold_chain_required=True,  min_temp_celsius=2.0,  max_temp_celsius=8.0,  authorized_facility_codes=["FAC-LAG-001","FAC-LAG-002","FAC-ABJ-001"], quantity=5000, is_recalled=False, recall_reason=None, nafdac_number="A9-1122"),
    dict(batch_code="EXP-AMOX-001",       drug_name="Amoxicillin 250mg Syrup (Expired)",                  manufacturer="Evans Medical Nigeria",           manufacture_date="2022-01-01", expiry_date="2023-12-31", cold_chain_required=False, min_temp_celsius=None, max_temp_celsius=None, authorized_facility_codes=NATIONAL,                quantity=1200,  is_recalled=False, recall_reason=None, nafdac_number="A7-4455"),
    dict(batch_code="EXP-HEPB-001",       drug_name="Hepatitis B Vaccine (Expired)",                      manufacturer="Bio Farma Indonesia",             manufacture_date="2022-06-01", expiry_date="2024-05-31", cold_chain_required=True,  min_temp_celsius=2.0,  max_temp_celsius=8.0,  authorized_facility_codes=["FAC-LAG-001","FAC-KAN-001"],               quantity=500,   is_recalled=False, recall_reason=None, nafdac_number="V1-3300"),
    dict(batch_code="FAKE-PARA-001",      drug_name="Paracetamol 500mg (COUNTERFEIT)",                    manufacturer="Unknown",                         manufacture_date="2024-01-01", expiry_date="2027-01-01", cold_chain_required=False, min_temp_celsius=None, max_temp_celsius=None, authorized_facility_codes=[],                       quantity=0,     is_recalled=True,  recall_reason="Unregistered. Toxic adulterants found. NAFDAC REF: RC-2024-001",              nafdac_number=None),
    dict(batch_code="RECALL-COUGH-001",   drug_name="PediRelief Cough Syrup 100mL (Recalled)",            manufacturer="Maiden Pharmaceuticals",          manufacture_date="2023-09-01", expiry_date="2025-08-31", cold_chain_required=False, min_temp_celsius=None, max_temp_celsius=None, authorized_facility_codes=[],                       quantity=0,     is_recalled=True,  recall_reason="Diethylene glycol contamination. Linked to child deaths. WHO Alert 2023.",    nafdac_number="A3-7890"),
    dict(batch_code="RECALL-MALARIA-001", drug_name="Chloroquine 250mg (Substandard)",                    manufacturer="PharmaCo Ltd (Unverified)",       manufacture_date="2023-11-01", expiry_date="2026-10-31", cold_chain_required=False, min_temp_celsius=None, max_temp_celsius=None, authorized_facility_codes=[],                       quantity=0,     is_recalled=True,  recall_reason="Active ingredient 40% below dose. Substandard. NAFDAC REF: RC-2023-017",     nafdac_number="A4-0000"),
]

EMERGENCIES = [
    dict(phone_number="+2348056001001", patient_name="Chidinma Obi",      emergency_type="medical",       location_lat=6.5095,  location_lng=3.3711, location_address="Surulere, Lagos",         location_accuracy_m=187, maps_link="https://maps.google.com/?q=6.5095,3.3711",   status="resolved",   assigned_facility="Lagos University Teaching Hospital (LUTH)",    assigned_facility_code="FAC-LAG-001", distance_to_facility_km=2.1, qos_session_id="QOS-001001-DEMO", notes="Demo emergency — resolved.",          created_at=ago(days=14), resolved_at=ago(days=14, hours=2)),
    dict(phone_number="+2348056004004", patient_name="Lanre Abiodun",     emergency_type="ambulance",     location_lat=6.4281,  location_lng=3.4217, location_address="Victoria Island, Lagos", location_accuracy_m=220, maps_link="https://maps.google.com/?q=6.4281,3.4217",   status="resolved",   assigned_facility="Reddington Hospital Victoria Island",           assigned_facility_code="FAC-LAG-002", distance_to_facility_km=5.2, qos_session_id="QOS-004004-DEMO", notes="Demo emergency — resolved.",          created_at=ago(days=10), resolved_at=ago(days=10, hours=1)),
    dict(phone_number="+2348067001001", patient_name="Fatima Shehu",      emergency_type="medical",       location_lat=9.0579,  location_lng=7.4951, location_address="Wuse II, Abuja",         location_accuracy_m=150, maps_link="https://maps.google.com/?q=9.0579,7.4951",   status="dispatched", assigned_facility="National Hospital Abuja",                       assigned_facility_code="FAC-ABJ-001", distance_to_facility_km=1.8, qos_session_id="QOS-001001-ABUJA", notes="Ambulance en route.",              created_at=ago(hours=4),  resolved_at=None),
    dict(phone_number="+2348078001001", patient_name="Yusuf Abdullahi",   emergency_type="ambulance",     location_lat=12.0022, location_lng=8.5920, location_address="Kano City Centre",       location_accuracy_m=300, maps_link="https://maps.google.com/?q=12.0022,8.592",   status="dispatched", assigned_facility="Aminu Kano Teaching Hospital",                  assigned_facility_code="FAC-KAN-001", distance_to_facility_km=3.1, qos_session_id="QOS-001001-KANO",  notes="Ambulance dispatched.",            created_at=ago(hours=2),  resolved_at=None),
    dict(phone_number="+2348089001001", patient_name="Ngozi Williams",    emergency_type="drug_reaction", location_lat=4.8156,  location_lng=7.0498, location_address="GRA Port Harcourt",      location_accuracy_m=200, maps_link="https://maps.google.com/?q=4.8156,7.0498",   status="dispatched", assigned_facility="University of Port Harcourt Teaching Hospital", assigned_facility_code="FAC-PHC-001", distance_to_facility_km=2.5, qos_session_id="QOS-001001-PHC",   notes="Drug reaction — dispatched.",      created_at=ago(hours=1),  resolved_at=None),
    dict(phone_number="+2348056007000", patient_name="Kemi Fashola",      emergency_type="mental_health", location_lat=6.5612,  location_lng=3.3588, location_address="Oregun, Lagos",          location_accuracy_m=400, maps_link="https://maps.google.com/?q=6.5612,3.3588",   status="pending",    assigned_facility=None,                                            assigned_facility_code=None,          distance_to_facility_km=None,qos_session_id="QOS-007000-NEW",  notes="Awaiting dispatch.",               created_at=ago(minutes=5),resolved_at=None),
    dict(phone_number="+2348067003003", patient_name="Amina Bello",       emergency_type="medical",       location_lat=9.0300,  location_lng=7.5000, location_address="Maitama, Abuja",         location_accuracy_m=250, maps_link="https://maps.google.com/?q=9.03,7.5",        status="pending",    assigned_facility=None,                                            assigned_facility_code=None,          distance_to_facility_km=None,qos_session_id="QOS-003003-NEW",  notes="Awaiting dispatch.",               created_at=ago(minutes=2),resolved_at=None),
    dict(phone_number="+2348092001001", patient_name="Malam Audu Bello",  emergency_type="ambulance",     location_lat=12.0022, location_lng=8.5920, location_address="Kano Rural",             location_accuracy_m=480, maps_link="https://maps.google.com/?q=12.0022,8.592",   status="pending",    assigned_facility=None,                                            assigned_facility_code=None,          distance_to_facility_km=None,qos_session_id="QOS-001001-RUR",  notes="Rural emergency — awaiting dispatch.",created_at=ago(minutes=1),resolved_at=None),
    dict(phone_number="+2348056002002", patient_name="Emeka Dike",        emergency_type="medical",       location_lat=6.5244,  location_lng=3.3792, location_address="Yaba, Lagos",            location_accuracy_m=130, maps_link="https://maps.google.com/?q=6.5244,3.3792",   status="resolved",   assigned_facility="Lagos University Teaching Hospital (LUTH)",    assigned_facility_code="FAC-LAG-001", distance_to_facility_km=2.0, qos_session_id="QOS-002002-DEMO", notes="Demo emergency — resolved.",          created_at=ago(days=3),   resolved_at=ago(days=3, hours=4)),
    dict(phone_number="+2348056001001", patient_name="Chidinma Obi",      emergency_type="ambulance",     location_lat=6.5095,  location_lng=3.3711, location_address="Surulere, Lagos",         location_accuracy_m=187, maps_link="https://maps.google.com/?q=6.5095,3.3711",   status="cancelled",  assigned_facility=None,                                            assigned_facility_code=None,          distance_to_facility_km=None,qos_session_id="QOS-001001-CAN",  notes="Patient cancelled after calling.",    created_at=ago(days=8),   resolved_at=ago(days=8, hours=1)),
]

TRUST_EVENTS = [
    dict(phone_number="+2348056006009", entity_type="patient", event_type="sim_swap_recent",    score_delta=-40.0, new_score=35.0,  meta={"sim_swap_detected": True,  "days_since_swap": 2, "number_verified": True}),
    dict(phone_number="+2348011006009", entity_type="worker",  event_type="sim_swap_recent",    score_delta=-40.0, new_score=38.0,  meta={"sim_swap_detected": True,  "days_since_swap": 2}),
    dict(phone_number="+2348056007000", entity_type="patient", event_type="number_not_verified", score_delta=-20.0, new_score=62.0,  meta={"number_verified": False,   "device_status": "active"}),
    dict(phone_number="+2348056006009", entity_type="patient", event_type="repeated_fraud_flag", score_delta=-30.0, new_score=5.0,   meta={"manual": True, "reason": "Confirmed identity fraud — drug diversion attempt"}),
    dict(phone_number="+2348056001001", entity_type="patient", event_type="verified_interaction",score_delta=5.0,   new_score=100.0, meta={"number_verified": True, "sim_swap_detected": False, "device_status": "active"}),
    dict(phone_number="+2348056002002", entity_type="patient", event_type="verified_interaction",score_delta=5.0,   new_score=97.0,  meta={"number_verified": True, "sim_swap_detected": False, "device_status": "active"}),
    dict(phone_number="+2348067001001", entity_type="patient", event_type="verified_interaction",score_delta=5.0,   new_score=98.0,  meta={"number_verified": True, "sim_swap_detected": False, "device_status": "active"}),
    dict(phone_number="+2348011001001", entity_type="worker",  event_type="verified_interaction",score_delta=5.0,   new_score=98.0,  meta={"number_verified": True, "sim_swap_detected": False, "device_status": "active"}),
    dict(phone_number="+2348011004004", entity_type="worker",  event_type="verified_interaction",score_delta=5.0,   new_score=100.0, meta={"number_verified": True, "sim_swap_detected": False, "device_status": "active"}),
]



# ─────────────────────────────────────────────────────────────────────────────
# Seeder
# ─────────────────────────────────────────────────────────────────────────────

async def seed():
    print("\nBioGuard Demo Seed")
    print("=" * 50)

    # Drop and recreate all tables cleanly
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    print("  ✓  Tables reset")

    async with Session() as db:

        # Facilities
        for f in FACILITIES:
            db.add(models.Facility(**f, is_active=True))
        await db.commit()
        print(f"  ✓  {len(FACILITIES)} facilities")

        # Patients
        for p in PATIENTS:
            db.add(models.Patient(**p, is_active=True))
        await db.commit()
        print(f"  ✓  {len(PATIENTS)} patients")

        # Healthcare workers
        for w in WORKERS:
            db.add(models.HealthcareWorker(**w))
        await db.commit()
        print(f"  ✓  {len(WORKERS)} healthcare workers")

        # Drugs
        for d in DRUGS:
            db.add(models.Drug(**d))
        await db.commit()
        print(f"  ✓  {len(DRUGS)} drug batches")

        # Drug verifications
        phones    = [p["phone_number"] for p in PATIENTS[:12]]
        authentic = ["ACT-MALARIA-001","ACT-ANTIBIOTIC-001","ACT-PARACETAMOL-001","ACT-ORS-001","CC-HEPB-001"]
        v_count   = 0

        for batch in authentic:
            for _ in range(5):
                db.add(models.DrugVerification(
                    batch_code=batch,
                    verified_by_phone=random.choice(phones),
                    verification_channel=random.choice(["api", "mobile"]),
                    verification_location=random.choice(NATIONAL),
                    result="authentic",
                    trust_score_at_time=round(random.uniform(90, 100), 1),
                    camara_location_match=True,
                    alert_sent=False,
                    notes="All checks passed.",
                    created_at=ago(days=random.randint(0, 30)),
                ))
                v_count += 1

        for batch in ["EXP-AMOX-001", "EXP-HEPB-001"]:
            for _ in range(3):
                db.add(models.DrugVerification(
                    batch_code=batch,
                    verified_by_phone=random.choice(phones),
                    verification_channel="api",
                    result="expired",
                    trust_score_at_time=10.0,
                    camara_location_match=True,
                    alert_sent=True,
                    notes="Expired drug caught and blocked.",
                    created_at=ago(days=random.randint(1, 60)),
                ))
                v_count += 1

        for batch in ["FAKE-PARA-001", "RECALL-COUGH-001", "RECALL-MALARIA-001"]:
            for _ in range(4):
                db.add(models.DrugVerification(
                    batch_code=batch,
                    verified_by_phone=random.choice(phones),
                    verification_channel=random.choice(["api", "mobile"]),
                    verification_location="UNAUTHORIZED",
                    result="recalled",
                    trust_score_at_time=0.0,
                    camara_location_match=False,
                    alert_sent=True,
                    notes="ALERT: Recalled product. NAFDAC notified.",
                    created_at=ago(days=random.randint(0, 90)),
                ))
                v_count += 1

        await db.commit()
        print(f"  ✓  {v_count} drug verifications")

        # Emergencies
        for e in EMERGENCIES:
            db.add(models.EmergencyRequest(**e))
        await db.commit()
        print(f"  ✓  {len(EMERGENCIES)} emergency requests")

        # Trust events
        for t in TRUST_EVENTS:
            db.add(models.TrustEvent(
                **t,
                created_at=ago(days=random.randint(0, 10)),
            ))
        await db.commit()
        print(f"  ✓  {len(TRUST_EVENTS)} trust events")


    await engine.dispose()

    print()
    print("=" * 50)
    print("       Seed complete!\n")
    print("       Demo scenarios ready:")
    print("       Authentic drug:    ACT-MALARIA-001")
    print("       Expired drug:     EXP-AMOX-001")
    print("       Recalled:         FAKE-PARA-001")
    print("       Trusted worker:   HW-001")
    print("       Fraud worker:     HW-006  (trust 38, SIM swap)")
    print("       Pending alerts:   GET /emergency?status_filter=pending")
    print()
    print("       → http://localhost:8000/docs")


if __name__ == "__main__":
    asyncio.run(seed())
