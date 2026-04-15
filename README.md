# MeasurePi

`MeasurePi` ist ein lokaler Diagnose-Stack fuer einen Raspberry Pi, der sich wie ein normaler WLAN-Client in das betroffene Netz einbucht und dort dauerhaft misst.

Das Ziel ist bewusst nicht "allgemeines Monitoring", sondern Fehleranalyse aus echter Client-Sicht:

- Ist das WLAN selbst weg?
- Ist nur das Gateway nicht erreichbar?
- Ist das Internet weg, obwohl WLAN und Gateway noch funktionieren?
- Gibt es Roaming-Ereignisse oder BSSID-Wechsel genau zu dem Zeitpunkt, an dem Nutzer Probleme melden?
- Ist der Pi selbst vielleicht gerade thermisch, CPU-seitig oder storage-seitig angeschlagen?

## Architektur in einem Satz

Der Pi misst lokal, `Prometheus` speichert die Zeitreihen, `Grafana` visualisiert sie, `Blackbox Exporter` prueft Netzwerkpfade, `Node Exporter` liefert Systemmetriken, `Smartctl Exporter` liefert best-effort Storage-Zustand und ein eigener `wifi-exporter` sammelt WLAN-spezifische Daten direkt aus der Client-Perspektive.

Hinweis fuer Raspberry Pi:

- Der Basis-Stack startet ohne zusaetzliche Profile.
- `smartctl-exporter` ist bewusst optional, weil nicht jedes Image fuer `linux/arm64` verfuegbar ist und viele SD-Karten ohnehin keine brauchbaren SMART-Daten liefern.
- ein zusaetzlicher `kernel-log-exporter` zaehlt stattdessen typische Storage-/Kernel-Fehler aus `dmesg`

## Persistente Daten auf dem Stick

Alle dauerhaften Daten liegen bewusst in einem sichtbaren Projektordner:

- [data/prometheus](/Users/benedikt/Projekte/measurepi/data/prometheus): Prometheus-Zeitreihen
- [data/wifi-exporter](/Users/benedikt/Projekte/measurepi/data/wifi-exporter): rebootfester WLAN-Exporter-State und Event-Log

Warum das wichtig ist:

- Die Daten liegen nicht versteckt in anonymen Docker-Volumes.
- Du kannst den Inhalt leicht sichern, kopieren oder inspizieren.
- Reboots des Pi verlieren weder Zeitreihen noch die WLAN-Ereigniszaehlung.
- Auf einem 64-GB-Stick ist das fuer diesen Zweck eine sehr vernuenftige und gut nachvollziehbare Struktur.

Ausnahme:

- Grafana speichert seine interne SQLite-Datenbank bewusst in einem Docker-Volume statt in `data/grafana`.

Warum wir das so machen:

- Das ist auf dem Raspberry Pi deutlich robuster als ein bind-gemounteter SQLite-Pfad.
- Damit vermeiden wir die wiederkehrenden Rechteprobleme rund um `GF_PATHS_DATA`.
- Dashboards und Provisioning bleiben trotzdem versionskontrolliert im Repo.

Vor dem ersten Start sollten die Rechte einmal passend gesetzt werden:

```bash
cd /opt/measurepi
sh ./scripts/prepare-data-dirs.sh
```

Danach muessen die Ordner bei normalen Reboots oder `docker compose down && docker compose up -d` nicht neu angelegt werden.

## Schnellstart

1. Projekt nach `/opt/measurepi` kopieren.
2. Rechte und Datenordner vorbereiten:

```bash
cd /opt/measurepi
sh ./scripts/prepare-data-dirs.sh
```

3. Optional: `.env.example` nach `.env` kopieren und nur dann anpassen, wenn du vom Standard abweichen willst.
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
- `GF_SECURITY_ADMIN_USER`: Grafana-Login
- `GF_SECURITY_ADMIN_PASSWORD`: Grafana-Passwort
- `GATEWAY_TARGET`: optionales Override fuer das lokale Gateway
- `INTERNET_PING_TARGET`: optionales Override fuer den externen ICMP-Test, Standard `1.1.1.1`
- `HTTP_CHECK_URL`: optionales Override fuer den externen HTTP-Test, Standard `https://connectivitycheck.gstatic.com/generate_204`

Warum diese Variablen wichtig sind:

