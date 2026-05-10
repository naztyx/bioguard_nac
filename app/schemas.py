from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Any
from datetime import datetime


class APIResponse(BaseModel):
    success: bool
    message: str
    data: Optional[Any] = None


# ── Patient ───────────────────────────────────────────────────────────────────
class PatientCreate(BaseModel):
    phone_number:  str
    full_name:     str
    date_of_birth: Optional[str] = None
    blood_group:   Optional[str] = None
    region:        Optional[str] = None


class PatientOut(BaseModel):
    id:           int
    phone_number: str
    health_id:    Optional[str]
    full_name:    Optional[str]
    blood_group:  Optional[str]
    region:       Optional[str]
    trust_score:  float
    is_active:    bool
    created_at:   datetime

    model_config = {"from_attributes": True}


# ── Healthcare Worker ─────────────────────────────────────────────────────────
class WorkerCreate(BaseModel):
    phone_number:   str
    worker_id:      str
    full_name:      str
    facility_name:  str
    facility_code:  Optional[str] = None
    specialization: Optional[str] = None


class WorkerOut(BaseModel):
    id:             int
    phone_number:   str
    worker_id:      str
    full_name:      Optional[str]
    facility_name:  Optional[str]
    specialization: Optional[str]
    is_verified:    bool
    trust_score:    float

    model_config = {"from_attributes": True}


class WorkerVerifyResponse(BaseModel):
    worker_id:         str
    full_name:         Optional[str]
    facility_name:     Optional[str]
    specialization:    Optional[str]
    is_verified:       bool
    trust_score:       float
    sim_swap_detected: bool
    number_verified:   bool
    trust_level:       str
    recommendation:    str


# ── Facility ──────────────────────────────────────────────────────────────────
class FacilityCreate(BaseModel):
    facility_code: str
    name:          str
    facility_type: str
    region:        str
    location_lat:  Optional[float] = None
    location_lng:  Optional[float] = None
    phone_number:  Optional[str] = None


class FacilityOut(BaseModel):
    facility_code: str
    name:          str
    facility_type: str
    region:        str
    location_lat:  Optional[float]
    location_lng:  Optional[float]
    phone_number:  Optional[str]
    is_active:     bool

    model_config = {"from_attributes": True}


# ── Drug ──────────────────────────────────────────────────────────────────────
class DrugCreate(BaseModel):
    batch_code:                str
    drug_name:                 str
    manufacturer:              str
    manufacture_date:          str
    expiry_date:               str
    cold_chain_required:       bool = False
    min_temp_celsius:          Optional[float] = None
    max_temp_celsius:          Optional[float] = None
    authorized_facility_codes: List[str] = []
    quantity:                  int = 0
    nafdac_number:             Optional[str] = None


class DrugVerifyRequest(BaseModel):
    batch_code:       str
    phone_number:     str
    facility_code:    Optional[str] = None
    location_lat:     Optional[float] = None
    location_lng:     Optional[float] = None


class DrugVerifyResponse(BaseModel):
    batch_code:          str
    drug_name:           Optional[str]  = None
    manufacturer:        Optional[str]  = None
    expiry_date:         Optional[str]  = None
    result:              str
    location_authorized: bool
    cold_chain_ok:       bool
    trust_score:         float
    safety_level:        str            # SAFE | WARNING | DANGER | CRITICAL
    message:             str
    action:              str            # what the user should do next
    nafdac_number:       Optional[str]  = None
    nafdac_hotline:      str            = "0800-1-623322"


class DrugOut(BaseModel):
    id:                 int
    batch_code:         str
    drug_name:          str
    manufacturer:       Optional[str]
    expiry_date:        str
    cold_chain_required: bool
    is_recalled:        bool
    quantity:           int
    nafdac_number:      Optional[str]

    model_config = {"from_attributes": True}


# ── Identity / Trust ──────────────────────────────────────────────────────────
class IdentityVerifyRequest(BaseModel):
    phone_number:  str
    entity_type:   str = "patient"
    location_lat:  Optional[float] = None
    location_lng:  Optional[float] = None


class IdentityVerifyResponse(BaseModel):
    phone_number:        str
    trust_score:         float
    trust_level:         str
    number_verified:     bool
    sim_swap_detected:   bool
    sim_swap_date:       Optional[str]
    device_status:       str
    location_consistent: bool
    recommendation:      str
    action_message:      str


# ── Emergency ─────────────────────────────────────────────────────────────────
VALID_EMERGENCY_TYPES = {"medical", "drug_reaction", "ambulance", "mental_health"}
VALID_STATUS_TRANSITIONS = {"dispatched", "resolved", "cancelled"}


class EmergencyCreate(BaseModel):
    phone_number:     str
    patient_name:     Optional[str] = None
    emergency_type:   str
    location_address: Optional[str] = None
    location_lat:     Optional[float] = None
    location_lng:     Optional[float] = None
    notes:            Optional[str] = None

    @field_validator("emergency_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in VALID_EMERGENCY_TYPES:
            raise ValueError(f"emergency_type must be one of: {sorted(VALID_EMERGENCY_TYPES)}")
        return v


class EmergencyOut(BaseModel):
    id:                      int
    phone_number:            str
    patient_name:            Optional[str]
    emergency_type:          str
    status:                  str
    location_lat:            Optional[float]
    location_lng:            Optional[float]
    location_address:        Optional[str]
    location_accuracy_m:     Optional[int]
    maps_link:               Optional[str]
    assigned_facility:       Optional[str]
    assigned_facility_code:  Optional[str]
    distance_to_facility_km: Optional[float]
    qos_session_id:          Optional[str]
    notes:                   Optional[str]
    created_at:              datetime
    resolved_at:             Optional[datetime]

    model_config = {"from_attributes": True}


class EmergencyUpdateStatus(BaseModel):
    status:            str
    assigned_facility: Optional[str] = None
    notes:             Optional[str] = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_STATUS_TRANSITIONS:
            raise ValueError(f"status must be one of: {sorted(VALID_STATUS_TRANSITIONS)}")
        return v
