# MeasurePi

`MeasurePi` ist ein lokaler Monitoring- und Diagnose-Stack fuer einen Raspberry Pi in einem realen Netz.

Der Stack ist heute nicht mehr nur ein WLAN-Client-Messer, sondern eine Kombination aus:

- Pi-Host-Health
- Internet-/HTTP-Reachability
- WLAN-Client-Sicht des Pi, sofern genutzt
- SNMP-Monitoring fuer Gateway und Switches
- UniFi-AP-Monitoring per SNMP

Die zentrale Idee bleibt: nicht nur sehen, dass "irgendwas rot ist", sondern moeglichst sauber trennen, ob das Problem am Pi, an der lokalen Infrastruktur, an den APs oder am externen Uplink liegt.

## Aktueller Scope

Der Stack deckt heute vor allem diese Bereiche ab:

- Pi-Zustand:
  - CPU
  - Load
  - Temperatur
  - Filesystem
  - Kernel-/Storage-Hinweise
- externe Erreichbarkeit:
  - ICMP zu einem Internet-Ziel
  - HTTP-Check zu einem Referenzziel
- Netzwerk-Infrastruktur via SNMP:
  - UXG Pro
  - Switches
  - Interface-Status, Durchsatz, Errors, Discards
- UniFi-Access-Points:
  - Online-Status
  - Zonen EG / OG3
  - Clients
  - CPU / Memory / Load
  - Uplink-Traffic
  - Radio-/SSID-nahe Metriken
- optionale WLAN-Client-Sicht des Pi:
  - SSID / BSSID
  - RSSI
  - Roams
  - Disconnects
  - Gateway-/Internet-Ereignisse aus Sicht des Pi

## Architektur in einem Satz

Der Pi sammelt lokal Host-, WLAN- und Event-Signale, `Prometheus` speichert Zeitreihen, `Grafana` visualisiert, `Blackbox Exporter` prueft externe Ziele, `snmp-exporter` sammelt Standard-SNMP fuer Netzgeraete und `unifi-ap-exporter` uebersetzt UniFi-AP-OIDs in Prometheus-Metriken.

## Aktive Services

Der Haupt-Stack in [docker-compose.yaml](/Users/benedikt/Projekte/measurepi/docker-compose.yaml) besteht aktuell aus:

- `prometheus`
- `grafana`
- `blackbox-exporter`
- `snmp-exporter`
- `unifi-ap-exporter`
- `wifi-exporter`
- `tshark-exporter`
- `kernel-log-exporter`
- `node-exporter`
- optional `smartctl-exporter`

## Dashboards

Aktuell werden diese Grafana-Dashboards ausgeliefert:

- `MeasurePi 01 Overview`
  - transport-agnostische Startseite
  - Pi-, Internet-, Infrastruktur- und AP-Gesundheit
  - Outage-Sicht fuer Internet und Gateway-Geraet
- `MeasurePi Logs`
  - bestehende Event-/Incident-Sicht aus der WLAN-Client-Logik
  - eher Ereignis-/Troubleshooting-Board als Startseite
- `MeasurePi Network Device Focus`
  - fokussierte Betriebsansicht fuer UXG Pro und Switches
  - physische Ports, Uplinks, Fehleraktivitaet
- `MeasurePi Network Interface Explorer`
  - generische SNMP-Interface-Sicht
  - fuer Ad-hoc-Analyse und freies Filtern
- `MeasurePi WLAN AP Overview`
  - schnelle Lage fuer alle UniFi-APs
  - Online-Status, Zonen, Clients, CPU, Uplink-Traffic
- `MeasurePi WLAN AP Zone Detail`
  - Detailansicht fuer Zone / AP / Band / Radio

Entfernt wurden:

- `MeasurePi Correlation`
- `MeasurePi Gateway`

Beide wurden als Legacy entfernt, weil sie auf alten oder heute nicht mehr aktiven Datenpfaden aufbauten.

## Schnellstart

1. Projekt nach `/opt/measurepi` kopieren
2. Datenordner vorbereiten
3. Stack bauen und starten

```bash
cd /opt/measurepi
sh ./scripts/prepare-data-dirs.sh
docker compose up -d --build
```

Danach:

- Grafana: `http://<pi-ip>:3000`
- Prometheus: `http://<pi-ip>:9090`

## Konfiguration

Im Produktivbetrieb kann der Stack komplett ohne `.env` laufen.

Es gibt bewusst nur eine [.env.example](/Users/benedikt/Projekte/measurepi/.env.example) als kleine Override-Referenz. Wenn du nichts anpasst, greifen die Defaults aus `docker-compose.yaml`.

Aktuell relevante Variablen sind:

- `GF_SECURITY_ADMIN_USER`
  - Benutzername fuer den Grafana-Login
- `GF_SECURITY_ADMIN_PASSWORD`
  - Passwort fuer den Grafana-Login
- `SNMP_COMMUNITY`
  - Community fuer `snmp-exporter` und `unifi-ap-exporter`
- `WIFI_INTERFACE`
  - Standard: `wlan0`
  - nur relevant, wenn der Pi aktiv ueber WLAN misst oder ein anderes WLAN-Interface genutzt wird
- `INTERNET_PING_TARGET`
  - Standard: `1.1.1.1`
- `HTTP_CHECK_URL`
  - Standard: `https://connectivitycheck.gstatic.com/generate_204`
- `DNS_CHECK_HOST`
  - Standard: `connectivitycheck.gstatic.com`
  - nur relevant fuer die WLAN-Client-Sicht des `wifi-exporter`
- `GATEWAY_TARGET`
  - optionales Override, falls der `wifi-exporter` das Gateway nicht aus der Routing-Tabelle ableiten soll

