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
cd /opt/maintenance

# Skapa virtual environment
python3 -m venv venv
source venv/bin/activate

# Installera beroenden
pip install -r agent/requirements.txt

# Konfigurera
nano agent/config.yaml
# Sätt mqtt.host till HA-maskinens IP

# Installera systemd-service
sudo cp systemd/maintenance.service /etc/systemd/system/

# Uppdatera ExecStart i servicefilen för venv
sudo sed -i "s|ExecStart=/usr/bin/python3|ExecStart=/opt/maintenance/venv/bin/python3|" /etc/systemd/system/maintenance.service

# Aktivera och starta
sudo systemctl daemon-reload
sudo systemctl enable maintenance
sudo systemctl start maintenance

# Verifiera
sudo systemctl status maintenance
```

## CLI-användning

```bash
# Aktivera venv först
source /opt/maintenance/venv/bin/activate

# Visa systemstatus
sudo /opt/maintenance/venv/bin/python3 /opt/maintenance/cli/maintenance_cli.py status

# Starta om OpenClaw
sudo /opt/maintenance/venv/bin/python3 /opt/maintenance/cli/maintenance_cli.py restart-openclaw

# Reboot
sudo /opt/maintenance/venv/bin/python3 /opt/maintenance/cli/maintenance_cli.py reboot

# Docker
sudo /opt/maintenance/venv/bin/python3 /opt/maintenance/cli/maintenance_cli.py docker list
sudo /opt/maintenance/venv/bin/python3 /opt/maintenance/cli/maintenance_cli.py docker restart openclaw
sudo /opt/maintenance/venv/bin/python3 /opt/maintenance/cli/maintenance_cli.py docker stop openclaw
```

Lägg till ett alias i `/etc/bash.bashrc`:
```bash
alias maintenance="source /opt/maintenance/venv/bin/activate && /opt/maintenance/venv/bin/python3 /opt/maintenance/cli/maintenance_cli.py"
```

Eller ännu enklare, skapa ett shell-wrapper-skript:
```bash
sudo tee /usr/local/bin/maintenance > /dev/null <<'EOF'
#!/bin/bash
source /opt/maintenance/venv/bin/activate
/opt/maintenance/venv/bin/python3 /opt/maintenance/cli/maintenance_cli.py "$@"
EOF

sudo chmod +x /usr/local/bin/maintenance

# Använd sedan bara:
sudo maintenance status
sudo maintenance restart-openclaw
sudo maintenance docker list
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
