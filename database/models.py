from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


class Vacancy(Base):
    __tablename__ = "vacancies"

    id = Column(Integer, primary_key=True)
    source_key = Column(String(64), unique=True, nullable=True, index=True)
    source_row = Column(Integer, nullable=True)
    organization = Column(String(200))
    division = Column(String(200))
    position = Column(String(200))
    sphere = Column(String(100))
    salary = Column(String(100))
    schedule = Column(String(100))
    work_format = Column(String(100))
    description = Column(Text)
    vacancy_url = Column(Text)
    employment_format = Column(String(100))
    feature1 = Column(String(200))
    feature2 = Column(String(200))
    feature3 = Column(String(200))
    itiabd = Column(Boolean, default=False)
    ioo = Column(Boolean, default=False)
    finfak = Column(Boolean, default=False)
    vshu = Column(Boolean, default=False)
    nab = Column(Boolean, default=False)
    snimk = Column(Boolean, default=False)
    meo = Column(Boolean, default=False)
    feb = Column(Boolean, default=False)
    yurfak = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class VacancySyncState(Base):
    __tablename__ = "vacancy_sync_state"

    id = Column(Integer, primary_key=True, default=1)
    status = Column(String(20), nullable=False, default="idle")
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    error_message = Column(Text)
    source_count = Column(Integer, nullable=False, default=0)
    added_count = Column(Integer, nullable=False, default=0)
    updated_count = Column(Integer, nullable=False, default=0)
    deleted_count = Column(Integer, nullable=False, default=0)


class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), unique=True, nullable=False, index=True)
    description = Column(Text)
    logo_url = Column(Text)
    achievements = Column(Text)
    parent_company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, index=True)
    is_partner = Column(Boolean, default=False, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    divisions = relationship("Division", back_populates="company", cascade="all, delete-orphan", order_by="Division.id")
    parent_company = relationship(
        "Company",
        remote_side=[id],
        back_populates="child_companies",
    )
    child_companies = relationship(
        "Company",
        back_populates="parent_company",
        cascade="save-update",
        order_by="Company.name",
    )


class Division(Base):
    __tablename__ = "divisions"

    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    company = relationship("Company", back_populates="divisions")


class MiniappEvent(Base):
    __tablename__ = "miniapp_events"

    id = Column(Integer, primary_key=True)
    category = Column(String(50), nullable=False, default="Другое")
    format = Column(String(50), nullable=False, default="Офлайн")
    image_url = Column(Text)
    lead = Column(String(255))
    title = Column(String(255), nullable=False)
    date_text = Column(String(255))
    starts_at = Column(DateTime(timezone=True), index=True)
    place = Column(String(255))
    description = Column(Text)
    deadline_text = Column(String(255))
    external_url = Column(Text)
    capacity = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    registrations = relationship("MiniappEventRegistration", back_populates="event", cascade="all, delete-orphan")


class MiniappEventRegistration(Base):
    __tablename__ = "miniapp_event_registrations"
    __table_args__ = (
        UniqueConstraint("event_id", "max_user_id", name="uq_miniapp_event_registration_max"),
        UniqueConstraint("event_id", "profile_email", name="uq_miniapp_event_registration_email"),
    )

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("miniapp_events.id", ondelete="CASCADE"), nullable=False, index=True)
    max_user_id = Column(BigInteger, nullable=True, index=True)
    profile_email = Column(String(320), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="confirmed", index=True)
    promoted_at = Column(DateTime(timezone=True))
    reminder_day_sent_at = Column(DateTime(timezone=True))
    reminder_two_hours_sent_at = Column(DateTime(timezone=True))
    in_app_reminder_day_sent_at = Column(DateTime(timezone=True))
    in_app_reminder_two_hours_sent_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    event = relationship("MiniappEvent", back_populates="registrations")


class MiniappNotification(Base):
    __tablename__ = "miniapp_notifications"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, nullable=False, index=True)
    max_user_id = Column(BigInteger, nullable=True, index=True)
    profile_email = Column(String(320), nullable=True, index=True)
    kind = Column(String(32), nullable=False)
    event_title = Column(String(255), nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    read_at = Column(DateTime(timezone=True), nullable=True)


class StudentProfile(Base):
    __tablename__ = "student_profiles"

    email = Column(String(320), primary_key=True)
    faculty = Column(String(120), nullable=False, default="")
    course = Column(String(32), nullable=False, default="")
    group = Column(String(80), nullable=False, default="")
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)


class MiniappAction(Base):
    __tablename__ = "miniapp_actions"

    id = Column(Integer, primary_key=True)
    max_user_id = Column(BigInteger, nullable=True, index=True)
    session_id = Column(String(64), nullable=False, index=True)
    event_type = Column(String(24), nullable=False, index=True)
    action = Column(String(100), nullable=False, index=True)
    route = Column(String(255), nullable=False, index=True)
    target = Column(String(255))
    raw_data = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
