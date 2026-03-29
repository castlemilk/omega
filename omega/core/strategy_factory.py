"""
omega.core.strategy_factory
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Runtime signal hot-loading — writes Python signal functions to disk and
loads them into the running process via importlib without restart.

Design
------
Generated signals live in a ``generated_dir`` (default:
``omega/nodes/victoria/generated/``).  Each file must expose:

    def compute(data: dict) -> float: ...

``SignalHotLoader`` compiles the source, validates the ``compute``
callable is present, writes to disk, then imports the module under a
unique package path (``omega_generated.<name>``).

Namespace isolation: each signal gets its own module object so module-
level constants in signal A never bleed into signal B.

Usage::

    loader = SignalHotLoader()
    mod = loader.write_and_load("whale_pressure_v2", code_string)
    score = mod.compute(market_data)

    # Later — update signal in place without restart
    new_code = generate_improved_signal(...)
    loader.write_and_load("whale_pressure_v2", new_code)
    score = loader.call("whale_pressure_v2", market_data)
"""

from __future__ import annotations

import logging
import sys
import types
from pathlib import Path

logger = logging.getLogger("omega.core.strategy_factory")

_DEFAULT_GENERATED_DIR = str(Path(__file__).parent.parent / "nodes" / "victoria" / "generated")


class SignalHotLoader:
    """
    Writes Python signal code to disk and hot-loads it via importlib.

    Parameters
    ----------
    generated_dir:
        Directory where generated ``.py`` files are written.
        Default: ``omega/nodes/victoria/generated/``.
    """

    def __init__(self, generated_dir: str | None = None) -> None:
        self._dir = Path(generated_dir or _DEFAULT_GENERATED_DIR)
        self._dir.mkdir(parents=True, exist_ok=True)
        # Ensure the directory is a Python package
        init = self._dir / "__init__.py"
        if not init.exists():
            init.write_text('"""Auto-generated signal functions — do not edit manually."""\n')
        # name -> module
        self._modules: dict[str, types.ModuleType] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def write_and_load(self, name: str, code: str) -> types.ModuleType:
        """
        Compile ``code``, write to ``<generated_dir>/<name>.py``, and load.

        Raises
        ------
        SyntaxError  : if ``code`` has a syntax error.
        ValueError   : if ``code`` does not define a ``compute`` callable.

        Returns the loaded module.
        """
        # Compile first to catch syntax errors before touching disk
        compile(code, f"<{name}>", "exec")

        path = self._dir / f"{name}.py"
        path.write_text(code, encoding="utf-8")
        logger.info("SignalHotLoader: wrote %s (%d bytes)", path, len(code))

        mod = self._load_from_file(name, path)

        if not callable(getattr(mod, "compute", None)):
            raise ValueError(
                f"Generated signal '{name}' must define a callable `compute(data: dict) -> float`. "
                f"Found module attributes: {[a for a in dir(mod) if not a.startswith('_')]}"
            )

        self._modules[name] = mod
        logger.info("SignalHotLoader: loaded signal '%s'", name)
        return mod

    def reload(self, name: str) -> types.ModuleType:
        """
        Re-read ``<name>.py`` from disk and reload the module in-place.

        Use this after externally updating the file (e.g. after the LLM
        writes an improved version directly to disk).

        Raises KeyError if ``name`` has never been loaded.
        """
        if name not in self._modules:
            raise KeyError(f"Signal '{name}' not loaded — call write_and_load() first.")
        path = self._dir / f"{name}.py"
        mod = self._load_from_file(name, path)
        self._modules[name] = mod
        logger.info("SignalHotLoader: reloaded signal '%s'", name)
        return mod

    def call(self, name: str, data: dict) -> float:
        """
        Call ``compute(data)`` on a loaded signal.

        Raises KeyError if signal not loaded.
        """
        mod = self._modules.get(name)
        if mod is None:
            raise KeyError(f"Signal '{name}' not loaded.")
        return float(mod.compute(data))

    def list_loaded(self) -> list[str]:
        """Return names of all currently loaded signals."""
        return list(self._modules.keys())

    def get_module(self, name: str) -> types.ModuleType | None:
        return self._modules.get(name)

    # ── Internals ──────────────────────────────────────────────────────────────

    def _load_from_file(self, name: str, path: Path) -> types.ModuleType:
        """
        Load (or reload) a module by reading the source file directly.

        Uses ``compile`` + ``exec`` rather than the importlib spec loader to
        guarantee the latest on-disk content is used on every call — no
        bytecode-cache (.pyc) interference.
        """
        module_name = f"omega_generated.{name}"
        source = path.read_text(encoding="utf-8")
        code = compile(source, str(path), "exec")

        mod = types.ModuleType(module_name)
        mod.__file__ = str(path)
        mod.__package__ = "omega_generated"
        # Register before exec so any self-referential imports work
        sys.modules[module_name] = mod
        exec(code, mod.__dict__)
        return mod
