# MeasurePi

`MeasurePi` ist ein lokaler Diagnose-Stack fuer einen Raspberry Pi, der sich wie ein normaler WLAN-Client in das betroffene Netz einbucht und dort dauerhaft misst.

Das Ziel ist bewusst nicht "allgemeines Monitoring", sondern Fehleranalyse aus echter Client-Sicht:

- Ist das WLAN selbst weg?
- Ist nur das Gateway nicht erreichbar?
- Ist das Internet weg, obwohl WLAN und Gateway noch funktionieren?
- Gibt es Roaming-Ereignisse oder BSSID-Wechsel genau zu dem Zeitpunkt, an dem Nutzer Probleme melden?
- Ist der Pi selbst vielleicht thermisch, CPU-seitig oder storage-seitig angeschlagen?

## Architektur in einem Satz

Der Pi misst lokal, `Prometheus` speichert die Zeitreihen, `Grafana` visualisiert sie, `Blackbox Exporter` prueft externe Ziele, `Node Exporter` liefert Host-Metriken, `wifi-exporter` sammelt WLAN- und Ausfallkontext, `kernel-log-exporter` wertet Kernel-/Storage-Hinweise aus und `tshark-exporter` liefert Zusatzsignale aus dem normalen Client-Traffic.

## Was der Stack heute kann

- WLAN-Verbindung aus Client-Sicht messen
- Gateway-, Internet-, HTTP-, DNS- und ARP-Hinweise korrelieren
- Disconnects, Roams, Gateway-Outages und Internet-Outages als Ereignisse zaehlen
- Ereignisse mit Kontext speichern:
  - Zeit
  - Event-Typ
  - SSID
  - BSSID / AP
  - RSSI
  - Frequenz
  - TX/RX-Bitrate
  - Gateway
  - Reason Guess
  - ARP/DNS/HTTP-Kontext
  - Outage-Dauer, sofern bekannt
- Host-Zustand des Pi beobachten:
  - CPU
  - Load
  - Temperatur
  - Filesystem
- Kernel-/Storage-Warnhinweise zaehlen
- normalen Client-Traffic via `tshark` auswerten:
  - ARP
  - DNS
  - DHCP
  - ICMP
  - TCP-Retransmits

## Dashboards

Es gibt zwei vorprovisionierte Grafana-Dashboards:

- `MeasurePi Overview`
  - Betriebsansicht fuer WLAN-/Gateway-/Internet-Status
  - Signalstaerke, Bitrate, Latenzen
  - Event-Zaehler fuer Disconnects, Roams, Gateway- und Internet-Outages
- `MeasurePi Logs`
  - juengste Connectivity-Incidents als Tabelle
  - Reason Guess / Detailtiefe
  - aktuelle Connectivity-State-Tabelle
  - Kernel-Storage-Hinweise
  - `tshark`-basierte Client-Traffic-Hinweise

## Raspberry-Pi-Hinweise

- Der Basis-Stack startet ohne zusaetzliche Profile.
- `smartctl-exporter` bleibt optional, weil viele SD-Karten und USB-Sticks kein brauchbares SMART liefern.
- Grafana speichert seine interne SQLite-Datenbank absichtlich in einem Docker-Volume statt in einem Host-Bind-Mount. Das ist auf dem Pi deutlich robuster.

## Persistente Daten

Die dauerhaften Host-Daten liegen bewusst sichtbar im Projekt:

- [data/prometheus](/Users/benedikt/Projekte/measurepi/data/prometheus): Prometheus-Zeitreihen
- [data/wifi-exporter](/Users/benedikt/Projekte/measurepi/data/wifi-exporter): `events.log` und `state.json`

Warum das wichtig ist:

- Die Messhistorie liegt nicht versteckt in anonymen Docker-Volumes.
- Du kannst Ereignislog und Prometheus-Daten leicht sichern oder inspizieren.
- Reboots verlieren weder Zeitreihen noch die Event-Historie des `wifi-exporter`.