- `WIFI_INTERFACE` ist nur relevant, wenn dein Mess-Interface nicht `wlan0` ist.
- `GATEWAY_TARGET` ist normalerweise nicht noetig, weil der `wifi-exporter` das Gateway direkt aus der Routing-Tabelle des Pi liest.
- Die externen Ziele haben brauchbare Defaults und muessen nur geaendert werden, wenn du bewusst andere Referenzziele nutzen willst.

`MeasurePi` liest die aktive SSID direkt vom gewaehlten Interface. Du musst also kein WLAN in `.env` doppelt eintragen. Welche SSID gerade genutzt wird, kommt live aus dem Host-System des Pi.

Ein minimalistischer `.env`-Fall fuer einen USB-WLAN-Adapter waere zum Beispiel:

```bash
WIFI_INTERFACE=wlan1
```

## Andere WLAN-Hardware als `wlan0`

Der Stack ist bewusst so gebaut, dass nicht zwingend der interne WLAN-Chip des Raspberry Pi genutzt werden muss.

Wenn du stattdessen einen USB-WLAN-Adapter oder eine andere Karte verwendest, setzt du einfach in der `.env`:

```bash
WIFI_INTERFACE=wlan1
```

oder zum Beispiel:

```bash
WIFI_INTERFACE=wlp0s20f3
```

Warum das sinnvoll ist:

- manche USB-Adapter haben bessere Empfaenger-Eigenschaften
- manche Chipsaetze verhalten sich beim Roaming anders
- externe Adapter erlauben mitunter gezieltere Vergleiche zwischen Hardware-Plattformen

Wichtig ist nur, dass genau dieses Interface auf dem Host mit dem Ziel-WLAN verbunden ist. Der Stack beobachtet dann genau diese echte Client-Verbindung.

## Aufbau des `docker-compose.yaml`

Das Compose-File ist der zentrale Einstiegspunkt. Es beschreibt den gesamten Diagnose-Stack in genau einer Datei und sorgt dafuer, dass die Services konsistent zusammen starten.

### `prometheus`

`Prometheus` ist der Zeitreihenspeicher des Systems.

Er macht Folgendes:

- ruft in kurzen Intervallen alle Exporter ab
- speichert deren Messwerte lokal auf dem Pi
- fuehrt die Blackbox-Probes fuer Gateway, Internet-Ping und HTTP-Checks aus

Warum das wichtig ist:

- Du brauchst keine Momentaufnahme, sondern eine Zeitachse.
- Erst ueber die Zeit wird sichtbar, ob Ausfaelle periodisch, zufaellig oder mit Roaming korreliert sind.
- Prometheus ist die Grundlage fuer spaetere Vergleiche wie "Signal okay, aber Gateway tot".

Besonderheit im Compose:

- Das Prometheus-Image wird lokal gebaut.
- Beim Start wird aus `prometheus/prometheus.yml.tmpl` per einfachem Shell-Rendering die echte Konfiguration erzeugt.
- Dadurch kannst du Ziele wie Gateway-IP oder HTTP-Test sauber ueber `.env` steuern.
- Wenn kein Gateway gesetzt ist, ermittelt der Exporter es automatisch ueber `ip route`.
- Die Zeitreihen landen persistent in `./data/prometheus`.

### `grafana`

`Grafana` ist die Visualisierungsschicht.

Es macht Folgendes:

- bindet `Prometheus` automatisch als Datenquelle ein
- laedt ein vorbereitetes Dashboard beim Start
- setzt das MeasurePi-Dashboard als Standard-Startseite nach dem Login
- zeigt dir die Diagnosemetriken direkt nach dem Hochfahren
- provisioniert zusaetzlich ein zweites Dashboard `MeasurePi Logs` fuer juengste Ereignisse und Log-Kontext

Warum das wichtig ist:

- Fehleranalyse wird erst dann effizient, wenn du Zeitpunkte und Korrelationen schnell sehen kannst.
- Ein Dashboard spart manuellen Query-Aufwand und macht Muster sofort sichtbar.
- Grafana speichert seine lokale Datenbank persistent in einem Docker-Volume namens `grafana_data`.

Das vorbereitete Dashboard zeigt unter anderem:

- WLAN-Verbindungsstatus
- Gateway-Erreichbarkeit
- Internet-Erreichbarkeit
- HTTP-Erfolg
- RSSI
- TX/RX-Bitrate
- Disconnects und Roams
- Temperatur, CPU-Last und freien Speicherplatz
- SMART-Status des Datentraegers, sofern verfuegbar

