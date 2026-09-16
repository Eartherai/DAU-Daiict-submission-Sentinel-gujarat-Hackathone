"""Model 3 — VMS federation / adapter layer.

These adapters do **not** replace departmental VMS systems. They normalise
discovery, health, stream URLs and events at the boundary so Model 1 (registry)
and Model 2 (viewing) can stay vendor-neutral.

Mock adapters are labelled DEMO/TEST. They are not government VMS integrations.
"""
from saakshya.federation.adapters import (
    GenericVMSAdapter,
    ONVIFAdapter,
    RTSPAdapter,
    VMSAdapter,
    VMSHealth,
    demo_connected_systems,
)
from saakshya.federation.bus import EventBus, FederatedEvent

__all__ = [
    "EventBus",
    "FederatedEvent",
    "GenericVMSAdapter",
    "ONVIFAdapter",
    "RTSPAdapter",
    "VMSAdapter",
    "VMSHealth",
    "demo_connected_systems",
]
