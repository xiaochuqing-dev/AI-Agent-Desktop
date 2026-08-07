from .configuration import build_configuration_router
from .credentials import build_credentials_router
from .integrations import build_integrations_router
from .lifecycle import build_lifecycle_router
from .native_configuration import build_native_configuration_router
from .observability import build_observability_router
from .telegram_binding import build_telegram_router

__all__ = [
    "build_configuration_router",
    "build_credentials_router",
    "build_integrations_router",
    "build_lifecycle_router",
    "build_native_configuration_router",
    "build_observability_router",
    "build_telegram_router",
]
