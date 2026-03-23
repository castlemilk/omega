"""omega.bridge — Python clients for Go Connect-RPC services + Python pipeline server."""

from omega.bridge.adversarial_client import AdversarialServiceClient, AdversarialServiceError
from omega.bridge.autonomy_client import AutonomyServiceClient, AutonomyServiceError
from omega.bridge.improvement_client import ImprovementServiceClient, ImprovementServiceError
from omega.bridge.memory_client import MemoryServiceClient, MemoryServiceError
from omega.bridge.pipeline_server import StepHandlerRegistry, start_pipeline_server
from omega.bridge.pipeline_types import ExecuteStepRequest, ExecuteStepResponse, PingResponse
from omega.bridge.safety_client import SafetyServiceClient, SafetyServiceError
from omega.bridge.state_client import StateServiceClient, StateServiceError

__all__ = [
    "AdversarialServiceClient",
    "AdversarialServiceError",
    "AutonomyServiceClient",
    "AutonomyServiceError",
    "ExecuteStepRequest",
    "ExecuteStepResponse",
    "ImprovementServiceClient",
    "ImprovementServiceError",
    "MemoryServiceClient",
    "MemoryServiceError",
    "PingResponse",
    "SafetyServiceClient",
    "SafetyServiceError",
    "StateServiceClient",
    "StateServiceError",
    "StepHandlerRegistry",
    "start_pipeline_server",
]
