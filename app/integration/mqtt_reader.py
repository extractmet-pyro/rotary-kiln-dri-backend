"""Optional MQTT subscriber for a site-approved broker (TLS + client certs).
UNIMPLEMENTED in the cloud demo (requires paho-mqtt and site broker policy).
Subscribe-only; no publish method exists."""
from __future__ import annotations

from app.integration.base import DataAdapter


class MqttReader(DataAdapter):
    name = "mqtt_reader"
    status = "UNIMPLEMENTED (on-prem connector; interface retained)"

    def __init__(self, broker_url: str, topics: list[str], tls: bool = True):
        if not tls:
            raise ValueError("MQTT must use TLS")
        self.broker_url, self.topics = broker_url, topics

    def read_recent(self, tags=None, minutes=60):
        raise NotImplementedError(self.status)

    def read_range(self, start, end, tags=None):
        raise NotImplementedError(self.status)

    def health(self):
        return {"adapter": self.name, "status": self.status, "topics": self.topics, "read_only": True}
