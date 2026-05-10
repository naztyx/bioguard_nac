from sqlalchemy import (
    Column, String, Integer, Float, Boolean,
    DateTime, JSON, Text, ForeignKey,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Patient(Base):
    __tablename__ = "patients"

    id            = Column(Integer, primary_key=True, index=True)
    phone_number  = Column(String(20), unique=True, index=True, nullable=False)
    health_id     = Column(String(20), unique=True, index=True)
    full_name     = Column(String(100))
    date_of_birth = Column(String(20))
    blood_group   = Column(String(5))
    region        = Column(String(100))
    trust_score   = Column(Float, default=100.0)
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), onupdate=func.now())

    # No ORM relationship to EmergencyRequest — emergencies can be raised by
    # unregistered callers so a FK would wrongly block them.
    # The routers query via explicit select() — this relationship is not needed.


class HealthcareWorker(Base):
    __tablename__ = "healthcare_workers"

    id             = Column(Integer, primary_key=True, index=True)
    phone_number   = Column(String(20), unique=True, index=True, nullable=False)
    worker_id      = Column(String(20), unique=True, index=True, nullable=False)
    full_name      = Column(String(100))
    facility_name  = Column(String(200))
    facility_code  = Column(String(20), ForeignKey("facilities.facility_code"), nullable=True)
    specialization = Column(String(100))
    is_verified    = Column(Boolean, default=False)
    trust_score    = Column(Float, default=100.0)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())
    updated_at     = Column(DateTime(timezone=True), onupdate=func.now())

    facility       = relationship("Facility", back_populates="workers")


class Facility(Base):
    __tablename__ = "facilities"

    id            = Column(Integer, primary_key=True, index=True)
    facility_code = Column(String(20), unique=True, index=True, nullable=False)
    name          = Column(String(200), nullable=False)
    facility_type = Column(String(50))
    region        = Column(String(100))
    location_lat  = Column(Float)
    location_lng  = Column(Float)
    phone_number  = Column(String(20))
    is_active     = Column(Boolean, default=True)

    workers       = relationship("HealthcareWorker", back_populates="facility")


class Drug(Base):
    __tablename__ = "drugs"

    id                        = Column(Integer, primary_key=True, index=True)
    batch_code                = Column(String(50), unique=True, index=True, nullable=False)
    drug_name                 = Column(String(200), nullable=False)
    manufacturer              = Column(String(200))
    manufacture_date          = Column(String(20))
    expiry_date               = Column(String(20))
    cold_chain_required       = Column(Boolean, default=False)
    min_temp_celsius          = Column(Float, nullable=True)
    max_temp_celsius          = Column(Float, nullable=True)
    authorized_facility_codes = Column(JSON, default=list)
    quantity                  = Column(Integer, default=0)
    is_recalled               = Column(Boolean, default=False)
    recall_reason             = Column(Text, nullable=True)
    nafdac_number             = Column(String(50), nullable=True)
    created_at                = Column(DateTime(timezone=True), server_default=func.now())

    verifications             = relationship("DrugVerification", back_populates="drug_ref")


class DrugVerification(Base):
    __tablename__ = "drug_verifications"

    id                    = Column(Integer, primary_key=True, index=True)
    batch_code            = Column(String(50), ForeignKey("drugs.batch_code"), index=True)
    verified_by_phone     = Column(String(20))
    verification_channel  = Column(String(20), default="api")
    verification_location = Column(String(300))
    result                = Column(String(20))   # authentic|counterfeit|expired|recalled|not_found
    trust_score_at_time   = Column(Float)
    camara_location_match = Column(Boolean, nullable=True)
    alert_sent            = Column(Boolean, default=False)
    notes                 = Column(Text)
    created_at            = Column(DateTime(timezone=True), server_default=func.now())

    drug_ref              = relationship("Drug", back_populates="verifications")


class EmergencyRequest(Base):
    __tablename__ = "emergency_requests"

    id                      = Column(Integer, primary_key=True, index=True)
    phone_number            = Column(String(20), index=True)
    patient_name            = Column(String(100))
    emergency_type          = Column(String(50))
    location_lat            = Column(Float, nullable=True)
    location_lng            = Column(Float, nullable=True)
    location_address        = Column(String(300))
    location_accuracy_m     = Column(Integer, nullable=True)
    maps_link               = Column(String(300), nullable=True)
    status                  = Column(String(20), default="pending")
    assigned_facility       = Column(String(200))
    assigned_facility_code  = Column(String(20), nullable=True)
    distance_to_facility_km = Column(Float, nullable=True)
    qos_session_id          = Column(String(100), nullable=True)
    notes                   = Column(Text)
    created_at              = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at             = Column(DateTime(timezone=True), nullable=True)

    # No ORM relationship back to Patient — see note on Patient model above.


class TrustEvent(Base):
    __tablename__ = "trust_events"

    id           = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String(20), index=True, nullable=False)
    entity_type  = Column(String(20))
    event_type   = Column(String(100))
    score_delta  = Column(Float)
    new_score    = Column(Float)
    meta         = Column(JSON, default=dict)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())

