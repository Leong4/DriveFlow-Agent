from typing import Optional
from pydantic import BaseModel, Field


class CarStateContext(BaseModel):
    battery_level: Optional[float] = Field(None, description="Current battery level in percent (0–100)")
    remaining_range_km: Optional[float] = Field(None, description="Estimated remaining driving range in km")
