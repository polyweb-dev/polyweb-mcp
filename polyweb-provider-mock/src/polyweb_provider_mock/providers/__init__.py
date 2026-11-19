"""Provider plugins, discovered from the modules in this package.

Every module except ``base`` and names that start with ``_`` must export
``PLUGIN``, a :class:`~polyweb_provider_mock.providers.base.ProviderPlugin`.
"""

import importlib
import pkgutil
from functools import cache

from polyweb_provider_mock.providers.base import ProviderPlugin

__all__ = ["discover", "plugin"]


@cache
def discover() -> dict[str, ProviderPlugin]:
    """Return the plugins by name; reject duplicate names or hosts."""

    plugins: dict[str, ProviderPlugin] = {}
    hosts: dict[str, str] = {}
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda item: item.name):
        if info.name == "base" or info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        found = getattr(module, "PLUGIN", None)
        if not isinstance(found, ProviderPlugin):
            raise TypeError(f"{module.__name__} must export PLUGIN, a ProviderPlugin")
        if found.name in plugins:
            raise ValueError(f"duplicate provider plugin name {found.name!r}")
        for host in found.hosts:
            if host in hosts:
                raise ValueError(f"host {host} is claimed by {hosts[host]} and {found.name}")
            hosts[host] = found.name
        plugins[found.name] = found
    return plugins


def plugin(name: str) -> ProviderPlugin:
    """Return one plugin by name, with a clear error for an unknown name."""

    plugins = discover()
    if name not in plugins:
        raise KeyError(f"unknown provider {name!r}; known: {', '.join(sorted(plugins))}")
    return plugins[name]