### `blackbox-exporter`

Der `Blackbox Exporter` fuehrt aktive Netzwerkprobes aus.

Er macht Folgendes:

- ICMP-Probe zum Gateway
- ICMP-Probe ins Internet
- HTTP-Probe zu einer definierten URL

Warum das wichtig ist:

- Ein Ping auf das Gateway zeigt, ob das Problem eher zwischen Client und lokalem Netz liegt.
- Ein externer Ping zeigt, ob das Problem erst hinter dem Gateway beginnt.
- Ein HTTP-Check zeigt, ob "Internet verfuegbar" auch auf Anwendungsebene noch stimmt.

Damit bekommst du genau die Trennung, die fuer die Diagnose entscheidend ist:

- WLAN kaputt
- lokales Netz kaputt
- WAN/Internet kaputt
- DNS/HTTP-Anwendungspfad kaputt

### `wifi-exporter`

Der eigene `wifi-exporter` ist das Herzstueck des Projekts.

Er misst direkt aus Sicht des WLAN-Clients:

- ob das Interface verbunden ist
- mit welcher SSID der Pi verbunden ist
- an welcher BSSID bzw. welchem AP der Pi haengt
- aktuelle Frequenz und Kanal
- RSSI
- TX- und RX-Bitrate
- Dauer der aktuellen Verbindung
- erkannte Disconnects
- erkannte AP-/BSSID-Wechsel als Roaming-Ereignisse
- Erreichbarkeit des Gateways aus Sicht genau dieses WLAN-Clients
- Erreichbarkeit eines externen Ping-Ziels
- Erfolg und Dauer eines HTTP-Checks

Warum das wichtig ist:

- Genau hier entsteht die fehlende Objektivierung deiner Hoerensagen-Probleme.
- Der Pi misst dort, wo die Nutzer stehen.
- Du kannst spaeter exakt sehen, ob ein Problem eher Funk, AP, Roaming, Gateway oder WAN war.

Beispiele fuer die Interpretation:

- `wifi_connected = 0`: Das Problem liegt sehr wahrscheinlich auf Funk-/Assoziations-/Roaming-Ebene.
- `wifi_connected = 1`, aber `wifi_gateway_reachable = 0`: WLAN steht formal, aber der Weg ins lokale Netz ist gestoert.
- Gateway erreichbar, Internet-Ping tot: eher WAN-/Upstream-Problem.
- RSSI gut, Bitrate schlecht: Hinweis auf Interferenz, Airtime-Pressure oder PHY-Probleme.
- Viele `wifi_roam_total`-Anstiege: moeglicher Roaming-, Zellgroessen- oder Sendeleistungsfehler.

Wichtige Einschraenkung:

- Disconnect- und Roam-Counter werden persistent gespeichert und ueberleben Reboots des Pi.
- Die SSID wird live vom Interface gelesen. Dadurch bleibt die Konfiguration schlank und nah am realen Host-Zustand.
- Das aktuelle Gateway kommt standardmaessig aus der Default-Route des Pi und muss nicht manuell gepflegt werden.

Zusaetzliche Persistenz:

- `./data/wifi-exporter/state.json` speichert Counter und letzte Event-Zeitpunkte.
- `./data/wifi-exporter/events.log` ist ein zeilenbasiertes JSON-Event-Log fuer Disconnects und Roams.

Warum das hilfreich ist:

- Du verlierst die Ereigniszaehlung nicht bei Reboot oder Container-Neustart.
- Das Event-Log kann spaeter leicht weiterverarbeitet oder archiviert werden.
- Damit wird aus "Counter seit letztem Start" eine wesentlich robustere Langzeitdiagnose.

### `node-exporter`

`Node Exporter` liefert Host-Systemmetriken vom Raspberry Pi selbst.

Er sammelt zum Beispiel:

- CPU-Auslastung
- Load
- Temperatur-Sensoren
- Filesystem-Metriken
- RAM-Informationen

Warum das wichtig ist:

- Du willst ausschliessen koennen, dass der Mess-Client selbst die Ursache ist.
- Wenn der Pi ueberhitzt, die CPU permanent anschlaegt oder das Root-Filesystem voll laeuft, sind Messwerte weniger belastbar.

### `smartctl-exporter`

`Smartctl Exporter` liefert best-effort Gesundheitsdaten des Speichermediums.

Er ist besonders nuetzlich bei:

- USB-SSDs
- SATA-Drives hinter brauchbaren USB-Adaptern
- manchen USB-Sticks mit vernuenftiger SMART-Unterstuetzung

Warum das wichtig ist:

- Wenn das Speichermedium problematisch ist, kann der Pi selbst instabil werden.
- Gerade bei Langzeitmessung willst du SD-/USB-Probleme nicht mit WLAN-Problemen verwechseln.

Wichtige Einschraenkung:

- Viele SD-Karten liefern kein klassisches SMART.
- Auf einem Raspberry Pi ist Storage-Health deshalb immer nur best effort.
- Fehlen SMART-Daten, ist das kein Fehler des Stacks, sondern oft eine Hardware-Grenze des Mediums.
- Der Service ist im Compose standardmaessig deaktiviert und nur ueber das Profil `smartctl` aktivierbar.

Aktivierung nur wenn gewuenscht und wenn ein kompatibles Image vorhanden ist:

```bash
docker compose --profile smartctl up -d
```

## Warum alle Services im `host`-Netzwerk laufen

Alle Container laufen mit `network_mode: host`.

Der Grund dafuer ist schlicht Diagnosenaehe:

- keine Docker-NAT-Schicht zwischen Probe und Host
- keine verfremdete Sicht auf das Netz
- direkte Erreichbarkeit der Exporter ueber localhost
- moeglichst wenig Distanz zwischen "echter Pi als WLAN-Client" und "Messung"

Gerade fuer einen WLAN-Diagnose-Pi ist das sinnvoller als ein rein isoliertes Bridge-Setup.

## Wie die Daten zusammenhaengen

Der Datenfluss ist absichtlich einfach:

1. `wifi-exporter`, `node-exporter` und `smartctl-exporter` liefern Metriken.
2. `blackbox-exporter` fuehrt aktive Probes fuer externe ICMP- und HTTP-Ziele aus.
3. `kernel-log-exporter` zaehlt typische Kernel-/Storage-Fehlermuster seit dem letzten Boot.
4. `Prometheus` sammelt alles in festen Intervallen ein.
5. `Grafana` visualisiert die Zeitreihen in einem Diagnose-Dashboard.

Das ist der eigentliche Mehrwert:

- nicht nur "es fuehlt sich schlecht an"
- sondern "um 14:07 fiel die Gateway-Erreichbarkeit weg, waehrend RSSI stabil blieb und kurz davor ein BSSID-Wechsel stattfand"

Wenn du das aktuelle Gateway direkt sehen willst, kannst du es an zwei Stellen nachvollziehen:

- auf dem Host mit `ip route`
- in Prometheus ueber die Metrik `wifi_default_gateway_info`

## Was der Stack diagnostisch beantworten kann

Mit diesem Setup kannst du typische Fehlerbilder sauber trennen:

- `WLAN disconnected`: Funkproblem, AP-Assoziation, Roaming oder AP-Ausfall
- `WLAN verbunden, Gateway nicht erreichbar`: lokales Netz, Airtime, Interferenz, Bridge-/Switch-/AP-Problem
- `Gateway erreichbar, Internet nicht`: WAN, UXG-Upstream, DNS oder externer Pfad
- `Viele AP-Wechsel`: Roaming-Tuning, Zellgroesse, Sendeleistung, Kanalplanung
- `Schlechte Bitrate trotz brauchbarem Signal`: Interferenz, Airtime-Last, MCS-/PHY-Probleme

## Dateien im Repo

- [docker-compose.yaml](/Users/benedikt/Projekte/measurepi/docker-compose.yaml): gesamter Stack
- [prometheus/prometheus.yml.tmpl](/Users/benedikt/Projekte/measurepi/prometheus/prometheus.yml.tmpl): Prometheus-Scrapes und Blackbox-Jobs
- [blackbox/blackbox.yml](/Users/benedikt/Projekte/measurepi/blackbox/blackbox.yml): Probe-Module fuer ICMP und HTTP
- [containers/wifi-exporter/wifi_exporter.py](/Users/benedikt/Projekte/measurepi/containers/wifi-exporter/wifi_exporter.py): eigener WLAN-Exporter
- [containers/kernel-log-exporter/kernel_log_exporter.py](/Users/benedikt/Projekte/measurepi/containers/kernel-log-exporter/kernel_log_exporter.py): zaehlt Kernel-/Storage-Fehler aus `dmesg`
- [grafana/dashboards/measurepi-overview.json](/Users/benedikt/Projekte/measurepi/grafana/dashboards/measurepi-overview.json): vorprovisioniertes Dashboard
- [data](/Users/benedikt/Projekte/measurepi/data): persistente Host-Daten fuer Prometheus und den WLAN-Exporter
- [scripts/prepare-data-dirs.sh](/Users/benedikt/Projekte/measurepi/scripts/prepare-data-dirs.sh): setzt die benoetigten Verzeichnisrechte fuer den ersten Start

