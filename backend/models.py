"""Pydantic request schemas with input validation.

All request validation is handled by FastAPI via these models.
"""

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class PredictRequest(BaseModel):
    """Request body for ``POST /api/predict``."""

    query: str = Field(..., min_length=8, max_length=2000, description="PQL query starting with PREDICT")
    graph_id: str = "default"
    entity_ids: Optional[list] = Field(None, description="Target entity IDs (max 1000)")
    anchor_time: Optional[str] = Field(None, description="ISO-format date, e.g. 2024-06-01")
    run_mode: str = Field(default="fast", pattern=r"^(fast|normal|best)$")
    explain: bool = False

    @field_validator("query")
    @classmethod
    def query_starts_with_predict(cls, v: str) -> str:
        q = v.strip()
        if not q.upper().startswith("PREDICT"):
            raise ValueError("Query must start with PREDICT")
        return q

    @field_validator("entity_ids")
    @classmethod
    def limit_entity_ids(cls, v: Optional[list]) -> Optional[list]:
        if v is not None and len(v) > 1000:
            raise ValueError("Maximum of 1000 entity IDs allowed")
        return v

    @field_validator("anchor_time")
    @classmethod
    def validate_anchor_time(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            from datetime import datetime
            try:
                datetime.fromisoformat(v)
            except ValueError as exc:
                raise ValueError(f"Invalid anchor_time format: {exc}")
        return v


class LoadDataRequest(BaseModel):
    """Request body for ``POST /api/load-dataset``."""

    dataset: str = Field(..., min_length=1, description="Dataset name: online_shopping, ecom, or steam")
    graph_id: str = "default"
