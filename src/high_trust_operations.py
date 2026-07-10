"""Explicit opt-in policy for operations that control a host or remote server.

The normal agent command path is intentionally isolated in the tool-sandbox
sidecar.  Cookbook operations that launch processes, mutate packages, or
connect to SSH targets cannot safely use that sidecar, so they are unavailable
until a trusted operator opts in at deployment time.
"""

import os
from collections.abc import Mapping


HIGH_TRUST_COOKBOOK_ENV_VAR = "ODYSSEUS_ENABLE_HIGH_TRUST_COOKBOOK"
HIGH_TRUST_COOKBOOK_HINT = (
    "Cookbook host and SSH operations are disabled by default. Set "
    "ODYSSEUS_ENABLE_HIGH_TRUST_COOKBOOK=true only for a trusted administrator "
    "who intends to allow local process and configured remote-SSH control."
)


def high_trust_cookbook_enabled(
    *, environ: Mapping[str, str] | None = None
) -> bool:
    """Whether the deployment explicitly permits high-trust Cookbook actions."""
    values = os.environ if environ is None else environ
    return values.get(HIGH_TRUST_COOKBOOK_ENV_VAR, "").strip().lower() == "true"
