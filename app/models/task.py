from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

class Task(BaseModel):
    id: str = Field(..., description="Unique identifier for the task (e.g., 'task_1')")
    type: str = Field(..., description="Type of the task (e.g., 'restaurant', 'destination', 'charging_station')")
    name: Optional[str] = Field(None, description="Explicit location or destination name (e.g., 'Baiyun Mountain')")
    brand: Optional[str] = Field(None, description="Specific brand constraint (e.g., 'McDonalds')")
    constraints: Optional[Dict[str, Any]] = Field(None, description="Simple constraints for the task")
    order_hint: int = Field(..., description="Hint for the order of task execution (e.g., 1, 2, 3)")