Ausnahme:

- Grafanas interne DB liegt in einem Docker-Volume `grafana_data`.

Warum:

- deutlich robuster als ein bind-gemounteter SQLite-Pfad auf dem Pi
- vermeidet Rechteprobleme rund um `GF_PATHS_DATA`
- Dashboards und Provisioning bleiben trotzdem versioniert im Repo

## Schnellstart

1. Projekt nach `/opt/measurepi` kopieren.
2. Datenordner vorbereiten:

```bash
cd /opt/measurepi
sh ./scripts/prepare-data-dirs.sh
```

3. Optional `.env.example` nach `.env` kopieren und nur dann anpassen, wenn du vom Standard abweichen willst.
4. Stack starten:

```bash
cd /opt/measurepi
docker compose up -d --build
```

5. Grafana oeffnen: `http://<pi-ip>:3000`
6. Prometheus oeffnen: `http://<pi-ip>:9090`

Ohne `.env` startet der Stack bereits mit sinnvollen Defaults.

## Optionale Konfiguration ueber `.env`

- `WIFI_INTERFACE`: WLAN-Interface des Pi, meist `wlan0`
- `DNS_CHECK_HOST`: Host fuer den DNS-Test, Standard `connectivitycheck.gstatic.com`
- `GF_SECURITY_ADMIN_USER`: Grafana-Login
- `GF_SECURITY_ADMIN_PASSWORD`: Grafana-Passwort
- `GATEWAY_TARGET`: optionales Override fuer das lokale Gateway
- `INTERNET_PING_TARGET`: optionales Override fuer den externen ICMP-Test, Standard `1.1.1.1`
- `HTTP_CHECK_URL`: optionales Override fuer den externen HTTP-Test, Standard `https://connectivitycheck.gstatic.com/generate_204`

Wichtig dazu:

- `WIFI_INTERFACE` ist nur relevant, wenn dein Mess-Interface nicht `wlan0` ist.
- `GATEWAY_TARGET` ist normalerweise nicht noetig, weil der `wifi-exporter` das Gateway direkt aus der Routing-Tabelle des Pi liest.
- `DNS_CHECK_HOST`, `INTERNET_PING_TARGET` und `HTTP_CHECK_URL` haben brauchbare Defaults und muessen nur geaendert werden, wenn du bewusst andere Referenzziele willst.
- Die aktive SSID wird live vom Interface gelesen. Du musst sie nicht in `.env` doppelt pflegen.

Minimalbeispiel fuer einen USB-WLAN-Adapter:

```bash
WIFI_INTERFACE=wlan1
```

## Andere WLAN-Hardware als `wlan0`

Der Stack ist bewusst so gebaut, dass nicht zwingend der interne WLAN-Chip des Raspberry Pi genutzt werden muss.

Wenn du stattdessen einen USB-WLAN-Adapter oder eine andere Karte verwendest:

```bash
WIFI_INTERFACE=wlan1
```

oder zum Beispiel:

```bash
WIFI_INTERFACE=wlp0s20f3
```

Wichtig ist nur, dass genau dieses Interface auf dem Host mit dem Ziel-WLAN verbunden ist. Der Stack beobachtet dann genau diese echte Client-Verbindung.

## Aufbau des Compose-Stacks

### `prometheus`

`Prometheus` ist der Zeitreihenspeicher.

Es:

- scraped alle Exporter
- speichert die Messwerte lokal auf dem Pi
- fuehrt die Blackbox-Probes fuer externe ICMP- und HTTP-Ziele aus

Die Zeitreihen landen persistent in `./data/prometheus`.

### `grafana`

`Grafana` ist die Visualisierungsschicht.

Es:

- provisioniert `Prometheus` als Datenquelle
- laedt beide Dashboards automatisch
- setzt `MeasurePi Overview` als Startseite nach dem Login

Grafanas DB lebt bewusst im Docker-Volume `grafana_data`.

