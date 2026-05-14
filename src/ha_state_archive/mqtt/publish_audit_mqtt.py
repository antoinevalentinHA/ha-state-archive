#!/usr/bin/env python3
"""
publish_audit_mqtt.py

Publish a compact audit verdict to MQTT.

This module is intentionally generic:
- no Home Assistant instance-specific path;
- no private topic;
- no embedded credentials;
- no audit logic;
- no report content publishing.
"""

import argparse
import json
import os
import re
import sys
import time
import threading
from datetime import UTC, datetime

import paho.mqtt.client as mqtt


DEFAULT_TOPIC = "ha_state_archive/audit/state"
CONTRACT_VERSION = "1.0.0"
STRICT_FRESHNESS_SECONDS = 5 * 60
MQTT_KEEPALIVE_SECONDS = 30
VALID_AUDIT_RETURN_CODES = (0, 30)


def log_error(message: str) -> None:
    print(f"[publish_audit_mqtt] {message}", file=sys.stderr)


def now_iso_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


_ENV_LINE_RE = re.compile(
    r'^\s*([A-Z_][A-Z0-9_]*)\s*=\s*"([^"\n]*)"\s*$'
)

_REQUIRED_MQTT_KEYS = (
    "MQTT_HOST",
    "MQTT_PORT",
    "MQTT_USERNAME",
    "MQTT_PASSWORD",
)


def load_mqtt_config(path: str | None) -> dict:
    """
    Load MQTT configuration from environment variables or from a strict env file.

    Expected env file format:

        MQTT_HOST="127.0.0.1"
        MQTT_PORT="1883"
        MQTT_USERNAME="user"
        MQTT_PASSWORD="password"
    """

    values = {}

    if path is not None:
        if not os.path.exists(path):
            raise FileNotFoundError(f"MQTT config file not found: {path}")

        try:
            with open(path, "r", encoding="utf-8") as file:
                for line in file:
                    line = line.rstrip("\n")

                    if not line or line.lstrip().startswith("#"):
                        continue

                    match = _ENV_LINE_RE.match(line)

                    if match is None:
                        continue

                    values[match.group(1)] = match.group(2)
        except OSError as error:
            raise ValueError(f"failed to read MQTT config file: {error}") from error

    for key in _REQUIRED_MQTT_KEYS:
        if key not in values and key in os.environ:
            values[key] = os.environ[key]

    missing = [
        key
        for key in _REQUIRED_MQTT_KEYS
        if key not in values or values[key] == ""
    ]

    if missing:
        raise ValueError(f"missing MQTT configuration keys: {', '.join(missing)}")

    try:
        port = int(values["MQTT_PORT"])
    except ValueError as error:
        raise ValueError(f"MQTT_PORT is not numeric: {values['MQTT_PORT']!r}") from error

    return {
        "host": values["MQTT_HOST"],
        "port": port,
        "username": values["MQTT_USERNAME"],
        "password": values["MQTT_PASSWORD"],
    }


_REQUIRED_VERDICT_KEYS = (
    "contract_version",
    "engine_version",
    "published_at",
    "audited_version",
    "verdict",
    "total_anomalies",
    "anomaly_categories",
    "report_path",
)


def read_verdict_json(path: str):
    """
    Read and validate the compact audit verdict JSON.

    Returns:
        tuple: (data, mtime, present, valid)
    """

    if not os.path.exists(path):
        return None, None, False, False

    try:
        mtime = int(os.path.getmtime(path))
    except OSError as error:
        log_error(f"failed to stat verdict JSON: {error}")
        return None, None, True, False

    try:
        with open(path, "r", encoding="utf-8") as file:
            content = file.read()
    except OSError as error:
        log_error(f"failed to read verdict JSON: {error}")
        return None, mtime, True, False

    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError) as error:
        log_error(f"invalid verdict JSON: {error}")
        return None, mtime, True, False

    if not isinstance(data, dict):
        log_error("verdict JSON root is not an object")
        return None, mtime, True, False

    missing = [key for key in _REQUIRED_VERDICT_KEYS if key not in data]

    if missing:
        log_error(f"missing verdict JSON keys: {', '.join(missing)}")
        return None, mtime, True, False

    if data.get("verdict") not in ("ok", "degraded", "critical", "error", "unknown"):
        log_error(f"invalid verdict value: {data.get('verdict')!r}")
        return None, mtime, True, False

    return data, mtime, True, True


def build_nominal_payload(verdict_data: dict) -> str:
    return json.dumps(verdict_data, ensure_ascii=False)


def build_error_payload(
    reason: str,
    detail: str = "",
    engine_version=None,
    audited_version=None,
) -> str:
    payload = {
        "contract_version": CONTRACT_VERSION,
        "engine_version": engine_version,
        "published_at": now_iso_utc(),
        "audited_version": audited_version,
        "verdict": "error",
        "total_anomalies": None,
        "error_reason": reason,
        "error_detail": detail,
    }

    return json.dumps(payload, ensure_ascii=False)


