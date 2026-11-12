from __future__ import annotations

import errno
import ipaddress
import select
import socket
import ssl
import time
from typing import Callable

from src.core.service_auditor import ServiceAuditor
from src.models import ProbeResult, ProbeStatus, Target, TargetType

CLOUDFLARE_SNI_HOST = "speed.cloudflare.com"
MIN_VALID_PAYLOAD_BYTES = 51_200  # 50 KB threshold to reject captive portals and ISP block pages
DEFAULT_CHUNK_SIZE = 65_536  # 64 KB read buffer to maximize socket I/O efficiency without memory bloat


class CloudflareProber:
    def __init__(
        self,
        payload_bytes: int = 5_000_000,
        connect_timeout_s: float = 3.5,
        download_timeout_s: float = 7.0,
        jitter_probes: int = 3,
        sni_host: str = CLOUDFLARE_SNI_HOST,
        download_path: str = "/__down?bytes={bytes}",
        audit_services: bool = False,
    ) -> None:
        self.payload_bytes = payload_bytes
        self.connect_timeout_s = connect_timeout_s
        self.download_timeout_s = download_timeout_s
        self.jitter_probes = max(1, min(jitter_probes, 5))
        self.sni_host = sni_host.strip() if sni_host and sni_host.strip() else CLOUDFLARE_SNI_HOST
        self.download_path = download_path.strip() if download_path and download_path.strip() else "/__down?bytes={bytes}"
        self.audit_services = audit_services
        self._service_auditor = ServiceAuditor(timeout_s=2.5) if audit_services else None

        # Reusable SSL context configured for SNI routing emulation.
        # Disabling hostname verification while explicitly injecting SNI enables
        # testing against raw edge IP literals while satisfying edge CDN SNI routing.
        self._ssl_ctx = ssl.create_default_context()
        self._ssl_ctx.check_hostname = False
        self._ssl_ctx.verify_mode = ssl.CERT_NONE

    def probe(
        self,
        target: Target,
        operator_name: str,
        cancel_check: Callable[[], bool] | None = None,
    ) -> list[ProbeResult]:
        """
        Probes target and returns results for all resolved endpoints (or the single IP).
        If target is a domain, both IPv4 and IPv6 endpoints are resolved and probed.
        """
        if cancel_check and cancel_check():
            return []

        resolved_endpoints = self._resolve_target(target)
        if not resolved_endpoints:
            return [
                ProbeResult(
                    target=target,
                    resolved_ip="0.0.0.0",
                    ip_version="Unknown",
                    operator_name=operator_name,
                    ping_ms=0.0,
                    download_mbps=0.0,
                    jitter_ms=0.0,
                    packet_loss_pct=100.0,
                    bytes_downloaded=0,
                    duration_s=0.0,
                    http_status=0,
                    status=ProbeStatus.DNS_ERROR,
                    error_message="Failed to resolve host via system DNS",
                )
            ]

        results: list[ProbeResult] = []
        for ip_str, family in resolved_endpoints:
            if cancel_check and cancel_check():
                break

            result = self._probe_single_ip(
                target=target,
                ip_str=ip_str,
                family=family,
                operator_name=operator_name,
                cancel_check=cancel_check,
            )
            results.append(result)

        return results

    def _resolve_target(self, target: Target) -> list[tuple[str, socket.AddressFamily]]:
        """
        Resolves the target into concrete IP addresses and address families.
        For raw IP targets, resolution is performed locally via ipaddress parsing.
        """
        if target.target_type in (TargetType.IPV4, TargetType.IPV6):
            family = (
                socket.AF_INET
                if target.target_type == TargetType.IPV4
                else socket.AF_INET6
            )
            return [(target.host, family)]

        endpoints: list[tuple[str, socket.AddressFamily]] = []
        seen_ips: set[str] = set()

        try:
            # Query system resolver for both AF_INET and AF_INET6
            addr_info = socket.getaddrinfo(
                target.host, 443, socket.AF_UNSPEC, socket.SOCK_STREAM
            )
            for item in addr_info:
                family = item[0]
                sockaddr = item[4]
                ip_candidate = sockaddr[0]

                if ip_candidate not in seen_ips:
                    seen_ips.add(ip_candidate)
                    endpoints.append((ip_candidate, family))
        except socket.gaierror:
            return []

        return endpoints

    def _probe_single_ip(
        self,
        target: Target,
        ip_str: str,
        family: socket.AddressFamily,
        operator_name: str,
        cancel_check: Callable[[], bool] | None = None,
    ) -> ProbeResult:
        ip_ver_str = "IPv6" if family == socket.AF_INET6 else "IPv4"

        # 1. Multi-sample latency and jitter measurement
        latencies_ms: list[float] = []
        failures = 0

        for _ in range(self.jitter_probes):
            if cancel_check and cancel_check():
                break
            try:
                lat_ms = self._measure_handshake_latency(ip_str, family)
                latencies_ms.append(lat_ms)
            except (socket.timeout, TimeoutError):
                failures += 1
            except ssl.SSLError:
                failures += 1
            except OSError as err:
                if self._is_unreachable_error(err):
                    return ProbeResult(
                        target=target,
                        resolved_ip=ip_str,
                        ip_version=ip_ver_str,
                        operator_name=operator_name,
                        ping_ms=0.0,
                        download_mbps=0.0,
                        jitter_ms=0.0,
                        packet_loss_pct=100.0,
                        bytes_downloaded=0,
                        duration_s=0.0,
                        http_status=0,
                        status=ProbeStatus.UNREACHABLE,
                        error_message="Host interface lacks routing to target network",
                    )
                failures += 1

        total_probes = self.jitter_probes
        packet_loss_pct = (failures / total_probes) * 100.0

        if not latencies_ms:
            return ProbeResult(
                target=target,
                resolved_ip=ip_str,
                ip_version=ip_ver_str,
                operator_name=operator_name,
                ping_ms=0.0,
                download_mbps=0.0,
                jitter_ms=0.0,
                packet_loss_pct=100.0,
                bytes_downloaded=0,
                duration_s=0.0,
                http_status=0,
                status=ProbeStatus.TIMEOUT if failures == total_probes else ProbeStatus.FAILED,
                error_message="Handshake probes timed out or failed completely",
            )

        best_ping_ms = min(latencies_ms)
        jitter_ms = self._calculate_jitter(latencies_ms)

        # 2. Edge HTTP stream throughput benchmark
        try:
            download_mbps, bytes_read, duration_s, http_status, status, err_msg, headers_raw = (
                self._measure_download_throughput(
                    ip_str, family, cancel_check=cancel_check
                )
            )

            badges_str = ""
            services_passed = 0
            fitness_mult = 1.0
            location_str = ""

            # 3. Service reachability audit via PoP Egress analysis and secure proxy probing
            if self._service_auditor and status == ProbeStatus.SUCCESS and not (cancel_check and cancel_check()):
                audit_res = self._service_auditor.audit_endpoint(
                    ip_str,
                    family,
                    proxy_sni_host=self.sni_host if self.sni_host != CLOUDFLARE_SNI_HOST else "",
                    headers_raw=headers_raw,
                    cancel_check=cancel_check,
                )
                badges_str = audit_res.format_badges()
                services_passed = audit_res.passed_count
                fitness_mult = audit_res.fitness_multiplier
                location_str = audit_res.location

            return ProbeResult(
                target=target,
                resolved_ip=ip_str,
                ip_version=ip_ver_str,
                operator_name=operator_name,
                ping_ms=best_ping_ms,
                download_mbps=download_mbps,
                jitter_ms=jitter_ms,
                packet_loss_pct=packet_loss_pct,
                bytes_downloaded=bytes_read,
                duration_s=duration_s,
                http_status=http_status,
                status=status,
                error_message=err_msg,
                location=location_str,
                services_badges=badges_str,
                services_passed=services_passed,
                fitness_multiplier=fitness_mult,
            )
        except Exception as exc:
            return ProbeResult(
                target=target,
                resolved_ip=ip_str,
                ip_version=ip_ver_str,
                operator_name=operator_name,
                ping_ms=best_ping_ms,
                download_mbps=0.0,
                jitter_ms=jitter_ms,
                packet_loss_pct=packet_loss_pct,
                bytes_downloaded=0,
                duration_s=0.0,
                http_status=0,
                status=ProbeStatus.FAILED,
                error_message=str(exc),
            )

    def _measure_handshake_latency(
        self, ip_str: str, family: socket.AddressFamily
    ) -> float:
        """
        Measures exact TCP connection + TLS handshake duration in milliseconds.
        """
        start_time = time.perf_counter()
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(self.connect_timeout_s)
        try:
            sock.connect((ip_str, 443))
            with self._ssl_ctx.wrap_socket(
                sock, server_hostname=self.sni_host
            ) as ssl_sock:
                # Force TLS handshake negotiation completion
                ssl_sock.do_handshake()
                return (time.perf_counter() - start_time) * 1000.0
        finally:
            try:
                sock.close()
            except OSError:
                pass

    def _measure_download_throughput(
        self,
        ip_str: str,
        family: socket.AddressFamily,
        cancel_check: Callable[[], bool] | None = None,
    ) -> tuple[float, int, float, int, ProbeStatus, str, bytes]:
        """
        Streams payload directly into volatile memory via raw HTTP/1.1 over TLS.
        Calculates real payload throughput while guarding against captive portals.
        """
        raw_sock = socket.socket(family, socket.SOCK_STREAM)
        raw_sock.settimeout(self.connect_timeout_s)

        try:
            raw_sock.connect((ip_str, 443))
        except (socket.timeout, TimeoutError):
            raw_sock.close()
            return 0.0, 0, 0.0, 0, ProbeStatus.TIMEOUT, "TCP connection timed out", b""
        except OSError as err:
            raw_sock.close()
            return 0.0, 0, 0.0, 0, ProbeStatus.UNREACHABLE, f"Connect error: {err}", b""

        try:
            ssl_sock = self._ssl_ctx.wrap_socket(
                raw_sock, server_hostname=self.sni_host
            )
        except (socket.timeout, TimeoutError) as err:
            raw_sock.close()
            return 0.0, 0, 0.0, 0, ProbeStatus.TIMEOUT, f"TLS handshake timed out: {err}", b""
        except ssl.SSLError as err:
            raw_sock.close()
            is_timeout = "timed out" in str(err).lower() or isinstance(err, (socket.timeout, TimeoutError))
            status = ProbeStatus.TIMEOUT if is_timeout else ProbeStatus.TLS_ERROR
            return 0.0, 0, 0.0, 0, status, f"TLS negotiation error: {err}", b""

        # Resolve path template if {bytes} placeholder is present
        if "{bytes}" in self.download_path:
            req_path = self.download_path.replace("{bytes}", str(self.payload_bytes))
        else:
            req_path = self.download_path

        # Construct raw HTTP/1.1 GET request to edge test endpoint
        http_request = (
            f"GET {req_path} HTTP/1.1\r\n"
            f"Host: {self.sni_host}\r\n"
            "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36\r\n"
            "Accept: */*\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")

        try:
            ssl_sock.settimeout(self.connect_timeout_s)
            ssl_sock.sendall(http_request)

            # Parse HTTP status code from response header line
            header_data = bytearray()
            while b"\r\n\r\n" not in header_data:
                chunk = ssl_sock.recv(4096)
                if not chunk:
                    break
                header_data.extend(chunk)

            if not header_data:
                ssl_sock.close()
                return 0.0, 0, 0.0, 0, ProbeStatus.HTTP_ERROR, "Empty HTTP response from edge", b""

            headers_raw, _, body_initial = header_data.partition(b"\r\n\r\n")
            first_line = headers_raw.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
            parts = first_line.split()
            if len(parts) < 2 or not parts[1].isdigit():
                ssl_sock.close()
                return 0.0, 0, 0.0, 0, ProbeStatus.HTTP_ERROR, f"Malformed response: {first_line}", b""

            http_status = int(parts[1])
            is_speed_endpoint = "/__down" in self.download_path

            # Accept 200 (OK), 204 (No Content), 206 (Partial), and 30x redirects as reachable edge
            if http_status not in (200, 204, 206, 301, 302, 307, 308):
                if http_status in (403, 451):
                    ssl_sock.close()
                    return 0.0, 0, 0.0, http_status, ProbeStatus.BLOCKED, f"Edge blocked request (HTTP {http_status})", bytes(headers_raw)
                elif http_status == 404 and not is_speed_endpoint:
                    pass  # Edge reached and responded; valid for custom host without root resource
                else:
                    ssl_sock.close()
                    return (
                        0.0,
                        0,
                        0.0,
                        http_status,
                        ProbeStatus.HTTP_ERROR,
                        f"Edge returned HTTP status: {http_status}",
                        bytes(headers_raw),
                    )

            # Begin timed payload streaming directly into volatile memory
            bytes_received = len(body_initial)
            stream_start = time.perf_counter()
            deadline = stream_start + self.download_timeout_s

            ssl_sock.setblocking(False)

            while True:
                if cancel_check and cancel_check():
                    break

                now = time.perf_counter()
                time_remaining = deadline - now
                if time_remaining <= 0:
                    break

                # Use non-blocking select to enforce sub-millisecond deadline resolution
                r_ready, _, _ = select.select([ssl_sock], [], [], min(0.2, time_remaining))
                if not r_ready:
                    continue

                try:
                    data = ssl_sock.recv(DEFAULT_CHUNK_SIZE)
                    if not data:
                        # Edge closed connection after serving requested byte count
                        break
                    bytes_received += len(data)
                except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
                    continue
                except (socket.timeout, TimeoutError):
                    break
                except OSError:
                    break

            duration_s = max(time.perf_counter() - stream_start, 0.001)

            # Reject captive portals or block pages returning minimal byte content on dedicated speed endpoints
            if is_speed_endpoint and bytes_received < MIN_VALID_PAYLOAD_BYTES:
                ssl_sock.close()
                return (
                    0.0,
                    bytes_received,
                    duration_s,
                    http_status,
                    ProbeStatus.BLOCKED,
                    f"Payload below valid threshold ({bytes_received} bytes received)",
                    bytes(headers_raw),
                )

            # Megabits per second calculation (bits / seconds / 10^6)
            download_mbps = (bytes_received * 8.0) / (duration_s * 1_000_000.0)
            ssl_sock.close()

            return download_mbps, bytes_received, duration_s, http_status, ProbeStatus.SUCCESS, "", bytes(headers_raw)

        except (socket.timeout, TimeoutError) as exc:
            try:
                ssl_sock.close()
            except OSError:
                pass
            return 0.0, 0, 0.0, 0, ProbeStatus.TIMEOUT, f"Socket timed out: {exc}", b""
        except ssl.SSLError as exc:
            try:
                ssl_sock.close()
            except OSError:
                pass
            is_timeout = "timed out" in str(exc).lower() or isinstance(exc, (socket.timeout, TimeoutError))
            status = ProbeStatus.TIMEOUT if is_timeout else ProbeStatus.TLS_ERROR
            return 0.0, 0, 0.0, 0, status, f"TLS error: {exc}", b""
        except Exception as exc:
            try:
                ssl_sock.close()
            except OSError:
                pass
            return 0.0, 0, 0.0, 0, ProbeStatus.FAILED, f"Benchmark stream failure: {exc}", b""

    @staticmethod
    def _calculate_jitter(samples: list[float]) -> float:
        """
        Calculates RFC 3550 statistical jitter (mean absolute deviation of consecutive delays).
        """
        if len(samples) < 2:
            return 0.0
        diffs = [abs(samples[i] - samples[i - 1]) for i in range(1, len(samples))]
        return sum(diffs) / len(diffs)

    @staticmethod
    def _is_unreachable_error(err: OSError) -> bool:
        """
        Detects operating system errors indicating lack of layer 3 routing
        for the given address family (common when host lacks IPv6 default route).
        """
        unreachable_codes = {
            errno.EAFNOSUPPORT,
            errno.ENETUNREACH,
            errno.EHOSTUNREACH,
            10051,  # Windows WSAENETUNREACH
            10047,  # Windows WSAEAFNOSUPPORT
            10065,  # Windows WSAEHOSTUNREACH
        }
        return getattr(err, "errno", None) in unreachable_codes
