import os
import re
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer


PATTERNS = {
    "io_error": re.compile(r"\b(i/o error|blk_update_request|buffer i/o error)\b", re.IGNORECASE),
    "ext4_error": re.compile(r"\bext4-fs error\b", re.IGNORECASE),
    "mmc_error": re.compile(r"\bmmc\d*.*(error|timeout|crc|retry|failed)\b", re.IGNORECASE),
    "usb_storage_error": re.compile(
        r"\b("
        r"reset .*usb|reset (high|super)speed usb device|"
        r"uas.*(error|abort|reset|failed|timeout)|"
        r"usb-storage.*(error|abort|reset|failed|timeout)|"
        r"device descriptor read.*(error|failed|-71)|"
        r"usb .*disconnect|usb .*unable to enumerate"
        r")\b",
        re.IGNORECASE,
    ),
}


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


def metric_line(name: str, value: float, labels: dict[str, str] | None = None) -> str:
    if labels:
        rendered = ",".join(
            f'{key}="{str(val).replace("\\", "\\\\").replace(chr(34), "\\\"")}"'
            for key, val in sorted(labels.items())
        )
        return f"{name}{{{rendered}}} {value}"
    return f"{name} {value}"


def read_dmesg() -> str:
    code, output = shell(["dmesg", "--color=never"], timeout=10)
    if code != 0:
        return ""
    return output


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in ("/", "/metrics"):
            self.send_response(404)
            self.end_headers()
            return

        dmesg_output = read_dmesg()
        scrape_success = 1 if dmesg_output else 0
        counts = {category: 0 for category in PATTERNS}

        if dmesg_output:
            for line in dmesg_output.splitlines():
                for category, pattern in PATTERNS.items():
                    if pattern.search(line):
                        counts[category] += 1

        total_matches = sum(counts.values())
        lines = [
            "# HELP kernel_log_exporter_scrape_success 1 when dmesg could be read successfully.",
            "# TYPE kernel_log_exporter_scrape_success gauge",
            metric_line("kernel_log_exporter_scrape_success", scrape_success),
            "# HELP kernel_storage_error_lines_total Count of matching kernel log lines since boot.",
            "# TYPE kernel_storage_error_lines_total gauge",
        ]
        for category, count in counts.items():
            lines.append(metric_line("kernel_storage_error_lines_total", count, {"category": category}))

        lines.extend(
            [
                "# HELP kernel_storage_error_present 1 when at least one matching storage/kernel error was found since boot.",
                "# TYPE kernel_storage_error_present gauge",
                metric_line("kernel_storage_error_present", 1 if total_matches > 0 else 0),
                "# HELP kernel_storage_error_total Sum of all matching kernel storage error lines since boot.",
                "# TYPE kernel_storage_error_total gauge",
                metric_line("kernel_storage_error_total", total_matches),
            ]
        )

        body = ("\n".join(lines) + "\n").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        return


if __name__ == "__main__":
    port = int(os.getenv("EXPORTER_PORT", "9722"))
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
