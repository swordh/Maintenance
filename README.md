# Maintenance

Ubuntu underhållsagent med MQTT-integration för Home Assistant.

## Vad det gör

- Övervakar RAM, disk och väntande apt-uppdateringar
- Hanterar Docker-containers (status, restart, stop)
- Styr OpenClaw gateway (systemd-service)
- Kan rebootа Ubuntu
- Styrs från CLI (lokalt) och Home Assistant (via MQTT)

## Arkitektur

```
Ubuntu-maskin                          Home Assistant
┌─────────────────────────────┐        ┌───────────────────────┐
│  maintenance-agent (daemon) │◄──────►│  Mosquitto MQTT broker │
│  maintenance-cli (CLI)      │  MQTT  │  Sensorer + knappar    │
└─────────────────────────────┘        └───────────────────────┘
```

## Installation på Ubuntu

```bash
# Klona repot
git clone https://github.com/swordh/Maintenance.git /opt/maintenance

# Installera beroenden
pip3 install -r /opt/maintenance/agent/requirements.txt

# Konfigurera
nano /opt/maintenance/agent/config.yaml
# Sätt mqtt.host till HA-maskinens IP

# Installera systemd-service
sudo cp /opt/maintenance/systemd/maintenance.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable maintenance
sudo systemctl start maintenance

# Verifiera
sudo systemctl status maintenance
```

## CLI-användning

```bash
# Visa systemstatus
sudo python3 /opt/maintenance/cli/maintenance_cli.py status

# Starta om OpenClaw
sudo python3 /opt/maintenance/cli/maintenance_cli.py restart-openclaw

# Reboot
sudo python3 /opt/maintenance/cli/maintenance_cli.py reboot

# Docker
sudo python3 /opt/maintenance/cli/maintenance_cli.py docker list
sudo python3 /opt/maintenance/cli/maintenance_cli.py docker restart openclaw
sudo python3 /opt/maintenance/cli/maintenance_cli.py docker stop openclaw
```

Lägg gärna till ett alias i `/etc/bash.bashrc`:
```bash
alias maintenance="sudo python3 /opt/maintenance/cli/maintenance_cli.py"
```

## Home Assistant-integration

1. Kopiera `homeassistant/mqtt.yaml` till din HA-konfigmapp
2. Lägg till i `configuration.yaml`:
   ```yaml
   mqtt: !include mqtt.yaml
   ```
3. Starta om Home Assistant
4. Gå till **Developer Tools → States** och sök på `ubuntu`
5. Lägg till dashboard-kortet från `homeassistant/dashboard.yaml`

## MQTT Topics

| Topic | Riktning | Innehåll |
|-------|----------|---------|
| `maintenance/status` | Agent → HA | JSON med RAM, disk, updates, docker-status |
| `maintenance/log` | Agent → HA | Loggmeddelanden |
| `maintenance/command/reboot` | HA → Agent | Triggar reboot |
| `maintenance/command/restart_openclaw` | HA → Agent | Startar om openclaw.service |
| `maintenance/command/docker/{name}/restart` | HA → Agent | Docker restart |
| `maintenance/command/docker/{name}/stop` | HA → Agent | Docker stop |
