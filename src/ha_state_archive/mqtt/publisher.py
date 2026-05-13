import json
from datetime import UTC, datetime

import paho.mqtt.publish as publish


DEFAULT_TOPIC = "ha_state_archive/audit/state"


def publish_audit_state(
    broker: str,
    payload: dict,
    topic: str = DEFAULT_TOPIC,
    port: int = 1883,
) -> None:
    """
    Publish audit supervision payload to MQTT.
    """

    enriched_payload = {
        **payload,
        "published_at": datetime.now(UTC).isoformat(),
    }

    publish.single(
        topic=topic,
        payload=json.dumps(enriched_payload),
        hostname=broker,
        port=port,
        retain=True,
    )