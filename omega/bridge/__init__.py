"""omega.bridge — Python clients for Go Connect-RPC services."""

from omega.bridge.adversarial_client import AdversarialServiceClient, AdversarialServiceError
from omega.bridge.autonomy_client import AutonomyServiceClient, AutonomyServiceError
from omega.bridge.improvement_client import ImprovementServiceClient, ImprovementServiceError
from omega.bridge.memory_client import MemoryServiceClient, MemoryServiceError
from omega.bridge.safety_client import SafetyServiceClient, SafetyServiceError
from omega.bridge.state_client import StateServiceClient, StateServiceError

__all__ = [
    "AdversarialServiceClient",
    "AdversarialServiceError",
    "AutonomyServiceClient",
    "AutonomyServiceError",
    "ImprovementServiceClient",
    "ImprovementServiceError",
    "MemoryServiceClient",
    "MemoryServiceError",
    "SafetyServiceClient",
    "SafetyServiceError",
    "StateServiceClient",
    "StateServiceError",
]