## Betriebshinweise

- Der Pi sollte physisch genau dort stehen, wo Nutzer Probleme melden.
- Der Pi sollte bewusst per WLAN angebunden sein, nicht per LAN.
- Wenn ein externer WLAN-Adapter genutzt wird, sollte nur das Mess-Interface in `WIFI_INTERFACE` eingetragen werden.
- Fuer eine brauchbare Aussage solltest du mindestens 24 bis 48 Stunden messen.
- Notiere dir ungefaehre Beschwerdezeiten von Nutzern, damit du spaeter im Dashboard dagegenhalten kannst.

## Konzept-Review und Verbesserungsansaetze

Die Grundidee ist stark. Vor allem die Trennung zwischen Funk, lokalem Gateway und Internetpfad ist genau der richtige Hebel fuer echte Ursachenanalyse. Ein paar Erweiterungen wuerden das Projekt noch robuster machen:

### 1. Lokale Referenzprobe per Ethernet

Wenn spaeter moeglich, waere ein zweiter Messpfad per LAN sehr wertvoll.

Warum:

- WLAN-Probleme und allgemeine Upstream-Probleme lassen sich dann noch haerter voneinander trennen.
- Wenn WLAN-Messung schlecht ist, LAN-Messung aber stabil bleibt, ist der Funkpfad praktisch ueberfuehrt.

### 3. Controller-Korrelation als optionale zweite Ebene

Dein Kerngedanke "Client-Sicht first" ist richtig. Fuer ein oeffentliches Repo waere aber eine optionale Erweiterung spannend:

- zusaetzlicher Pull von UniFi-Controller-Daten
- nur als optionales Modul, nicht als Pflicht

Warum:

- Dann koennte man Client-Symptome spaeter mit AP-Kanal, AP-Last oder Reassociation-Events korrelieren.
- Wichtig ist nur, das nicht zur Grundvoraussetzung zu machen.

### 4. Messung gegen mehrere Internetziele

Ein einzelnes Ziel wie `1.1.1.1` ist gut, aber nicht unfehlbar.

Sinnvoll waere spaeter optional:

- zwei ICMP-Ziele
- ein HTTP-Ziel
- eventuell ein DNS-Check

Warum:

- So vermeidest du, dass ein einzelner externer Dienst als falscher Schuldiger erscheint.

### 5. Boot- und Reboot-Resilienz dokumentieren

Fuer ein oeffentliches Repo lohnt sich eine kleine Betreiberperspektive:

- Was passiert nach Stromausfall?
- Startet Docker automatisch?
- Bleiben Prometheus-Daten erhalten?

Die Compose-Datei hat schon gute Restart-Policies. In der README koennte spaeter noch ein kurzer Abschnitt fuer "Produktionsbetrieb auf dem Pi" dazu kommen.

## Start und Betrieb

Stack bauen und starten:

```bash
cd /opt/measurepi
sh ./scripts/prepare-data-dirs.sh
docker compose up -d --build
```

Bei einem normalen Reboot oder nach einem versehentlichen Stromverlust gilt:

- Die Daten in `data/` bleiben erhalten.
- Grafana und Prometheus kommen wieder hoch, solange die Rechte in `data/` fuer Prometheus und den WLAN-Exporter unveraendert bleiben.
- Du musst keine `data/grafana`-Struktur mehr pflegen.
- Die Dashboard-JSONs liegen getrennt read-only unter `/etc/grafana/dashboards`, waehrend Grafanas Datenbank in einem Docker-Volume lebt.

Ein Neuaufbau von Grafana ist nur dann sinnvoll, wenn:

- die Grafana-SQLite-Datei beschaedigt ist
- du bewusst einen frischen Grafana-Start willst

Wenn du Grafana wirklich frisch zuruecksetzen willst:

```bash
cd /opt/measurepi
docker compose down
docker volume rm measurepi_grafana_data
docker compose up -d
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
```

Stack stoppen:

```bash
docker compose down
```
