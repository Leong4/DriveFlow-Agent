from abc import ABC, abstractmethod
from app.tools.schemas import ToolInput, ToolResult


class BaseTool(ABC):
    """Abstract base class for all tools in the DriveFlow Agent system.

    Every tool must:
      1. Expose a `name` property.
      2. Implement `run(tool_input) -> ToolResult`.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this tool."""
        ...

    @abstractmethod
    def run(self, tool_input: ToolInput) -> ToolResult:
        """Execute the tool with a standardised input and return a standardised result."""
        ...
