"""Request and response contracts for application authentication."""

from datetime import datetime
from uuid import UUID

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not normalized:
            raise ValueError("username must not be blank")
        return normalized


class AuthUserRead(BaseModel):
    id: UUID
    username: str
    role: str
    company_id: UUID | None
    company_name: str | None


class AuthUserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=256)
    company_id: UUID
    role: Literal["ADMIN", "USER"] = "USER"

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not normalized:
            raise ValueError("username must not be blank")
        return normalized


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: AuthUserRead
