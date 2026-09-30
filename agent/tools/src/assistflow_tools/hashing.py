"""Stable hashes for tool arguments.

The hash is `sha256(tool_name + canonical JSON)`. Key order does not change the digest.
"""

from assistflow_contracts.gateway import arguments_hash

__all__ = ["arguments_hash"]
