#!/usr/bin/env python3
"""
Maintenance Agent — MQTT daemon för Ubuntu-underhåll.
Kör som root på Ubuntu-maskinen. Styrs från Home Assistant via MQTT.
"""

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path

import docker
import paho.mqtt.client as mqtt
import psutil
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def count_pending_updates():
    try:
        result = subprocess.run(
            ["apt", "list", "--upgradable"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        lines = [l for l in result.stdout.splitlines() if l and l != "Listing..."]
        return len(lines)
    except Exception as e:
        log.warning(f"Kunde inte räkna uppdateringar: {e}")
        return -1


def get_docker_statuses(containers: list[str]) -> dict:
    statuses = {}
    try:
        client = docker.from_env()
        for name in containers:
            try:
                c = client.containers.get(name)
                statuses[name] = c.status
            except docker.errors.NotFound:
                statuses[name] = "not_found"
    except Exception as e:
        log.warning(f"Docker-fel: {e}")
        for name in containers:
            statuses[name] = "error"
    return statuses


def get_openclaw_status() -> str:
    import pwd
    try:
        uid = pwd.getpwnam("sejsv").pw_uid
        result = subprocess.run(
            [
                "sudo", "-u", "sejsv",
                "env",
                f"XDG_RUNTIME_DIR=/run/user/{uid}",
                f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
                "systemctl", "--user", "is-active", "openclaw-gateway",
            ],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() or "inactive"
    except Exception as e:
        log.warning(f"Kunde inte hämta openclaw-status: {e}")
        return "unknown"


def collect_metrics(cfg: dict) -> dict:
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage(cfg.get("disk_path", "/"))
    containers = cfg.get("docker_containers") or []
    return {
        "ram_percent": ram.percent,
        "ram_used_mb": round(ram.used / 1024 / 1024),
        "ram_total_mb": round(ram.total / 1024 / 1024),
        "disk_percent": disk.percent,
        "disk_used_gb": round(disk.used / 1024 / 1024 / 1024, 1),
        "disk_total_gb": round(disk.total / 1024 / 1024 / 1024, 1),
        "pending_updates": count_pending_updates(),
        "openclaw": get_openclaw_status(),
        "docker": get_docker_statuses(containers),
        "timestamp": int(time.time()),
    }


def run_command(cmd: list[str], timeout: int = 10) -> tuple[bool, str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        success = result.returncode == 0
        output = result.stdout.strip() or result.stderr.strip()
        return success, output
    except subprocess.TimeoutExpired:
        return False, "Kommando tog för lång tid"
    except Exception as e:
        return False, str(e)


class MaintenanceAgent:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.client = mqtt.Client(client_id=cfg["mqtt"].get("client_id", "maintenance-agent"))
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

        if cfg["mqtt"].get("username"):
            self.client.username_pw_set(cfg["mqtt"]["username"], cfg["mqtt"]["password"])

        self.client.will_set(
            "maintenance/heartbeat",
            json.dumps({"state": "offline", "timestamp": int(time.time())}),
            retain=True,
            qos=1,
        )

        self._stop = threading.Event()

    def _publish_log(self, msg: str):
        log.info(msg)
        self.client.publish("maintenance/log", msg, retain=False)

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            log.info("Ansluten till MQTT-broker")
            client.subscribe("maintenance/command/#")
            client.publish(
                "maintenance/heartbeat",
                json.dumps({"state": "online", "timestamp": int(time.time())}),
                retain=True,
                qos=1,
            )
        else:
            log.error(f"MQTT-anslutning misslyckades, kod: {rc}")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        log.info(f"Kommando mottaget: {topic}")

        if topic == "maintenance/command/reboot":
            self._publish_log("Startar om Ubuntu om 5 sekunder...")
            threading.Thread(target=self._delayed_reboot, daemon=True).start()

        elif topic == "maintenance/command/restart_openclaw":
            import pwd
            uid = pwd.getpwnam("sejsv").pw_uid
            ok, out = run_command([
                "sudo", "-u", "sejsv",
                "env",
                f"XDG_RUNTIME_DIR=/run/user/{uid}",
                f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
                "systemctl", "--user", "restart", "openclaw-gateway",
            ])
            status = "OK" if ok else "FEL"
            self._publish_log(f"restart openclaw-gateway: {status} — {out}")

        elif topic.startswith("maintenance/command/docker/"):
            parts = topic.split("/")
            if len(parts) == 5:
                _, _, _, container, action = parts
                self._handle_docker(container, action)

    def _delayed_reboot(self):
        time.sleep(5)
        self._publish_log("Utför reboot nu.")
        time.sleep(1)
        subprocess.run(["reboot"])

    def _handle_docker(self, container: str, action: str):
        if action == "restart":
            ok, out = run_command(["docker", "restart", container], timeout=30)
        elif action == "stop":
            ok, out = run_command(["docker", "stop", container], timeout=30)
        else:
            self._publish_log(f"Okänd docker-åtgärd: {action}")
            return
        status = "OK" if ok else "FEL"
        self._publish_log(f"docker {action} {container}: {status} — {out}")

    def _metrics_loop(self):
        interval = self.cfg.get("poll_interval", 30)
        while not self._stop.is_set():
            try:
                metrics = collect_metrics(self.cfg)
                self.client.publish("maintenance/status", json.dumps(metrics), retain=False)
                self.client.publish(
                    "maintenance/heartbeat",
                    json.dumps({"state": "online", "timestamp": int(time.time())}),
                    retain=True,
                    qos=1,
                )
            except Exception as e:
                log.error(f"Metrics-fel: {e}")
            self._stop.wait(interval)

    def run(self):
        mqtt_cfg = self.cfg["mqtt"]
        self.client.connect(mqtt_cfg["host"], mqtt_cfg.get("port", 1883), keepalive=60)

        metrics_thread = threading.Thread(target=self._metrics_loop, daemon=True)
        metrics_thread.start()

        try:
            self.client.loop_forever()
        except KeyboardInterrupt:
            log.info("Avslutar agent.")
        finally:
            self._stop.set()


if __name__ == "__main__":
    cfg = load_config()
    agent = MaintenanceAgent(cfg)
    agent.run()
