import os
import platform
import re
import socket
import subprocess
from ipaddress import IPv4Address, AddressValueError
from typing import Optional, Union


TCP_TIMEOUT_SECONDS = 1.5
PING_TIMEOUT_MS = 1500
PING_PROCESS_TIMEOUT_SECONDS = 3
CHECK_WORKERS = min(16, max(4, (os.cpu_count() or 1) * 2))
MAX_SCAN_ADDRESSES = 1024


def validate_ipv4_range(
    start_text: str,
    end_text: str,
    maximum: int = MAX_SCAN_ADDRESSES,
):
    """Validate an inclusive IPv4 range and return canonical address strings."""
    try:
        start = IPv4Address(start_text.strip())
        end = IPv4Address(end_text.strip())
    except AddressValueError as exc:
        raise ValueError("Start IP and End IP must be valid IPv4 addresses") from exc

    if int(end) < int(start):
        raise ValueError("End IP must not be lower than Start IP")

    count = int(end) - int(start) + 1
    if count > maximum:
        raise ValueError(f"IP range is too large ({count}); maximum is {maximum}")

    return [str(IPv4Address(value)) for value in range(int(start), int(end) + 1)]


def normalize_target_key(host: str, port: int):
    """Return a stable key used to detect duplicate Host/IP + Port targets."""
    normalized_host = host.strip().lower()
    try:
        normalized_host = str(IPv4Address(normalized_host))
    except AddressValueError:
        pass
    return normalized_host, int(port)


class IPv4ScanPlan:
    """Track bounded scan scheduling and stop issuing work after cancellation."""

    def __init__(self, addresses):
        self.addresses = tuple(addresses)
        self.position = 0
        self.cancelled = False

    @classmethod
    def from_range(cls, start_text: str, end_text: str):
        return cls(validate_ipv4_range(start_text, end_text))

    @property
    def total(self) -> int:
        return len(self.addresses)

    @property
    def exhausted(self) -> bool:
        return self.position >= self.total

    def take(self, count: int):
        if self.cancelled or count <= 0:
            return []
        end = min(self.position + count, self.total)
        batch = list(self.addresses[self.position:end])
        self.position = end
        return batch

    def cancel(self):
        self.cancelled = True


def parse_ping_latency(output: Union[str, bytes]) -> Optional[str]:
    """Extract a latency token without depending on localized ping wording."""
    if isinstance(output, bytes):
        # Windows keeps digits/operators/unit in ASCII even when the
        # surrounding response uses a localized code page (including Thai).
        output = output.decode("ascii", errors="ignore")

    match = re.search(r"([=<])\s*(\d+(?:[.,]\d+)?)\s*ms\b", output, re.IGNORECASE)
    if not match:
        return None

    operator, value_text = match.groups()
    try:
        value = float(value_text.replace(",", "."))
    except ValueError:
        return None

    formatted = str(int(value)) if value.is_integer() else f"{value:g}"
    return f"<{formatted} ms" if operator == "<" else f"{formatted} ms"


def ping_host(host: str) -> str:
    """Ping once; use the return code for success and output only for latency."""
    is_windows = platform.system().lower().startswith("win")
    if is_windows:
        command = ["ping", "-n", "1", "-w", str(PING_TIMEOUT_MS), host]
    else:
        command = ["ping", "-c", "1", "-W", "2", host]

    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=PING_PROCESS_TIMEOUT_SECONDS,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if is_windows else 0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "Timeout"

    if completed.returncode != 0:
        return "Timeout"
    return parse_ping_latency(completed.stdout) or "Online"


def check_single_host_port(host: str, port: int) -> bool:
    """Check TCP availability independently using the existing 1.5s timeout."""
    try:
        with socket.create_connection((host, port), timeout=TCP_TIMEOUT_SECONDS):
            pass
        return True
    except (OSError, ValueError):
        return False


def check_target(host: str, port: int):
    """Return independent Ping display text and TCP availability."""
    return ping_host(host), check_single_host_port(host, port)
