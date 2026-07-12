"""Test configuration for the Resolume integration.

The protocol layer (api.py, client.py) has no Home Assistant dependencies
and can be tested without Home Assistant installed; in that case the
package path is registered manually so imports skip the integration's
__init__.py (which imports Home Assistant).
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

if importlib.util.find_spec("homeassistant") is None:
    _pkg = types.ModuleType("custom_components")
    _pkg.__path__ = [str(ROOT / "custom_components")]
    sys.modules.setdefault("custom_components", _pkg)

    _resolume = types.ModuleType("custom_components.resolume")
    _resolume.__path__ = [str(ROOT / "custom_components" / "resolume")]
    sys.modules.setdefault("custom_components.resolume", _resolume)
