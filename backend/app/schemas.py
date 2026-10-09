from typing import Literal
from pydantic import BaseModel, Field


class Profile(BaseModel):
    weight_kg: float = Field(default=65, ge=30, le=250)
    experience: Literal["beginner", "regular"] = "beginner"
    goal: Literal["habit", "fitness"] = "habit"


class SessionSummary(BaseModel):
    session_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    input_version: int = Field(default=1, ge=1)
    exercise: Literal["squat", "jumping_jack"]
    source: Literal["simulation", "camera"]
    reps: int = Field(ge=0, le=10000)
    active_seconds: float = Field(ge=0, le=86400)
    observable_seconds: float = Field(ge=0, le=86400)
    form_events: int = Field(ge=0, le=10000)
    fatigue: int = Field(default=4, ge=0, le=10)
    discomfort: bool = False
    target_reps: int = Field(default=12, ge=1, le=100)
    persist: bool = False
    profile: Profile = Field(default_factory=Profile)


class AcceptProposal(BaseModel):
    input_version: int = Field(ge=1)


class FoodEntry(BaseModel):
    food_id: Literal["rice", "egg", "milk", "broccoli"]
    grams: float = Field(ge=1, le=3000)
