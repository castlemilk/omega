"""Intelligent credential management for Omega.

Nodes declare what credentials they need. The store resolves from:
1. Environment variables (highest priority)
2. .env file (if present)
3. Returns None with a warning for missing optional creds

Usage in nodes:
    from omega.core.credentials import credentials
    api_key = credentials.get("COINGLASS_API_KEY")
    if api_key:
        # use real API
    else:
        # graceful degradation
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class CredentialSpec:
    name: str
    required: bool = False
    description: str = ""
    source: str = ""  # where it was resolved from


@dataclass
class CredentialStore:
    _cache: dict[str, str] = field(default_factory=dict)
    _specs: dict[str, CredentialSpec] = field(default_factory=dict)
    _env_file_loaded: bool = False

    def register(self, name: str, required: bool = False, description: str = "") -> None:
        """Register a credential that a node needs."""
        self._specs[name] = CredentialSpec(name=name, required=required, description=description)

    def get(self, name: str) -> str | None:
        """Get a credential value. Returns None if not found."""
        if name in self._cache:
            return self._cache[name]

        # Try env var first
        val = os.environ.get(name)
        if val:
            self._cache[name] = val
            if name in self._specs:
                self._specs[name].source = "env"
            return val

        # Try .env file
        if not self._env_file_loaded:
            self._load_env_file()
        val = self._cache.get(name)
        if val:
            if name in self._specs:
                self._specs[name].source = ".env"
            return val

        # Not found
        spec = self._specs.get(name)
        if spec and spec.required:
            log.error("Required credential %s not found: %s", name, spec.description)
        elif spec:
            log.debug(
                "Optional credential %s not found: %s (degraded mode)", name, spec.description
            )
        return None

    def _load_env_file(self) -> None:
        """Load credentials from .env file.

        Search order:
        1. OMEGA_ENV_FILE env var (explicit override)
        2. .env in CWD
        3. Walk up parent directories (up to 5 levels) to find .env
           — supports running from git worktrees where .env lives at the repo root
        """
        self._env_file_loaded = True
        candidates: list[Path] = []
        env_file = os.environ.get("OMEGA_ENV_FILE", "")
        if env_file:
            candidates.append(Path(env_file))

        # CWD first, then walk up to repo root
        cwd = Path(".").resolve()
        candidates.append(cwd / ".env")
        parent = cwd.parent
        for _ in range(5):
            candidates.append(parent / ".env")
            if parent == parent.parent:
                break
            parent = parent.parent

        for env_path in candidates:
            if env_path.exists():
                with open(env_path) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, _, value = line.partition("=")
                            key = key.strip()
                            value = value.strip().strip('"').strip("'")
                            if key and key not in self._cache:
                                self._cache[key] = value
                log.info("Loaded credentials from %s", env_path)
                break

    def status(self) -> list[dict]:
        """Return status of all registered credentials."""
        result = []
        for name, spec in sorted(self._specs.items()):
            val = self.get(name)
            result.append(
                {
                    "name": name,
                    "configured": val is not None,
                    "required": spec.required,
                    "source": spec.source or "not found",
                    "description": spec.description,
                }
            )
        return result

    def summary(self) -> str:
        """Human-readable credential status."""
        lines = []
        for item in self.status():
            icon = "✅" if item["configured"] else ("❌" if item["required"] else "⚠️")
            source = f" ({item['source']})" if item["configured"] else ""
            lines.append(f"  {icon} {item['name']}{source} — {item['description']}")
        return "\n".join(lines) if lines else "  No credentials registered"


# Singleton instance
credentials = CredentialStore()