### `blackbox-exporter`

Der `Blackbox Exporter` prueft externe Netzwerkpfade:

- Internet-ICMP
- HTTP-Ziel

Damit trennst du lokale WLAN-/LAN-Probleme von externen Upstream-Problemen.

### `wifi-exporter`

Der `wifi-exporter` ist das Herzstueck des Projekts.

Er sammelt direkt aus Sicht des WLAN-Clients:

- SSID
- BSSID / AP
- RSSI
- Kanal / Frequenz
- TX/RX-Bitrate
- Gateway-Erreichbarkeit
- Internet-Erreichbarkeit
- HTTP-Erreichbarkeit
- DNS-Erfolg
- ARP-Hinweis auf das Gateway
- Disconnects
- Roams
- Gateway- und Internet-Outages

Er schreibt ausserdem Ereignisse mit Kontext nach:

- [data/wifi-exporter/events.log](/Users/benedikt/Projekte/measurepi/data/wifi-exporter)
- [data/wifi-exporter/state.json](/Users/benedikt/Projekte/measurepi/data/wifi-exporter)

### `kernel-log-exporter`

Der `kernel-log-exporter` wertet `dmesg` nach typischen Storage-/Kernel-Fehlermustern aus.

Das ist auf Pi-/USB-/SD-Setups oft nuetzlicher als klassisches SMART.

### `tshark-exporter`

Der `tshark-exporter` beobachtet den normalen Client-Traffic auf dem aktiven WLAN-Interface.

Er liefert Zusatzhinweise fuer:

- ARP
- DNS
- DHCP
- ICMP
- TCP-Retransmits

Wichtig:

- Das ist kein Monitor-Mode-Sniffer.
- Er sieht keine WLAN-Management-Frames wie `deauth` oder `reassoc`.
- Er ist trotzdem nuetzlich, um Client-Symptome auf Layer 2.5/3/4 besser einzuordnen.

### `node-exporter`

`Node Exporter` liefert Host-Metriken des Pi:

- CPU
- Load
- Temperatur
- Filesystem
- RAM

### `smartctl-exporter` (optional)

`smartctl-exporter` bleibt optional.

Er ist vor allem dann interessant, wenn statt SD-Karte/USB-Stick eher USB-SSD- oder SATA-basierte Medien mit brauchbarer SMART-Unterstuetzung genutzt werden.

Aktivierung nur wenn gewuenscht:

```bash
docker compose --profile smartctl up -d
```

## Warum `network_mode: host`

Alle Services laufen mit `network_mode: host`.

Der Grund:

- keine Docker-NAT-Schicht zwischen Messung und Host
- moeglichst echte Client-Sicht
- Exporter direkt ueber `localhost` erreichbar

Fuer einen WLAN-Diagnose-Pi ist das sinnvoller als ein klassisches Bridge-Setup.

## Wie die Daten zusammenhaengen

1. `wifi-exporter`, `kernel-log-exporter`, `tshark-exporter` und `node-exporter` liefern Metriken.
2. `blackbox-exporter` prueft externe Ziele.
3. `Prometheus` sammelt alles in festen Intervallen ein.
4. `Grafana` visualisiert Uebersichten und Ereignisdetails.

Der eigentliche Mehrwert ist:

- nicht nur "es fuehlt sich schlecht an"
- sondern "um 14:07 war das WLAN noch verbunden, ARP aufs Gateway war da, aber ICMP aufs Gateway fehlte, kurz darauf wurde das Gateway wieder erreichbar"

## Was der Stack diagnostisch beantworten kann

Mit dem aktuellen Setup kannst du typische Fehlerbilder deutlich besser trennen:

- `WLAN disconnected`
  - Funkproblem, Assoziation, Roaming oder AP-Ausfall
- `WLAN verbunden, Gateway nicht erreichbar`
  - lokales Netz, Airtime, Bridge-/Switch-/AP-Problem
