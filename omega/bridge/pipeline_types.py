# mypy: ignore-errors
"""omega.bridge.pipeline_types — PipelineService message types.

Re-exports from generated protobuf bindings (gen/python/omega/v1.py).
The generated types are betterproto dataclasses and are the source of
truth for all inter-service contracts.

Backward-compat helpers (from_json / to_json) are preserved as thin
shims over betterproto's from_dict / to_dict so existing callers need
not change.
"""

from __future__ import annotations

import importlib.util
import os
import sys

# ---------------------------------------------------------------------------
# Load generated module under a collision-free name.
# gen/python/omega/v1.py is generated from proto/omega/v1/ but "omega" is
# also this project's own top-level package, so we cannot put gen/python on
# sys.path directly.  Instead we load the file under the alias "_pb_omega_v1".
# ---------------------------------------------------------------------------
_GEN_FILE = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "gen", "python", "omega", "v1.py")
)

_MODULE_NAME = "_pb_omega_v1"
if _MODULE_NAME not in sys.modules:
    # Register a fake parent package so betterproto dataclasses can resolve
    # their __module__ attribute at import time.
    if "_pb_omega_v1_pkg" not in sys.modules:
        import types as _types

        _pkg = _types.ModuleType("_pb_omega_v1_pkg")
        sys.modules["_pb_omega_v1_pkg"] = _pkg

    spec = importlib.util.spec_from_file_location(_MODULE_NAME, _GEN_FILE)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot find generated protobuf bindings at {_GEN_FILE!r}")
    _mod = importlib.util.module_from_spec(spec)
    _mod.__package__ = "_pb_omega_v1_pkg"
    sys.modules[_MODULE_NAME] = _mod
    spec.loader.exec_module(_mod)

_pb = sys.modules[_MODULE_NAME]

_ExecuteStepRequest = _pb.ExecuteStepRequest
_ExecuteStepResponse = _pb.ExecuteStepResponse
_PingRequest = _pb.PingRequest
_PingResponse = _pb.PingResponse


# ---------------------------------------------------------------------------
# Public types — subclass to add from_json / to_json shims.
# ---------------------------------------------------------------------------


class ExecuteStepRequest(_ExecuteStepRequest):
    """ExecuteStepRequest with a dict-based from_json constructor.

    betterproto's from_dict accepts camelCase keys and decodes base64
    bytes fields automatically.
    """

    @classmethod
    def from_json(cls, body: dict) -> ExecuteStepRequest:
        return cls().from_dict(body)


class ExecuteStepResponse(_ExecuteStepResponse):
    """ExecuteStepResponse with a to_json() helper returning a camelCase dict.

    include_default_values=True ensures boolean false and zero floats are
    present in the wire payload so Go can decode them correctly.
    outputPayload is omitted when empty to avoid sending a spurious empty
    base64 string (matches original hand-written behaviour).
    """

    def to_json(self) -> dict:
        d = self.to_dict(include_default_values=True)
        if not self.output_payload:
            d.pop("outputPayload", None)
        return d


class PingRequest(_PingRequest):
    pass


class PingResponse(_PingResponse):
    """PingResponse with a to_json() helper returning a camelCase dict."""

    def to_json(self) -> dict:
        return self.to_dict(include_default_values=True)


__all__ = [
    "ExecuteStepRequest",
    "ExecuteStepResponse",
    "PingRequest",
    "PingResponse",
]
