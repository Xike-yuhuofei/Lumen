"""Minimal plugin kernel exports."""

from lumen.kernel.bootstrap import Bootstrap
from lumen.kernel.context import PluginContext
from lumen.kernel.effects import BackgroundTask, DisposalStack
from lumen.kernel.events import EventBus
from lumen.kernel.plugin import Plugin, PluginManifest
from lumen.kernel.profile import Profile
from lumen.kernel.registry import ServiceRegistry
from lumen.kernel.resolver import DependencyResolver

__all__ = [
    "BackgroundTask",
    "Bootstrap",
    "DependencyResolver",
    "DisposalStack",
    "EventBus",
    "Plugin",
    "PluginContext",
    "PluginManifest",
    "Profile",
    "ServiceRegistry",
]
