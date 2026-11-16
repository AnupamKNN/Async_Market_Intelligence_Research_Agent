"""Pydantic schemas for authentication requests and responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class AuthUserResponse(BaseModel):
    id: UUID
    email: EmailStr
    display_name: str
    email_verified: bool
    created_at: datetime


class AuthResponse(BaseModel):
    user: AuthUserResponse
    csrf_token: str


class AuthMessageResponse(BaseModel):
    message: str
