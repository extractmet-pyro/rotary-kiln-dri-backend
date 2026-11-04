"""Optional plant-approved OPC UA READ-ONLY reader (on-premises connector only).

UNIMPLEMENTED in the cloud demo: requires the `asyncua` package, a site
certificate trust list and an approved security policy (Basic256Sha256 /
SignAndEncrypt).  Encryption/authentication must never be disabled.  This
class intentionally exposes no write/call methods.  It must run inside the
plant DMZ connector, never on Render or in a browser.
"""
from __future__ import annotations

from app.integration.base import DataAdapter


class OpcUaReader(DataAdapter):
    name = "opcua_reader"
    status = "UNIMPLEMENTED (on-prem connector; interface retained)"

    def __init__(self, endpoint: str, node_map: dict, security_policy: str = "Basic256Sha256",
                 message_mode: str = "SignAndEncrypt", cert_path: str | None = None, key_path: str | None = None):
        if message_mode != "SignAndEncrypt":
            raise ValueError("OPC UA message mode must be SignAndEncrypt for production use")
        self.endpoint, self.node_map = endpoint, node_map
        self.security_policy, self.message_mode = security_policy, message_mode
        self.cert_path, self.key_path = cert_path, key_path

    def _client(self):
        try:
            import asyncua  # noqa: F401
        except ImportError as e:  # pragma: no cover
            raise NotImplementedError(self.status) from e
        raise NotImplementedError(self.status)

    def read_recent(self, tags=None, minutes=60):
        self._client()

    def read_range(self, start, end, tags=None):
        raise NotImplementedError("OPC UA HA (historical access) via site historian adapter instead")

    def health(self):
        return {"adapter": self.name, "status": self.status, "endpoint_configured": bool(self.endpoint),
                "security_policy": self.security_policy, "message_mode": self.message_mode, "read_only": True}