Die `.env.example` ist damit vor allem Dokumentation der moeglichen Overrides und kein zwingender Schritt fuer den Normalbetrieb.

Beispiel nur dann, wenn du wirklich abweichst:

```bash
WIFI_INTERFACE=wlan1
SNMP_COMMUNITY=monitoring
```

## Persistente Daten

Die wichtigsten Host-Daten liegen sichtbar im Projekt:

- [data/prometheus](/Users/benedikt/Projekte/measurepi/data/prometheus)
- [data/wifi-exporter](/Users/benedikt/Projekte/measurepi/data/wifi-exporter)

Grafanas interne Datenbank liegt absichtlich im Docker-Volume `grafana_data`, nicht in einem Host-Bind-Mount.

## SNMP fuer Infrastruktur

Die Infrastruktur-Ziele pflegst du in:

- [snmp/targets.yml](/Users/benedikt/Projekte/measurepi/snmp/targets.yml)

Beispiel:

```yaml
- targets: ["10.18.0.1"]
  labels:
    device: UXGPro
    role: gateway
    vendor: ubiquiti

- targets: ["10.18.0.11"]
  labels:
    device: switch-eg
    role: switch
    vendor: ubiquiti
```

Der `snmp-exporter` nutzt aktuell Standard-Interface-MIBs fuer eine moeglichst generische Sicht auf Router und Switches.

## SNMP fuer UniFi-APs

Die AP-Ziele pflegst du in:

- [ap/targets.yml](/Users/benedikt/Projekte/measurepi/ap/targets.yml)

Der eigene [unifi_ap_exporter.py](/Users/benedikt/Projekte/measurepi/containers/unifi-ap-exporter/unifi_ap_exporter.py) sammelt gezielt UniFi- und AP-nahe OIDs und macht daraus Prometheus-Metriken fuer:

- AP-Info
- Online-Status
- CPU / Memory / Load
- Interface-Metriken
- Radios
- SSIDs
- Client-Zahlen

## WLAN-Client-Sicht des Pi

Der `wifi-exporter` ist weiterhin Teil des Projekts, aber nicht mehr die einzige Hauptperspektive.

Er ist nuetzlich, wenn der Pi absichtlich als echter WLAN-Client mitmisst und liefert dann unter anderem:

- SSID
- BSSID
- RSSI
- Frequenz
- TX/RX-Bitrate
- Disconnects
- Roams
- Gateway-/Internet-Ausfaelle aus Sicht des Pi

Wichtig:

- Das neue `MeasurePi 01 Overview` behandelt fehlendes WLAN nicht mehr automatisch als Fehler.
- Wenn der Pi per Ethernet angebunden ist, bleiben WLAN-spezifische Erkenntnisse auf die spezialisierten Exporter/Dashboards begrenzt.

## Blackbox-Checks

Der `blackbox-exporter` prueft aktuell:

- externes ICMP
- externes HTTP

Diese Signale fliessen in das `Overview` ein und helfen dabei, lokale Infrastrukturprobleme von Upstream-/Internetproblemen zu trennen.

## Optionale Services

### `smartctl-exporter`

Bleibt optional und wird nur ueber das Profil `smartctl` gestartet:

```bash
docker compose --profile smartctl up -d
```

## Warum `network_mode: host`

Alle Services laufen mit `network_mode: host`, damit:

- die Messungen moeglichst nah an der Host-Realitaet bleiben
- keine Docker-NAT-Schicht zwischen Messung und Ziel liegt
- Exporter direkt ueber `localhost` erreichbar sind

## Dateien im Repo

- [docker-compose.yaml](/Users/benedikt/Projekte/measurepi/docker-compose.yaml)
- [prometheus/prometheus.yml.tmpl](/Users/benedikt/Projekte/measurepi/prometheus/prometheus.yml.tmpl)
- [blackbox/blackbox.yml](/Users/benedikt/Projekte/measurepi/blackbox/blackbox.yml)
- [containers/wifi-exporter/wifi_exporter.py](/Users/benedikt/Projekte/measurepi/containers/wifi-exporter/wifi_exporter.py)
- [containers/unifi-ap-exporter/unifi_ap_exporter.py](/Users/benedikt/Projekte/measurepi/containers/unifi-ap-exporter/unifi_ap_exporter.py)
- [containers/kernel-log-exporter/kernel_log_exporter.py](/Users/benedikt/Projekte/measurepi/containers/kernel-log-exporter/kernel_log_exporter.py)
- [containers/tshark-exporter/tshark_exporter.py](/Users/benedikt/Projekte/measurepi/containers/tshark-exporter/tshark_exporter.py)
- [containers/snmp-exporter](/Users/benedikt/Projekte/measurepi/containers/snmp-exporter)
- [snmp/targets.yml](/Users/benedikt/Projekte/measurepi/snmp/targets.yml)
- [ap/targets.yml](/Users/benedikt/Projekte/measurepi/ap/targets.yml)
- [grafana/dashboards](/Users/benedikt/Projekte/measurepi/grafana/dashboards)
- [scripts/generate_ap_dashboards.py](/Users/benedikt/Projekte/measurepi/scripts/generate_ap_dashboards.py)
- [scripts/prepare-data-dirs.sh](/Users/benedikt/Projekte/measurepi/scripts/prepare-data-dirs.sh)

## Was als Naechstes sinnvoll ist

Offene sinnvolle Ausbaupunkte sind aktuell:

- `MeasurePi Logs` fachlich auf die neue Architektur nachziehen
- echte Event-/Syslog-Quellen spaeter als Log-Schicht anbinden
- `unifi_ap_uptime_seconds` im AP-Exporter noch sauber nachziehen
