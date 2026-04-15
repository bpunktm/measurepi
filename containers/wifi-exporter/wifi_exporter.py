import os
import re
import subprocess
import time
import json
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional


def shell(command: list[str], timeout: int = 5) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 1, ""
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


def escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def metric_line(name: str, value: float, labels: Optional[dict[str, str]] = None) -> str:
    if labels:
        rendered = ",".join(
            f'{key}="{escape_label_value(str(val))}"'
            for key, val in sorted(labels.items())
        )
        return f"{name}{{{rendered}}} {value}"
    return f"{name} {value}"


def channel_from_frequency(freq_mhz: int) -> int:
    if 2412 <= freq_mhz <= 2472:
        return (freq_mhz - 2407) // 5
    if freq_mhz == 2484:
        return 14
    if 5000 <= freq_mhz <= 5900:
        return (freq_mhz - 5000) // 5
    if 5955 <= freq_mhz <= 7115:
        return (freq_mhz - 5950) // 5
    return 0


@dataclass
class WifiSnapshot:
    connected: bool
    ssid: str = ""
    bssid: str = ""
    signal_dbm: float = 0.0
    frequency_mhz: int = 0
    tx_bitrate_mbps: float = 0.0
    rx_bitrate_mbps: float = 0.0
    connected_seconds: float = 0.0


