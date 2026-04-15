import os
import subprocess
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, HTTPServer


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


class TsharkCollector:
    def __init__(self) -> None:
        self.interface = os.getenv("WIFI_INTERFACE", "wlan0")
        self.last_packet_ts = 0.0
        self.scrape_success = 0
        self.counters: dict[str, float] = defaultdict(float)
        self.last_seen: dict[str, float] = defaultdict(float)
        self.lock = threading.Lock()
        self.process: subprocess.Popen[str] | None = None

    def start(self) -> None:
        cmd = [
            "tshark",
            "-l",
            "-n",
            "-Q",
            "-i",
            self.interface,
            "-T",
            "fields",
            "-E",
            "separator=\t",
            "-E",
            "header=n",
            "-e",
            "frame.time_epoch",
            "-e",
            "_ws.col.Protocol",
            "-e",
            "dns.flags.response",
            "-e",
            "bootp.option.dhcp",
            "-e",
            "arp.opcode",
            "-e",
            "icmp.type",
            "-e",
            "tcp.analysis.retransmission",
        ]
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        thread = threading.Thread(target=self._consume, daemon=True)
        thread.start()

    def _bump(self, key: str, ts: float) -> None:
        self.counters[key] += 1
        self.last_seen[key] = ts

    def _consume(self) -> None:
        if not self.process or not self.process.stdout:
            return
        for raw_line in self.process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split("\t")
            while len(parts) < 7:
                parts.append("")

            try:
                ts = float(parts[0])
            except ValueError:
                ts = time.time()

            protocol = parts[1].upper()
            dns_response = parts[2]
            dhcp_type = parts[3]
            arp_opcode = parts[4]
            icmp_type = parts[5]
            tcp_retrans = parts[6]

            with self.lock:
                self.scrape_success = 1
                self.last_packet_ts = ts

                if protocol == "ARP":
                    if arp_opcode == "1":
                        self._bump("arp_request_total", ts)
                    elif arp_opcode == "2":
                        self._bump("arp_reply_total", ts)
                    else:
                        self._bump("arp_other_total", ts)

                if protocol == "DNS":
                    if dns_response == "0":
                        self._bump("dns_query_total", ts)
                    elif dns_response == "1":
                        self._bump("dns_response_total", ts)

                if protocol in ("DHCP", "BOOTP"):
                    self._bump("dhcp_packet_total", ts)
                    if dhcp_type:
                        self._bump(f"dhcp_type_{dhcp_type}_total", ts)

                if protocol == "ICMP":
                    if icmp_type == "8":
                        self._bump("icmp_echo_request_total", ts)
                    elif icmp_type == "0":
                        self._bump("icmp_echo_reply_total", ts)
                    else:
                        self._bump("icmp_other_total", ts)

                if tcp_retrans:
                    self._bump("tcp_retransmission_total", ts)

    def render_metrics(self) -> str:
        with self.lock:
            counters = dict(self.counters)
            last_seen = dict(self.last_seen)
            scrape_success = self.scrape_success
            last_packet_ts = self.last_packet_ts

        lines = [
            "# HELP tshark_exporter_capture_success 1 when tshark capture is running.",
            "# TYPE tshark_exporter_capture_success gauge",
            metric_line("tshark_exporter_capture_success", scrape_success, {"interface": self.interface}),
            "# HELP tshark_last_packet_timestamp_seconds Last observed packet timestamp.",
            "# TYPE tshark_last_packet_timestamp_seconds gauge",
            metric_line("tshark_last_packet_timestamp_seconds", last_packet_ts, {"interface": self.interface}),
        ]

        for key in sorted(counters):
            metric_name = f"tshark_{key}"
            lines.extend(
                [
                    f"# HELP {metric_name} Counter derived from tshark live capture.",
                    f"# TYPE {metric_name} counter",
                    metric_line(metric_name, counters[key], {"interface": self.interface}),
                ]
            )

        for key in sorted(last_seen):
            metric_name = f"tshark_{key.removesuffix('_total')}_last_seen_timestamp_seconds"
            lines.extend(
                [
                    f"# HELP {metric_name} Timestamp of the last observed matching tshark event.",
                    f"# TYPE {metric_name} gauge",
                    metric_line(metric_name, last_seen[key], {"interface": self.interface}),
                ]
            )

        return "\n".join(lines) + "\n"


COLLECTOR = TsharkCollector()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in ("/", "/metrics"):
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
    COLLECTOR.start()
    port = int(os.getenv("EXPORTER_PORT", "9723"))
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
