#!/usr/bin/env python3
"""
Maintenance CLI — lokal styrning av Ubuntu-maskinen.
Kör direkt utan MQTT. Kräver root (eller sudo) för systemctl/reboot.

Användning:
  sudo maintenance status
  sudo maintenance reboot
  sudo maintenance restart openclaw
  sudo maintenance docker list
  sudo maintenance docker restart <container>
  sudo maintenance docker stop <container>
"""

import argparse
import subprocess
import sys
from pathlib import Path

import docker
import psutil
import yaml

CONFIG_PATH = Path(__file__).parent.parent / "agent" / "config.yaml"


def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f)
    return {"docker_containers": [], "disk_path": "/"}


def run(cmd: list[str], timeout: int = 30) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout.strip() or r.stderr.strip())
    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except Exception as e:
        return False, str(e)


def cmd_status(cfg: dict):
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage(cfg.get("disk_path", "/"))

    print("=== System Status ===")
    print(f"RAM:  {ram.percent:.1f}%  ({ram.used // 1024 // 1024} MB / {ram.total // 1024 // 1024} MB)")
    print(f"Disk: {disk.percent:.1f}%  ({disk.used // 1024 // 1024 // 1024:.1f} GB / {disk.total // 1024 // 1024 // 1024:.1f} GB)")

    try:
        result = subprocess.run(
            ["apt", "list", "--upgradable"],
            capture_output=True, text=True, timeout=30,
        )
        updates = [l for l in result.stdout.splitlines() if l and l != "Listing..."]
        print(f"Uppdateringar: {len(updates)} tillgängliga")
    except Exception:
        print("Uppdateringar: kunde inte kontrollera")

    print("\n=== Docker ===")
    try:
        client = docker.from_env()
        containers = cfg.get("docker_containers", [])
        if not containers:
            print("Inga containers konfigurerade i config.yaml")
        for name in containers:
            try:
                c = client.containers.get(name)
                print(f"  {name}: {c.status}")
            except docker.errors.NotFound:
                print(f"  {name}: hittades inte")
    except Exception as e:
        print(f"  Docker-fel: {e}")

    print("\n=== OpenClaw Gateway ===")
    ok, out = run(["sudo", "-u", "sejsv", "systemctl", "--user", "is-active", "openclaw-gateway"])
    status = "aktiv" if ok else "inaktiv"
    print(f"  openclaw-gateway.service: {status}")


def cmd_reboot():
    answer = input("Bekräfta reboot av Ubuntu (ja/nej): ").strip().lower()
    if answer != "ja":
        print("Avbröt.")
        return
    print("Startar om...")
    subprocess.run(["reboot"])


def cmd_restart_openclaw():
    ok, out = run(["sudo", "-u", "sejsv", "systemctl", "--user", "restart", "openclaw-gateway"])
    if ok:
        print("openclaw-gateway startades om.")
    else:
        print(f"Fel: {out}")


def cmd_docker(args):
    client = docker.from_env()

    if args.docker_cmd == "list":
        containers = client.containers.list(all=True)
        if not containers:
            print("Inga containers.")
        for c in containers:
            print(f"  {c.name}: {c.status}")

    elif args.docker_cmd in ("restart", "stop"):
        name = args.container
        try:
            c = client.containers.get(name)
            if args.docker_cmd == "restart":
                c.restart()
                print(f"{name} startades om.")
            else:
                c.stop()
                print(f"{name} stoppades.")
        except docker.errors.NotFound:
            print(f"Container '{name}' hittades inte.")
        except Exception as e:
            print(f"Fel: {e}")


def main():
    parser = argparse.ArgumentParser(description="Maintenance CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Visa RAM, disk, updates och Docker-status")
    sub.add_parser("reboot", help="Starta om Ubuntu")
    sub.add_parser("restart-openclaw", help="Starta om openclaw.service")

    docker_p = sub.add_parser("docker", help="Docker-hantering")
    docker_sub = docker_p.add_subparsers(dest="docker_cmd", required=True)
    docker_sub.add_parser("list", help="Visa alla containers")
    restart_p = docker_sub.add_parser("restart", help="Starta om en container")
    restart_p.add_argument("container")
    stop_p = docker_sub.add_parser("stop", help="Stoppa en container")
    stop_p.add_argument("container")

    args = parser.parse_args()
    cfg = load_config()

    if args.command == "status":
        cmd_status(cfg)
    elif args.command == "reboot":
        cmd_reboot()
    elif args.command == "restart-openclaw":
        cmd_restart_openclaw()
    elif args.command == "docker":
        cmd_docker(args)


if __name__ == "__main__":
    main()