class WifiCollector:
    def __init__(self) -> None:
        self.interface = os.getenv("WIFI_INTERFACE", "wlan0")
        self.gateway_target = os.getenv("GATEWAY_TARGET", "")
        self.internet_ping_target = os.getenv("INTERNET_PING_TARGET", "1.1.1.1")
        self.http_check_url = os.getenv(
            "HTTP_CHECK_URL",
            "https://connectivitycheck.gstatic.com/generate_204",
        )
        self.dns_check_host = os.getenv("DNS_CHECK_HOST", "connectivitycheck.gstatic.com")
        self.data_dir = os.getenv("WIFI_EXPORTER_DATA_DIR", "/data")
        self.state_file = os.path.join(self.data_dir, "state.json")
        self.event_log_file = os.path.join(self.data_dir, "events.log")
        self.max_recent_events = 12
        self.recent_events: list[dict[str, object]] = []
        self.disconnect_total = 0.0
        self.roam_total = 0.0
        self.gateway_unreachable_total = 0.0
        self.internet_unreachable_total = 0.0
        self.last_disconnect_ts = 0.0
        self.last_roam_ts = 0.0
        self.last_gateway_unreachable_ts = 0.0
        self.last_internet_unreachable_ts = 0.0
        self.last_gateway_restored_ts = 0.0
        self.last_internet_restored_ts = 0.0
        self.last_gateway_outage_duration_seconds = 0.0
        self.last_internet_outage_duration_seconds = 0.0
        self.previous_connected = False
        self.previous_bssid = ""
        self.previous_gateway_ok = True
        self.previous_internet_ok = True
        self.gateway_outage_active_since = 0.0
        self.internet_outage_active_since = 0.0
        self.ensure_data_dir()
        self.load_state()
        self.load_recent_events()

    def ensure_data_dir(self) -> None:
        os.makedirs(self.data_dir, exist_ok=True)

    def load_state(self) -> None:
        try:
            with open(self.state_file, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return

        self.disconnect_total = float(payload.get("disconnect_total", 0))
        self.roam_total = float(payload.get("roam_total", 0))
        self.gateway_unreachable_total = float(payload.get("gateway_unreachable_total", 0))
        self.internet_unreachable_total = float(payload.get("internet_unreachable_total", 0))
        self.last_disconnect_ts = float(payload.get("last_disconnect_ts", 0))
        self.last_roam_ts = float(payload.get("last_roam_ts", 0))
        self.last_gateway_unreachable_ts = float(payload.get("last_gateway_unreachable_ts", 0))
        self.last_internet_unreachable_ts = float(payload.get("last_internet_unreachable_ts", 0))
        self.last_gateway_restored_ts = float(payload.get("last_gateway_restored_ts", 0))
        self.last_internet_restored_ts = float(payload.get("last_internet_restored_ts", 0))
        self.last_gateway_outage_duration_seconds = float(payload.get("last_gateway_outage_duration_seconds", 0))
        self.last_internet_outage_duration_seconds = float(payload.get("last_internet_outage_duration_seconds", 0))
        self.gateway_outage_active_since = float(payload.get("gateway_outage_active_since", 0))
        self.internet_outage_active_since = float(payload.get("internet_outage_active_since", 0))

    def save_state(self) -> None:
        payload = {
            "disconnect_total": self.disconnect_total,
            "roam_total": self.roam_total,
            "gateway_unreachable_total": self.gateway_unreachable_total,
            "internet_unreachable_total": self.internet_unreachable_total,
            "last_disconnect_ts": self.last_disconnect_ts,
            "last_roam_ts": self.last_roam_ts,
            "last_gateway_unreachable_ts": self.last_gateway_unreachable_ts,
            "last_internet_unreachable_ts": self.last_internet_unreachable_ts,
            "last_gateway_restored_ts": self.last_gateway_restored_ts,
            "last_internet_restored_ts": self.last_internet_restored_ts,
            "last_gateway_outage_duration_seconds": self.last_gateway_outage_duration_seconds,
            "last_internet_outage_duration_seconds": self.last_internet_outage_duration_seconds,
            "gateway_outage_active_since": self.gateway_outage_active_since,
            "internet_outage_active_since": self.internet_outage_active_since,
        }
        tmp_file = f"{self.state_file}.tmp"
        try:
            with open(tmp_file, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            os.replace(tmp_file, self.state_file)
        except OSError:
            return

    def load_recent_events(self) -> None:
        try:
            with open(self.event_log_file, "r", encoding="utf-8") as handle:
                lines = handle.readlines()[-self.max_recent_events :]
        except OSError:
            self.recent_events = []
            return

        events: list[dict[str, object]] = []
        for line in lines:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        self.recent_events = events[-self.max_recent_events :]

    def append_event(
        self,
        event_type: str,
        wifi: WifiSnapshot,
        timestamp: float,
        extra: Optional[dict[str, object]] = None,
    ) -> None:
        payload = {
            "ts": timestamp,
            "ts_iso": datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(),
            "event": event_type,
            "details_available": "true",
            "interface": self.interface,
            "ssid": wifi.ssid,
            "bssid": wifi.bssid,
            "signal_dbm": wifi.signal_dbm,
            "frequency_mhz": wifi.frequency_mhz,
            "tx_bitrate_mbps": wifi.tx_bitrate_mbps,
            "rx_bitrate_mbps": wifi.rx_bitrate_mbps,
            "connected_seconds": wifi.connected_seconds,
        }
        if extra:
            payload.update(extra)
        try:
            with open(self.event_log_file, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, sort_keys=True) + "\n")
        except OSError:
            return
        self.recent_events.append(payload)
        self.recent_events = self.recent_events[-self.max_recent_events :]

    def current_gateway(self) -> str:
        if self.gateway_target:
            return self.gateway_target
        code, output = shell(["ip", "route", "show", "default", "dev", self.interface])
        if code != 0:
            return ""
        match = re.search(r"default via ([0-9a-fA-F:\.]+)", output)
        return match.group(1) if match else ""

    def collect_wifi(self) -> WifiSnapshot:
        code, output = shell(["iw", "dev", self.interface, "link"])
        if code != 0 or "Not connected." in output:
            return WifiSnapshot(connected=False)

        snapshot = WifiSnapshot(connected=True)
        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("SSID:"):
                snapshot.ssid = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("Connected to "):
                snapshot.bssid = stripped.split()[2].strip()
            elif stripped.startswith("freq:"):
                raw_freq = stripped.split(":", 1)[1].strip()
                try:
                    snapshot.frequency_mhz = int(float(raw_freq))
                except ValueError:
                    snapshot.frequency_mhz = 0
            elif stripped.startswith("signal:"):
                match = re.search(r"(-?\d+(\.\d+)?)", stripped)
                if match:
                    snapshot.signal_dbm = float(match.group(1))
            elif stripped.startswith("tx bitrate:"):
                match = re.search(r"(\d+(\.\d+)?)\s+MBit/s", stripped)
                if match:
                    snapshot.tx_bitrate_mbps = float(match.group(1))
            elif stripped.startswith("rx bitrate:"):
                match = re.search(r"(\d+(\.\d+)?)\s+MBit/s", stripped)
                if match:
                    snapshot.rx_bitrate_mbps = float(match.group(1))
            elif stripped.startswith("connected time:"):
                match = re.search(r"(\d+)", stripped)
                if match:
                    snapshot.connected_seconds = float(match.group(1))
        return snapshot

    def ping(self, target: str) -> tuple[int, float]:
        if not target:
            return 0, 0.0
        code, output = shell(
            ["ping", "-I", self.interface, "-c", "1", "-W", "2", target],
            timeout=4,
        )
        if code != 0:
            return 0, 0.0
        match = re.search(r"time=(\d+(\.\d+)?)\s*ms", output)
        return 1, float(match.group(1)) if match else 0.0

    def gateway_arp_reachable(self, gateway: str) -> int:
        if not gateway:
            return 0
        code, output = shell(["ip", "neigh", "show", gateway, "dev", self.interface])
        if code != 0:
            return 0
        normalized = output.strip().upper()
        if not normalized:
            return 0
        if "FAILED" in normalized or "INCOMPLETE" in normalized:
            return 0
        return 1 if "LLADDR" in normalized or "REACHABLE" in normalized or "STALE" in normalized or "DELAY" in normalized else 0

    def dns_check(self) -> tuple[int, float]:
        started = time.time()
        try:
            socket.getaddrinfo(self.dns_check_host, None)
        except socket.gaierror:
            return 0, time.time() - started
        return 1, time.time() - started

    def classify_gateway_reason(self, wifi: WifiSnapshot, gateway_arp_ok: int) -> str:
        if not wifi.connected:
            return "wifi_disconnected"
        if not gateway_arp_ok:
            return "gateway_arp_unreachable"
        return "gateway_no_icmp_reply"

    def classify_internet_reason(self, wifi: WifiSnapshot, gateway_ok: int, dns_ok: int, http_ok: int) -> str:
        if not wifi.connected:
            return "wifi_disconnected"
        if not gateway_ok:
            return "gateway_unreachable"
        if not dns_ok:
            return "dns_resolution_failed"
        if not http_ok:
            return "http_path_failed"
        return "internet_ping_failed"

    def http_check(self) -> tuple[int, int, float]:
        code, output = shell(
            [
                "curl",
                "--interface",
                self.interface,
                "--max-time",
                "5",
                "--output",
                "/dev/null",
                "--silent",
                "--show-error",
                "--write-out",
                "%{http_code} %{time_total}",
                self.http_check_url,
            ],
            timeout=7,
        )
        if code != 0:
            return 0, 0, 0.0
        parts = output.strip().split()
        if len(parts) < 2:
            return 0, 0, 0.0
        try:
            status = int(parts[0])
            duration = float(parts[1])
        except ValueError:
            return 0, 0, 0.0
        success = 1 if 200 <= status < 400 else 0
        return success, status, duration

    def render_metrics(self) -> str:
        now = time.time()
        gateway = self.current_gateway()
        wifi = self.collect_wifi()
        state_changed = False

        if self.previous_connected and not wifi.connected:
            self.disconnect_total += 1
            self.last_disconnect_ts = now
            self.append_event("disconnect", wifi, now, {"gateway": gateway})
            state_changed = True
        if wifi.connected and self.previous_bssid and wifi.bssid and self.previous_bssid != wifi.bssid:
            self.roam_total += 1
            self.last_roam_ts = now
            self.append_event("roam", wifi, now, {"gateway": gateway})
            state_changed = True

        self.previous_connected = wifi.connected
        self.previous_bssid = wifi.bssid if wifi.connected else ""

        if state_changed:
            self.save_state()

        gateway_ok, gateway_ms = self.ping(gateway)
        gateway_arp_ok = self.gateway_arp_reachable(gateway)
        internet_ok, internet_ms = self.ping(self.internet_ping_target)
        dns_ok, dns_duration = self.dns_check()
        http_ok, http_status, http_duration = self.http_check()

        if self.previous_gateway_ok and not gateway_ok:
            self.gateway_unreachable_total += 1
            self.last_gateway_unreachable_ts = now
            self.gateway_outage_active_since = now
            self.append_event(
                "gateway_unreachable",
                wifi,
                now,
                {
                    "gateway": gateway,
                    "gateway_ping_ms": gateway_ms,
                    "gateway_arp_reachable": gateway_arp_ok,
                    "reason": self.classify_gateway_reason(wifi, gateway_arp_ok),
                },
            )
            state_changed = True
        if not self.previous_gateway_ok and gateway_ok:
            outage_duration = max(0.0, now - self.gateway_outage_active_since) if self.gateway_outage_active_since else 0.0
            self.last_gateway_restored_ts = now
            self.last_gateway_outage_duration_seconds = outage_duration
            self.gateway_outage_active_since = 0.0
            self.append_event(
                "gateway_restored",
                wifi,
                now,
                {
                    "gateway": gateway,
                    "gateway_ping_ms": gateway_ms,
                    "gateway_arp_reachable": gateway_arp_ok,
                    "outage_duration_seconds": outage_duration,
                    "reason": "gateway_recovered",
                },
            )
            state_changed = True
        if self.previous_internet_ok and not internet_ok:
            self.internet_unreachable_total += 1
            self.last_internet_unreachable_ts = now
            self.internet_outage_active_since = now
            self.append_event(
                "internet_unreachable",
                wifi,
                now,
                {
                    "gateway": gateway,
                    "internet_target": self.internet_ping_target,
                    "internet_ping_ms": internet_ms,
                    "dns_check_host": self.dns_check_host,
                    "dns_ok": dns_ok,
                    "dns_duration_seconds": dns_duration,
                    "http_ok": http_ok,
                    "http_status": http_status,
                    "reason": self.classify_internet_reason(wifi, gateway_ok, dns_ok, http_ok),
                },
            )
            state_changed = True
        if not self.previous_internet_ok and internet_ok:
            outage_duration = max(0.0, now - self.internet_outage_active_since) if self.internet_outage_active_since else 0.0
            self.last_internet_restored_ts = now
            self.last_internet_outage_duration_seconds = outage_duration
            self.internet_outage_active_since = 0.0
            self.append_event(
                "internet_restored",
                wifi,
                now,
                {
                    "gateway": gateway,
                    "internet_target": self.internet_ping_target,
                    "internet_ping_ms": internet_ms,
                    "dns_check_host": self.dns_check_host,
                    "dns_ok": dns_ok,
                    "dns_duration_seconds": dns_duration,
                    "outage_duration_seconds": outage_duration,
                    "reason": "internet_recovered",
                },
            )
            state_changed = True

        self.previous_gateway_ok = bool(gateway_ok)
        self.previous_internet_ok = bool(internet_ok)

        if state_changed:
            self.save_state()

        channel = channel_from_frequency(wifi.frequency_mhz) if wifi.frequency_mhz else 0

        lines = [
            "# HELP wifi_exporter_scrape_success 1 when the scrape completed successfully.",
            "# TYPE wifi_exporter_scrape_success gauge",
            metric_line("wifi_exporter_scrape_success", 1),
            "# HELP wifi_connected 1 when the Wi-Fi interface is associated.",
            "# TYPE wifi_connected gauge",
            metric_line("wifi_connected", 1 if wifi.connected else 0, {"interface": self.interface}),
            "# HELP wifi_signal_dbm Current RSSI in dBm.",
            "# TYPE wifi_signal_dbm gauge",
            metric_line("wifi_signal_dbm", wifi.signal_dbm, {"interface": self.interface}),
            "# HELP wifi_frequency_mhz Current channel frequency in MHz.",
            "# TYPE wifi_frequency_mhz gauge",
            metric_line("wifi_frequency_mhz", wifi.frequency_mhz, {"interface": self.interface}),
            "# HELP wifi_channel Current Wi-Fi channel.",
            "# TYPE wifi_channel gauge",
            metric_line("wifi_channel", channel, {"interface": self.interface}),
            "# HELP wifi_tx_bitrate_mbps Current TX bitrate in Mbit/s.",
            "# TYPE wifi_tx_bitrate_mbps gauge",
            metric_line("wifi_tx_bitrate_mbps", wifi.tx_bitrate_mbps, {"interface": self.interface}),
            "# HELP wifi_rx_bitrate_mbps Current RX bitrate in Mbit/s.",
            "# TYPE wifi_rx_bitrate_mbps gauge",
            metric_line("wifi_rx_bitrate_mbps", wifi.rx_bitrate_mbps, {"interface": self.interface}),
            "# HELP wifi_connected_seconds How long the current association has been active.",
            "# TYPE wifi_connected_seconds gauge",
            metric_line("wifi_connected_seconds", wifi.connected_seconds, {"interface": self.interface}),
            "# HELP wifi_disconnect_total Number of observed disconnects since exporter start.",
            "# TYPE wifi_disconnect_total counter",
            metric_line("wifi_disconnect_total", self.disconnect_total, {"interface": self.interface}),
            "# HELP wifi_roam_total Number of observed AP/BSSID changes since exporter start.",
            "# TYPE wifi_roam_total counter",
            metric_line("wifi_roam_total", self.roam_total, {"interface": self.interface}),
            "# HELP wifi_last_disconnect_timestamp_seconds Unix timestamp of the last observed disconnect.",
            "# TYPE wifi_last_disconnect_timestamp_seconds gauge",
            metric_line("wifi_last_disconnect_timestamp_seconds", self.last_disconnect_ts, {"interface": self.interface}),
            "# HELP wifi_last_roam_timestamp_seconds Unix timestamp of the last observed roam.",
            "# TYPE wifi_last_roam_timestamp_seconds gauge",
            metric_line("wifi_last_roam_timestamp_seconds", self.last_roam_ts, {"interface": self.interface}),
            "# HELP wifi_gateway_unreachable_total Number of observed transitions from reachable to unreachable gateway.",
            "# TYPE wifi_gateway_unreachable_total counter",
            metric_line("wifi_gateway_unreachable_total", self.gateway_unreachable_total, {"interface": self.interface}),
            "# HELP wifi_last_gateway_unreachable_timestamp_seconds Unix timestamp of the last observed gateway unreachable event.",
            "# TYPE wifi_last_gateway_unreachable_timestamp_seconds gauge",
            metric_line("wifi_last_gateway_unreachable_timestamp_seconds", self.last_gateway_unreachable_ts, {"interface": self.interface}),
            "# HELP wifi_last_gateway_restored_timestamp_seconds Unix timestamp of the last observed gateway restored event.",
            "# TYPE wifi_last_gateway_restored_timestamp_seconds gauge",
            metric_line("wifi_last_gateway_restored_timestamp_seconds", self.last_gateway_restored_ts, {"interface": self.interface}),
            "# HELP wifi_last_gateway_outage_duration_seconds Duration of the last completed gateway outage.",
            "# TYPE wifi_last_gateway_outage_duration_seconds gauge",
            metric_line("wifi_last_gateway_outage_duration_seconds", self.last_gateway_outage_duration_seconds, {"interface": self.interface}),
            "# HELP wifi_gateway_outage_active_seconds Current duration of the active gateway outage, if any.",
            "# TYPE wifi_gateway_outage_active_seconds gauge",
            metric_line(
                "wifi_gateway_outage_active_seconds",
                max(0.0, now - self.gateway_outage_active_since) if self.gateway_outage_active_since else 0.0,
                {"interface": self.interface},
            ),
            "# HELP wifi_internet_unreachable_total Number of observed transitions from reachable to unreachable internet ping target.",
            "# TYPE wifi_internet_unreachable_total counter",
            metric_line("wifi_internet_unreachable_total", self.internet_unreachable_total, {"interface": self.interface, "target": self.internet_ping_target}),
            "# HELP wifi_last_internet_unreachable_timestamp_seconds Unix timestamp of the last observed internet unreachable event.",
            "# TYPE wifi_last_internet_unreachable_timestamp_seconds gauge",
            metric_line("wifi_last_internet_unreachable_timestamp_seconds", self.last_internet_unreachable_ts, {"interface": self.interface, "target": self.internet_ping_target}),
            "# HELP wifi_last_internet_restored_timestamp_seconds Unix timestamp of the last observed internet restored event.",
            "# TYPE wifi_last_internet_restored_timestamp_seconds gauge",
            metric_line("wifi_last_internet_restored_timestamp_seconds", self.last_internet_restored_ts, {"interface": self.interface, "target": self.internet_ping_target}),
            "# HELP wifi_last_internet_outage_duration_seconds Duration of the last completed internet outage.",
            "# TYPE wifi_last_internet_outage_duration_seconds gauge",
            metric_line("wifi_last_internet_outage_duration_seconds", self.last_internet_outage_duration_seconds, {"interface": self.interface, "target": self.internet_ping_target}),
            "# HELP wifi_internet_outage_active_seconds Current duration of the active internet outage, if any.",
            "# TYPE wifi_internet_outage_active_seconds gauge",
            metric_line(
                "wifi_internet_outage_active_seconds",
                max(0.0, now - self.internet_outage_active_since) if self.internet_outage_active_since else 0.0,
                {"interface": self.interface, "target": self.internet_ping_target},
            ),
            "# HELP wifi_event_log_info Static info about the persistent event log location.",
            "# TYPE wifi_event_log_info gauge",
            metric_line("wifi_event_log_info", 1, {"interface": self.interface, "path": self.event_log_file}),
            "# HELP wifi_gateway_arp_reachable 1 when the gateway currently resolves in ARP/neighbor cache.",
            "# TYPE wifi_gateway_arp_reachable gauge",
            metric_line("wifi_gateway_arp_reachable", gateway_arp_ok, {"interface": self.interface}),
            "# HELP wifi_gateway_reachable 1 when the default gateway responds to ICMP.",
            "# TYPE wifi_gateway_reachable gauge",
            metric_line("wifi_gateway_reachable", gateway_ok, {"interface": self.interface}),
            "# HELP wifi_gateway_ping_ms ICMP RTT to the default gateway in milliseconds.",
            "# TYPE wifi_gateway_ping_ms gauge",
            metric_line("wifi_gateway_ping_ms", gateway_ms, {"interface": self.interface}),
            "# HELP wifi_dns_check_success 1 when the configured DNS hostname resolves successfully.",
            "# TYPE wifi_dns_check_success gauge",
            metric_line("wifi_dns_check_success", dns_ok, {"interface": self.interface, "host": self.dns_check_host}),
            "# HELP wifi_dns_check_duration_seconds DNS resolution duration for the configured hostname.",
            "# TYPE wifi_dns_check_duration_seconds gauge",
            metric_line("wifi_dns_check_duration_seconds", dns_duration, {"interface": self.interface, "host": self.dns_check_host}),
            "# HELP wifi_internet_ping_reachable 1 when the internet ping target responds to ICMP.",
            "# TYPE wifi_internet_ping_reachable gauge",
            metric_line("wifi_internet_ping_reachable", internet_ok, {"interface": self.interface, "target": self.internet_ping_target}),
            "# HELP wifi_internet_ping_ms ICMP RTT to the internet ping target in milliseconds.",
            "# TYPE wifi_internet_ping_ms gauge",
            metric_line("wifi_internet_ping_ms", internet_ms, {"interface": self.interface, "target": self.internet_ping_target}),
            "# HELP wifi_http_check_success 1 when the configured HTTP check succeeds.",
            "# TYPE wifi_http_check_success gauge",
            metric_line("wifi_http_check_success", http_ok, {"interface": self.interface, "target": self.http_check_url}),
            "# HELP wifi_http_status_code Last HTTP response status code.",
            "# TYPE wifi_http_status_code gauge",
            metric_line("wifi_http_status_code", http_status, {"interface": self.interface, "target": self.http_check_url}),
            "# HELP wifi_http_duration_seconds Last HTTP probe duration.",
            "# TYPE wifi_http_duration_seconds gauge",
            metric_line("wifi_http_duration_seconds", http_duration, {"interface": self.interface, "target": self.http_check_url}),
        ]

        if wifi.connected:
            lines.extend(
                [
                    "# HELP wifi_association_info Static association metadata.",
                    "# TYPE wifi_association_info gauge",
                    metric_line(
                        "wifi_association_info",
                        1,
                        {
                            "interface": self.interface,
                            "ssid": wifi.ssid,
                            "bssid": wifi.bssid,
                        },
                    ),
                ]
            )

        if gateway:
            lines.extend(
                [
                    "# HELP wifi_default_gateway_info Default gateway metadata.",
                    "# TYPE wifi_default_gateway_info gauge",
                    metric_line(
                        "wifi_default_gateway_info",
                        1,
                        {"interface": self.interface, "gateway": gateway},
                    ),
                ]
            )

        if self.recent_events:
            lines.extend(
                [
                    "# HELP wifi_recent_event_timestamp_seconds Recent Wi-Fi related events with context labels.",
                    "# TYPE wifi_recent_event_timestamp_seconds gauge",
                ]
            )
            recent = list(reversed(self.recent_events))
            for index, event in enumerate(recent, start=1):
                labels = {
                    "slot": str(index),
                    "event": str(event.get("event", "")),
                    "details_available": str(event.get("details_available", "false")),
                    "interface": str(event.get("interface", "")),
                    "ssid": str(event.get("ssid", "")),
                    "bssid": str(event.get("bssid", "")),
                    "gateway": str(event.get("gateway", "")),
                    "internet_target": str(event.get("internet_target", "")),
                    "dns_check_host": str(event.get("dns_check_host", "")),
                    "dns_ok": str(event.get("dns_ok", "")),
                    "http_ok": str(event.get("http_ok", "")),
                    "reason": str(event.get("reason", "")),
                    "outage_duration_seconds": str(event.get("outage_duration_seconds", "")),
                    "gateway_arp_reachable": str(event.get("gateway_arp_reachable", "")),
                    "signal_dbm": str(event.get("signal_dbm", "")),
                    "frequency_mhz": str(event.get("frequency_mhz", "")),
                    "tx_bitrate_mbps": str(event.get("tx_bitrate_mbps", "")),
                    "rx_bitrate_mbps": str(event.get("rx_bitrate_mbps", "")),
                    "ts_iso": str(event.get("ts_iso", "")),
                }
                lines.append(
                    metric_line(
                        "wifi_recent_event_timestamp_seconds",
                        float(event.get("ts", 0)),
                        labels,
                    )
                )

        return "\n".join(lines) + "\n"


COLLECTOR = WifiCollector()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in ("/metrics", "/"):
            self.send_response(404)
            self.end_headers()
            return

        body = COLLECTOR.render_metrics().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        return


if __name__ == "__main__":
    port = int(os.getenv("EXPORTER_PORT", "9721"))
    server = HTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()
