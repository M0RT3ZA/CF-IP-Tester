from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from src.core.cdn_presets import detect_cdn_for_ip


class TargetType(StrEnum):
    IPV4 = "IPv4"
    IPV6 = "IPv6"
    DOMAIN = "Domain"


class ProbeStatus(StrEnum):
    SUCCESS = "SUCCESS"
    TIMEOUT = "TIMEOUT"
    TLS_ERROR = "TLS_ERROR"
    HTTP_ERROR = "HTTP_ERROR"
    BLOCKED = "BLOCKED"
    DNS_ERROR = "DNS_ERROR"
    UNREACHABLE = "UNREACHABLE"
    FAILED = "FAILED"


# RFC 1035 and RFC 1123 compliant hostname validator
_HOSTNAME_REGEX = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$"
)


@dataclass(frozen=True, slots=True)
class Target:
    raw_input: str
    target_type: TargetType
    host: str
    source_file: str = ""
    cdn_name: str = ""

    @classmethod
    def from_string(cls, raw: str, source_file: str = "", cdn_name: str = "") -> Target | None:
        cleaned = raw.strip()
        if not cleaned or cleaned.startswith("#"):
            return None

        # Extract inline remarks if present (e.g., "1.1.1.1 # Cloudflare" or "1.1.1.1 # Fastly")
        inline_remark = ""
        if "#" in cleaned:
            parts = cleaned.split("#", 1)
            cleaned = parts[0].strip()
            inline_remark = parts[1].strip()

        # Strip brackets commonly found in IPv6 URI notations
        cleaned = cleaned.strip("[]")

        # Strip standard port specifications if present (e.g., example.com:443 or 1.1.1.1:443)
        if ":" in cleaned and not cls._is_raw_ipv6(cleaned):
            cleaned = cleaned.rsplit(":", 1)[0].strip()

        try:
            ip = ipaddress.ip_address(cleaned)
            target_type = TargetType.IPV4 if ip.version == 4 else TargetType.IPV6
            # Use compressed canonical format for IPv6 to ensure deterministic deduplication
            normalized_host = ip.compressed if ip.version == 6 else str(ip)
            resolved_cdn = cdn_name or detect_cdn_for_ip(normalized_host, source_file or inline_remark)
            return cls(
                raw_input=raw.strip(),
                target_type=target_type,
                host=normalized_host,
                source_file=source_file,
                cdn_name=resolved_cdn,
            )
        except ValueError:
            pass

        # Check if it satisfies standard FQDN criteria
        lower_host = cleaned.lower()
        if _HOSTNAME_REGEX.match(lower_host):
            resolved_cdn = cdn_name or detect_cdn_for_ip(lower_host, source_file or inline_remark)
            return cls(
                raw_input=raw.strip(),
                target_type=TargetType.DOMAIN,
                host=lower_host,
                source_file=source_file,
                cdn_name=resolved_cdn,
            )

        return None

    @staticmethod
    def _is_raw_ipv6(val: str) -> bool:
        # IPv6 addresses contain multiple colons; domain:port contains only one
        return val.count(":") >= 2


@dataclass(slots=True)
class ProbeResult:
    target: Target
    resolved_ip: str
    ip_version: str
    operator_name: str
    ping_ms: float
    download_mbps: float
    jitter_ms: float
    packet_loss_pct: float
    bytes_downloaded: int
    duration_s: float
    http_status: int
    status: ProbeStatus
    error_message: str = ""
    tested_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    cdn_name: str = ""
    location: str = ""
    services_badges: str = ""
    services_passed: int = 0
    fitness_multiplier: float = 1.0

    def __post_init__(self) -> None:
        if not self.cdn_name:
            self.cdn_name = self.target.cdn_name or detect_cdn_for_ip(
                self.resolved_ip, self.target.source_file
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target.host,
            "target_type": getattr(self.target.target_type, "value", str(self.target.target_type)),
            "resolved_ip": self.resolved_ip,
            "cdn_name": self.cdn_name,
            "location": self.location,
            "ip_version": self.ip_version,
            "operator_name": self.operator_name,
            "ping_ms": round(self.ping_ms, 2),
            "download_mbps": round(self.download_mbps, 2),
            "jitter_ms": round(self.jitter_ms, 2),
            "packet_loss_pct": round(self.packet_loss_pct, 1),
            "bytes_downloaded": self.bytes_downloaded,
            "duration_s": round(self.duration_s, 3),
            "http_status": self.http_status,
            "status": getattr(self.status, "value", str(self.status)),
            "error_message": self.error_message,
            "tested_at": self.tested_at,
            "services_badges": self.services_badges,
            "services_passed": self.services_passed,
            "fitness_multiplier": round(self.fitness_multiplier, 2),
        }


@dataclass(slots=True)
class AggregatedScore:
    target_repr: str
    resolved_ip: str
    ip_version: str
    total_isps_tested: int
    successful_isps_count: int
    isp_coverage: str
    tested_operators: list[str]
    successful_operators: list[str]
    min_speed_mbps: float
    harmonic_mean_speed_mbps: float
    arithmetic_mean_speed_mbps: float
    avg_ping_ms: float
    min_ping_ms: float
    max_ping_ms: float
    pass_rate_pct: float
    universal_score: float
    cdn_name: str = ""
    location: str = ""
    services_badges: str = ""
    services_passed: int = 0
    fitness_multiplier: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target_repr,
            "resolved_ip": self.resolved_ip,
            "cdn_name": self.cdn_name,
            "location": self.location,
            "ip_version": self.ip_version,
            "isp_coverage": self.isp_coverage,
            "tested_operators": ", ".join(self.tested_operators),
            "successful_operators": ", ".join(self.successful_operators),
            "min_speed_mbps": round(self.min_speed_mbps, 2),
            "harmonic_mean_speed_mbps": round(self.harmonic_mean_speed_mbps, 2),
            "arithmetic_mean_speed_mbps": round(self.arithmetic_mean_speed_mbps, 2),
            "avg_ping_ms": round(self.avg_ping_ms, 2),
            "min_ping_ms": round(self.min_ping_ms, 2),
            "max_ping_ms": round(self.max_ping_ms, 2),
            "pass_rate_pct": round(self.pass_rate_pct, 1),
            "universal_score": round(self.universal_score, 2),
            "services_badges": self.services_badges,
            "services_passed": self.services_passed,
            "fitness_multiplier": round(self.fitness_multiplier, 2),
        }
