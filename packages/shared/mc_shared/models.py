import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from mc_shared.db import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(32), default="USER")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class OrganizationUser(Base):
    __tablename__ = "organization_users"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_organization_users"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_projects_org_slug"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80))
    rpm_limit: Mapped[int] = mapped_column(Integer, default=60)
    tpm_limit: Mapped[int] = mapped_column(Integer, default=100000)
    daily_request_limit: Mapped[int] = mapped_column(Integer, default=10000)
    monthly_request_limit: Mapped[int] = mapped_column(Integer, default=300000)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Model(Base):
    __tablename__ = "models"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    model_family: Mapped[str] = mapped_column(String(80), default="")
    model_type: Mapped[str] = mapped_column(String(32), default="chat")
    provider_name: Mapped[str] = mapped_column(String(80), default="")
    license: Mapped[str] = mapped_column(String(80), default="")
    license_url: Mapped[str] = mapped_column(String(300), default="")
    parameter_count: Mapped[str] = mapped_column(String(32), default="")
    context_window: Mapped[int] = mapped_column(Integer, default=8192)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=2048)
    supports_chat: Mapped[bool] = mapped_column(Boolean, default=True)
    supports_streaming: Mapped[bool] = mapped_column(Boolean, default=True)
    supports_tools: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_structured_output: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_vision: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_audio: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_embeddings: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Runtime(Base):
    __tablename__ = "runtimes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80))
    type: Mapped[str] = mapped_column(String(32))
    endpoint: Mapped[str] = mapped_column(String(500), default="")
    api_key_encrypted: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="offline")
    gpu_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    gpu_count: Mapped[int] = mapped_column(Integer, default=0)
    health_status: Mapped[str] = mapped_column(String(32), default="unknown")
    last_health_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Deployment(Base):
    __tablename__ = "deployments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    model_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("models.id", ondelete="CASCADE"), index=True)
    runtime_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("runtimes.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80))
    runtime_model_name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    desired_status: Mapped[str] = mapped_column(String(32), default="running")
    replicas: Mapped[int] = mapped_column(Integer, default=1)
    gpu_required: Mapped[int] = mapped_column(Integer, default=0)
    gpu_memory_required: Mapped[int] = mapped_column(Integer, default=0)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    health_status: Mapped[str] = mapped_column(String(32), default="unknown")
    last_health_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProjectModel(Base):
    __tablename__ = "project_models"
    __table_args__ = (UniqueConstraint("project_id", "model_id", name="uq_project_models"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    model_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("models.id", ondelete="CASCADE"), index=True)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    key_prefix: Mapped[str] = mapped_column(String(24), index=True)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rpm_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tpm_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_request_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_request_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ApiKeyModel(Base):
    __tablename__ = "api_key_models"
    __table_args__ = (UniqueConstraint("api_key_id", "model_id", name="uq_api_key_models"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    api_key_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("api_keys.id", ondelete="CASCADE"), index=True)
    model_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("models.id", ondelete="CASCADE"), index=True)


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("organizations.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), index=True)
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("api_keys.id"), nullable=True)
    model_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("models.id"), nullable=True)
    deployment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("deployments.id"), nullable=True)
    runtime_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("runtimes.id"), nullable=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    endpoint: Mapped[str] = mapped_column(String(120))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    time_to_first_token_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status_code: Mapped[int] = mapped_column(Integer, default=200)
    streaming: Mapped[bool] = mapped_column(Boolean, default=False)
    error_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    event_type: Mapped[str] = mapped_column(String(64))
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
