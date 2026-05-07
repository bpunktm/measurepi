import os
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import yaml


def shell(command: list[str], timeout: int = 12) -> tuple[int, str]:
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
    if completed.returncode == 0:
        return completed.returncode, completed.stdout or ""
    return completed.returncode, (completed.stderr or "") or (completed.stdout or "")


def escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def metric_line(name: str, value: float, labels: dict[str, str] | None = None) -> str:
    if labels:
        rendered = ",".join(
            f'{key}="{escape_label_value(str(val))}"'
            for key, val in sorted(labels.items())
        )
        return f"{name}{{{rendered}}} {value}"
    return f"{name} {value}"


def info_metric(name: str, labels: dict[str, str]) -> str:
    return metric_line(name, 1, labels)


class UnifiApCollector:
    def __init__(self) -> None:
        self.community = os.getenv("SNMP_COMMUNITY", "monitoring")
        self.targets_file = os.getenv("AP_TARGETS_FILE", "/etc/measurepi/ap-targets.yml")
        self.refresh_interval = int(os.getenv("REFRESH_INTERVAL_SECONDS", "60"))
        self._lock = threading.Lock()
        self._cached_metrics = ""
        self._last_refresh = 0.0
        self._refresh_error = ""

    def load_targets(self) -> list[dict[str, object]]:
        try:
            with open(self.targets_file, "r", encoding="utf-8") as handle:
                payload = yaml.safe_load(handle) or []
        except FileNotFoundError:
            return []

        normalized: list[dict[str, object]] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            targets = entry.get("targets") or []
            if not isinstance(targets, list):
                continue
            labels = entry.get("labels") or {}
            if not isinstance(labels, dict):
                labels = {}
            for target in targets:
                normalized.append({"target": str(target), "labels": {str(k): str(v) for k, v in labels.items()}})
        return normalized

    def snmpget(self, target: str, oid: str) -> str:
        code, output = shell(
            ["snmpget", "-v2c", "-c", self.community, "-Oqv", target, oid],
            timeout=8,
        )
        if code != 0:
            return ""
        return output.strip()

    def snmpwalk(self, target: str, oid: str) -> list[str]:
        code, output = shell(
            ["snmpwalk", "-v2c", "-c", self.community, "-On", target, oid],
            timeout=15,
        )
        if code != 0:
            return []
        return [line.strip() for line in output.splitlines() if line.strip()]

    def parse_counter(self, raw_value: str) -> float:
        cleaned = re.sub(r"^[A-Za-z0-9\-]+\s*:\s*", "", raw_value.strip())
        match = re.search(r"(-?\d+(?:\.\d+)?)", cleaned)
        if match:
            return float(match.group(1))
        match = re.search(r"\((\d+)\)", raw_value)
        return float(match.group(1)) if match else 0.0

    def parse_text(self, raw_value: str) -> str:
        cleaned = re.sub(r"^[A-Z\-]+\s*:\s*", "", raw_value.strip())
        return cleaned.strip().strip('"')

    def parse_timeticks_seconds(self, raw_value: str) -> float:
        match = re.search(r"\((\d+)\)", raw_value)
        if match:
            return float(match.group(1)) / 100.0
        match = re.search(r"(?:(\d+)\s+days?,\s+)?(\d+):(\d+):(\d+)(?:\.(\d+))?", raw_value)
        if match:
            days = int(match.group(1) or 0)
            hours = int(match.group(2))
            minutes = int(match.group(3))
            seconds = int(match.group(4))
            centis = int((match.group(5) or "0")[:2].ljust(2, "0"))
            return days * 86400.0 + hours * 3600.0 + minutes * 60.0 + seconds + centis / 100.0
        return 0.0

    def parse_walk(self, lines: list[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for line in lines:
            match = re.match(r"\.([0-9\.]+)\.([0-9]+(?:\.[0-9]+)*)\s*=\s*(.*)", line)
            if not match:
                continue
            result[match.group(2)] = match.group(3).strip()
        return result

    def band_from_radio_type(self, radio_type: str) -> str:
        mapping = {
            "ng": "2.4",
            "na": "5",
            "be": "6",
        }
        return mapping.get(radio_type, "unknown")

    def scrape_ap(self, target: str, static_labels: dict[str, str]) -> list[str]:
        lines: list[str] = []
        sys_name = self.parse_text(self.snmpget(target, ".1.3.6.1.2.1.1.5.0"))
        sys_descr = self.parse_text(self.snmpget(target, ".1.3.6.1.2.1.1.1.0"))
        sys_uptime = self.parse_timeticks_seconds(self.snmpget(target, ".1.3.6.1.2.1.1.3.0"))
        model = self.parse_text(self.snmpget(target, ".1.3.6.1.4.1.41112.1.6.3.3.0"))
        firmware = self.parse_text(self.snmpget(target, ".1.3.6.1.4.1.41112.1.6.3.6.0"))
        zone = static_labels.get("zone", "unknown")
        ap_name = sys_name or static_labels.get("device", target)
        ap_type = model or (sys_descr.split(" ", 1)[0] if sys_descr else "unknown")
        base_labels = {
            "exported_instance": target,
            "zone": zone,
            "ap_name": ap_name,
            "ap_type": ap_type,
            "role": static_labels.get("role", "ap"),
            "vendor": static_labels.get("vendor", "ubiquiti"),
        }

        lines.append(metric_line("unifi_ap_scrape_success", 1 if sys_name else 0, base_labels))
        if sys_name:
            lines.append(
                info_metric(
                    "unifi_ap_info",
                    {
                        **base_labels,
                        "firmware": firmware or "unknown",
                        "model": model or "unknown",
                        "sys_descr": sys_descr or "unknown",
                    },
                )
            )
        lines.append(metric_line("unifi_ap_uptime_seconds", sys_uptime, base_labels))

        cpu_load = self.parse_walk(self.snmpwalk(target, ".1.3.6.1.2.1.25.3.3.1.2"))
        cpu_values: list[float] = []
        for cpu_index, raw_value in sorted(cpu_load.items()):
            value = self.parse_counter(raw_value)
            cpu_values.append(value)
            lines.append(metric_line("unifi_ap_cpu_load_percent", value, {**base_labels, "cpu": cpu_index}))
        if cpu_values:
            lines.append(metric_line("unifi_ap_cpu_load_percent_avg", sum(cpu_values) / len(cpu_values), base_labels))

        memory_oids = {
            "total": ".1.3.6.1.4.1.2021.4.5.0",
            "avail": ".1.3.6.1.4.1.2021.4.6.0",
            "shared": ".1.3.6.1.4.1.2021.4.13.0",
            "buffer": ".1.3.6.1.4.1.2021.4.14.0",
            "cached": ".1.3.6.1.4.1.2021.4.15.0",
        }
        for mem_type, oid in memory_oids.items():
            lines.append(
                metric_line(
                    "unifi_ap_memory_kilobytes",
                    self.parse_counter(self.snmpget(target, oid)),
                    {**base_labels, "memory": mem_type},
                )
            )

        load_oids = {
            "1m": ".1.3.6.1.4.1.2021.10.1.3.1",
            "5m": ".1.3.6.1.4.1.2021.10.1.3.2",
            "15m": ".1.3.6.1.4.1.2021.10.1.3.3",
        }
        for window, oid in load_oids.items():
            lines.append(
                metric_line(
                    "unifi_ap_load_average",
                    self.parse_counter(self.snmpget(target, oid)),
                    {**base_labels, "window": window},
                )
            )

        if_name = {k: self.parse_text(v) for k, v in self.parse_walk(self.snmpwalk(target, ".1.3.6.1.2.1.31.1.1.1.1")).items()}
        if_descr = {k: self.parse_text(v) for k, v in self.parse_walk(self.snmpwalk(target, ".1.3.6.1.2.1.2.2.1.2")).items()}
        if_oper = self.parse_walk(self.snmpwalk(target, ".1.3.6.1.2.1.2.2.1.8"))
        if_admin = self.parse_walk(self.snmpwalk(target, ".1.3.6.1.2.1.2.2.1.7"))
        if_in_octets = self.parse_walk(self.snmpwalk(target, ".1.3.6.1.2.1.31.1.1.1.6"))
        if_out_octets = self.parse_walk(self.snmpwalk(target, ".1.3.6.1.2.1.31.1.1.1.10"))
        if_in_errors = self.parse_walk(self.snmpwalk(target, ".1.3.6.1.2.1.2.2.1.14"))
        if_out_errors = self.parse_walk(self.snmpwalk(target, ".1.3.6.1.2.1.2.2.1.20"))

        all_if_indices = sorted(set(if_name) | set(if_descr) | set(if_oper) | set(if_admin))
        for if_index in all_if_indices:
            labels = {
                **base_labels,
                "if_index": if_index,
                "if_name": if_name.get(if_index, f"if{if_index}"),
                "if_descr": if_descr.get(if_index, if_name.get(if_index, f"if{if_index}")),
            }
            lines.append(metric_line("unifi_ap_interface_oper_status", self.parse_counter(if_oper.get(if_index, "0")), labels))
            lines.append(metric_line("unifi_ap_interface_admin_status", self.parse_counter(if_admin.get(if_index, "0")), labels))
            lines.append(metric_line("unifi_ap_interface_in_octets_total", self.parse_counter(if_in_octets.get(if_index, "0")), labels))
            lines.append(metric_line("unifi_ap_interface_out_octets_total", self.parse_counter(if_out_octets.get(if_index, "0")), labels))
            lines.append(metric_line("unifi_ap_interface_in_errors_total", self.parse_counter(if_in_errors.get(if_index, "0")), labels))
            lines.append(metric_line("unifi_ap_interface_out_errors_total", self.parse_counter(if_out_errors.get(if_index, "0")), labels))

        radio_names = {k: self.parse_text(v) for k, v in self.parse_walk(self.snmpwalk(target, ".1.3.6.1.4.1.41112.1.6.1.1.1.2")).items()}
        radio_types = {k: self.parse_text(v) for k, v in self.parse_walk(self.snmpwalk(target, ".1.3.6.1.4.1.41112.1.6.1.1.1.3")).items()}
        for radio_index, radio_name in sorted(radio_names.items()):
            radio_type = radio_types.get(radio_index, "unknown")
            lines.append(
                info_metric(
                    "unifi_ap_radio_info",
                    {
                        **base_labels,
                        "radio_index": radio_index,
                        "radio_name": radio_name,
                        "radio_type": radio_type,
                        "band": self.band_from_radio_type(radio_type),
                    },
                )
            )

        ssid_names = {k: self.parse_text(v) for k, v in self.parse_walk(self.snmpwalk(target, ".1.3.6.1.4.1.41112.1.6.1.2.1.6")).items()}
        vap_names = {k: self.parse_text(v) for k, v in self.parse_walk(self.snmpwalk(target, ".1.3.6.1.4.1.41112.1.6.1.2.1.7")).items()}
        ssid_clients = self.parse_walk(self.snmpwalk(target, ".1.3.6.1.4.1.41112.1.6.1.2.1.8"))
        ssid_radio_type = {k: self.parse_text(v) for k, v in self.parse_walk(self.snmpwalk(target, ".1.3.6.1.4.1.41112.1.6.1.2.1.9")).items()}
        ssid_role = {k: self.parse_text(v) for k, v in self.parse_walk(self.snmpwalk(target, ".1.3.6.1.4.1.41112.1.6.1.2.1.23")).items()}
        ssid_enabled = self.parse_walk(self.snmpwalk(target, ".1.3.6.1.4.1.41112.1.6.1.2.1.22"))
        all_ssid_indices = sorted(set(ssid_names) | set(vap_names) | set(ssid_clients))
        for ssid_index in all_ssid_indices:
            radio_type = ssid_radio_type.get(ssid_index, "unknown")
            labels = {
                **base_labels,
                "ssid_index": ssid_index,
                "ssid": ssid_names.get(ssid_index, f"ssid-{ssid_index}"),
                "vap": vap_names.get(ssid_index, ""),
                "radio_type": radio_type,
                "band": self.band_from_radio_type(radio_type),
                "network_role": ssid_role.get(ssid_index, "unknown"),
            }
            lines.append(info_metric("unifi_ap_ssid_info", labels))
            lines.append(metric_line("unifi_ap_ssid_enabled", self.parse_counter(ssid_enabled.get(ssid_index, "0")), labels))
            lines.append(metric_line("unifi_ap_ssid_clients", self.parse_counter(ssid_clients.get(ssid_index, "0")), labels))

        return lines

    def render_metrics(self) -> str:
        lines = [
            "# HELP unifi_ap_scrape_success 1 when AP SNMP collection succeeded.",
            "# TYPE unifi_ap_scrape_success gauge",
            "# HELP unifi_ap_info AP inventory information metric.",
            "# TYPE unifi_ap_info gauge",
            "# HELP unifi_ap_uptime_seconds SNMP agent uptime in seconds.",
            "# TYPE unifi_ap_uptime_seconds gauge",
            "# HELP unifi_ap_cpu_load_percent CPU utilization per processor in percent.",
            "# TYPE unifi_ap_cpu_load_percent gauge",
            "# HELP unifi_ap_cpu_load_percent_avg Average CPU utilization across processors in percent.",
            "# TYPE unifi_ap_cpu_load_percent_avg gauge",
            "# HELP unifi_ap_memory_kilobytes AP memory values in kilobytes.",
            "# TYPE unifi_ap_memory_kilobytes gauge",
            "# HELP unifi_ap_load_average System load average.",
            "# TYPE unifi_ap_load_average gauge",
            "# HELP unifi_ap_interface_oper_status Interface operational status.",
            "# TYPE unifi_ap_interface_oper_status gauge",
            "# HELP unifi_ap_interface_admin_status Interface administrative status.",
            "# TYPE unifi_ap_interface_admin_status gauge",
            "# HELP unifi_ap_interface_in_octets_total Inbound interface octets.",
            "# TYPE unifi_ap_interface_in_octets_total counter",
            "# HELP unifi_ap_interface_out_octets_total Outbound interface octets.",
            "# TYPE unifi_ap_interface_out_octets_total counter",
            "# HELP unifi_ap_interface_in_errors_total Inbound interface errors.",
            "# TYPE unifi_ap_interface_in_errors_total counter",
            "# HELP unifi_ap_interface_out_errors_total Outbound interface errors.",
            "# TYPE unifi_ap_interface_out_errors_total counter",
            "# HELP unifi_ap_radio_info Radio inventory information metric.",
            "# TYPE unifi_ap_radio_info gauge",
            "# HELP unifi_ap_ssid_info SSID and VAP inventory information metric.",
            "# TYPE unifi_ap_ssid_info gauge",
            "# HELP unifi_ap_ssid_enabled 1 when the SSID is enabled on the AP.",
            "# TYPE unifi_ap_ssid_enabled gauge",
            "# HELP unifi_ap_ssid_clients Associated clients per SSID/VAP.",
            "# TYPE unifi_ap_ssid_clients gauge",
            "# HELP unifi_ap_exporter_last_refresh_timestamp_seconds Unix timestamp of the last successful background refresh.",
            "# TYPE unifi_ap_exporter_last_refresh_timestamp_seconds gauge",
        ]

        for entry in self.load_targets():
            target = str(entry.get("target", ""))
            labels = entry.get("labels", {})
            if not target or not isinstance(labels, dict):
                continue
            lines.extend(self.scrape_ap(target, labels))

        lines.append(metric_line("unifi_ap_exporter_last_refresh_timestamp_seconds", time.time()))
        return "\n".join(lines) + "\n"

    def refresh_cache(self) -> None:
        try:
            metrics = self.render_metrics()
        except Exception as exc:  # pragma: no cover - defensive exporter path
            with self._lock:
                self._refresh_error = str(exc)
            return

        with self._lock:
            self._cached_metrics = metrics
            self._last_refresh = time.time()
            self._refresh_error = ""

    def cached_metrics(self) -> str:
        with self._lock:
            if self._cached_metrics:
                return self._cached_metrics

        self.refresh_cache()
        with self._lock:
            if self._cached_metrics:
                return self._cached_metrics

            fallback = [
                "# HELP unifi_ap_exporter_last_refresh_timestamp_seconds Unix timestamp of the last successful background refresh.",
                "# TYPE unifi_ap_exporter_last_refresh_timestamp_seconds gauge",
                metric_line("unifi_ap_exporter_last_refresh_timestamp_seconds", self._last_refresh or 0),
            ]
            if self._refresh_error:
                fallback.append(f"# refresh_error {self._refresh_error}")
            return "\n".join(fallback) + "\n"

    def background_refresh_loop(self) -> None:
        while True:
            self.refresh_cache()
            time.sleep(max(5, self.refresh_interval))


COLLECTOR = UnifiApCollector()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in ("/", "/metrics"):
            self.send_response(404)
            self.end_headers()
            return

        body = COLLECTOR.cached_metrics().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            return

    def log_message(self, fmt: str, *args) -> None:
        return


if __name__ == "__main__":
    port = int(os.getenv("EXPORTER_PORT", "9726"))
    threading.Thread(target=COLLECTOR.background_refresh_loop, daemon=True).start()
    server = HTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()
