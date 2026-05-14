from __future__ import annotations

import sys
import types


try:
    import paho.mqtt.client  # noqa: F401
except ModuleNotFoundError:
    paho = types.ModuleType("paho")
    mqtt_pkg = types.ModuleType("paho.mqtt")
    client_mod = types.ModuleType("paho.mqtt.client")

    class _CallbackAPIVersion:
        VERSION1 = object()

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

    client_mod.CallbackAPIVersion = _CallbackAPIVersion
    client_mod.Client = _Client

    sys.modules.setdefault("paho", paho)
    sys.modules.setdefault("paho.mqtt", mqtt_pkg)
    sys.modules.setdefault("paho.mqtt.client", client_mod)