def mqtt_connect(config: dict):
    connected = threading.Event()
    connect_result = {"rc": None}

    def on_connect(client, userdata, flags, rc):
        connect_result["rc"] = rc

        if rc == 0:
            connected.set()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    client.on_connect = on_connect
    client.username_pw_set(config["username"], config["password"])
    client.connect(
        config["host"],
        config["port"],
        keepalive=MQTT_KEEPALIVE_SECONDS,
    )
    client.loop_start()

    if not connected.wait(timeout=10):
        client.loop_stop()

        try:
            client.disconnect()
        except Exception:
            pass

        raise RuntimeError("MQTT connect timeout: CONNACK not received")

    if connect_result["rc"] != 0:
        client.loop_stop()

        try:
            client.disconnect()
        except Exception:
            pass

        raise RuntimeError(f"MQTT connection refused: rc={connect_result['rc']}")

    return client


def mqtt_publish_sync(client, topic: str, payload: str, qos: int) -> bool:
    info = client.publish(topic, payload, qos=qos, retain=True)

    try:
        info.wait_for_publish()
    except RuntimeError as error:
        log_error(f"publish wait failed: {error}")
        return False

    return info.is_published()


def decide_payload(
    verdict_json_path: str,
    audit_return_code: int,
    strict_freshness: bool,
):
    if audit_return_code not in VALID_AUDIT_RETURN_CODES:
        return (
            build_error_payload(
                reason="audit_engine_unexpected_exit_code",
                detail=f"exit_code={audit_return_code}",
            ),
            f"error/audit_engine_unexpected_exit_code(rc={audit_return_code})",
        )

    data, mtime, present, valid = read_verdict_json(verdict_json_path)

    if not present:
        return (
            build_error_payload(reason="verdict_json_missing"),
            "error/verdict_json_missing",
        )

    if not valid:
        return (
            build_error_payload(
                reason="verdict_json_malformed",
                detail=f"path={verdict_json_path}",
            ),
            "error/verdict_json_malformed",
        )

    if strict_freshness:
        age_seconds = int(time.time()) - mtime

        if age_seconds > STRICT_FRESHNESS_SECONDS:
            return (
                build_error_payload(
                    reason="verdict_json_stale",
                    detail=(
                        f"age_s={age_seconds}, "
                        f"threshold_s={STRICT_FRESHNESS_SECONDS}"
                    ),
                    engine_version=data.get("engine_version"),
                    audited_version=data.get("audited_version"),
                ),
                f"error/verdict_json_stale(age={age_seconds}s)",
            )

    return (
        build_nominal_payload(data),
        f"nominal/{data['verdict']}",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="publish_audit_mqtt",
        description="Publish a compact audit verdict to MQTT.",
    )
    parser.add_argument(
        "--verdict-json",
        required=True,
        help="Path to the compact audit verdict JSON file.",
    )
    parser.add_argument(
        "--audit-rc",
        type=int,
        required=True,
        help="Audit command return code. Expected values: 0 or 30.",
    )
    parser.add_argument(
        "--mqtt-env",
        default=None,
        help="Optional path to a strict MQTT env file.",
    )
    parser.add_argument(
        "--topic",
        default=DEFAULT_TOPIC,
        help=f"MQTT topic. Default: {DEFAULT_TOPIC}",
    )
    parser.add_argument(
        "--qos",
        type=int,
        default=1,
        choices=(0, 1, 2),
        help="MQTT QoS level. Default: 1.",
    )
    parser.add_argument(
        "--strict-freshness",
        action="store_true",
        help=(
            "Reject verdict JSON files older than "
            f"{STRICT_FRESHNESS_SECONDS} seconds."
        ),
    )

    args = parser.parse_args()

    try:
        mqtt_config = load_mqtt_config(args.mqtt_env)
    except (FileNotFoundError, ValueError) as error:
        log_error(f"configuration error: {error}")
        return 2

    payload, decision = decide_payload(
        verdict_json_path=args.verdict_json,
        audit_return_code=args.audit_rc,
        strict_freshness=args.strict_freshness,
    )
    log_error(f"decision: {decision}")

    try:
        client = mqtt_connect(mqtt_config)
    except Exception as error:
        log_error(f"MQTT connect failed: {type(error).__name__}: {error}")
        return 1

    exit_code = 0

    try:
        published = mqtt_publish_sync(
            client=client,
            topic=args.topic,
            payload=payload,
            qos=args.qos,
        )

        if not published:
            log_error(f"publish not acknowledged on topic {args.topic}")
            exit_code = 1
        else:
            log_error(f"published on {args.topic} ({len(payload)} bytes)")
    finally:
        client.loop_stop()

        try:
            client.disconnect()
        except Exception:
            pass

    return exit_code


if __name__ == "__main__":
    sys.exit(main())