- `Gateway per ARP sichtbar, aber kein ICMP`
  - Gateway / lokaler Pfad antwortet nicht auf IP-Ebene
- `Gateway okay, DNS nicht`
  - DNS-spezifisches Problem
- `Gateway okay, DNS okay, HTTP nicht`
  - Upstream-/HTTP-Pfadproblem
- `viele AP-Wechsel`
  - Roaming-Tuning, Zellgroesse, Sendeleistung, Kanalplanung
- `schlechte Bitrate trotz brauchbarem Signal`
  - Interferenz, Airtime-Last, PHY-/MCS-Thema

## Dateien im Repo

- [docker-compose.yaml](/Users/benedikt/Projekte/measurepi/docker-compose.yaml): gesamter Stack
- [prometheus/prometheus.yml.tmpl](/Users/benedikt/Projekte/measurepi/prometheus/prometheus.yml.tmpl): Prometheus-Scrapes
- [blackbox/blackbox.yml](/Users/benedikt/Projekte/measurepi/blackbox/blackbox.yml): Blackbox-Module
- [containers/wifi-exporter/wifi_exporter.py](/Users/benedikt/Projekte/measurepi/containers/wifi-exporter/wifi_exporter.py): WLAN-/Event-/ARP-/DNS-Exporter
- [containers/kernel-log-exporter/kernel_log_exporter.py](/Users/benedikt/Projekte/measurepi/containers/kernel-log-exporter/kernel_log_exporter.py): Kernel-/Storage-Fehlerauswertung
- [containers/tshark-exporter/tshark_exporter.py](/Users/benedikt/Projekte/measurepi/containers/tshark-exporter/tshark_exporter.py): `tshark`-basierte Client-Traffic-Hinweise
- [grafana/dashboards/measurepi-overview.json](/Users/benedikt/Projekte/measurepi/grafana/dashboards/measurepi-overview.json): Uebersichts-Dashboard
- [grafana/dashboards/measurepi-logs.json](/Users/benedikt/Projekte/measurepi/grafana/dashboards/measurepi-logs.json): Ereignis-/Logs-Dashboard
- [data](/Users/benedikt/Projekte/measurepi/data): persistente Host-Daten fuer Prometheus und den WLAN-Exporter
- [scripts/prepare-data-dirs.sh](/Users/benedikt/Projekte/measurepi/scripts/prepare-data-dirs.sh): setzt die benoetigten Verzeichnisrechte fuer den ersten Start

## Betriebshinweise

- Der Pi sollte physisch genau dort stehen, wo Nutzer Probleme melden.
- Der Pi sollte bewusst per WLAN angebunden sein, nicht per LAN.
- Fuer eine brauchbare Aussage solltest du mindestens 24 bis 48 Stunden messen.
- Notiere dir ungefaehre Beschwerdezeiten von Nutzern, damit du spaeter gezielt im Dashboard dagegenhalten kannst.

## Start und Betrieb

Stack bauen und starten:

```bash
cd /opt/measurepi
sh ./scripts/prepare-data-dirs.sh
docker compose up -d --build
```

Status pruefen:

```bash
docker compose ps
```

Logs ansehen:

```bash
docker compose logs -f wifi-exporter
docker compose logs -f prometheus
docker compose logs -f grafana
docker compose logs -f tshark-exporter
```

Stack stoppen:

```bash
docker compose down
```

## Reboot- und Wiederanlauf-Verhalten

Bei normalem Reboot oder versehentlichem Stromverlust gilt:

- Die Daten in `data/` bleiben erhalten.
- Prometheus und die Exporter kommen wieder hoch, solange die Rechte in `data/` stimmen.
- Du musst keine `data/grafana`-Struktur pflegen, weil Grafana in einem Docker-Volume lebt.

Wenn du Grafana bewusst frisch zuruecksetzen willst:

```bash
cd /opt/measurepi
docker compose down
docker volume rm measurepi_grafana_data
docker compose up -d
```
