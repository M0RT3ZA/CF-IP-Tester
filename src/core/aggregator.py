from __future__ import annotations

import os
import sqlite3
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from src.core.cdn_presets import detect_cdn_for_ip
from src.models import AggregatedScore, ProbeResult, ProbeStatus, Target, TargetType


class SessionDatabase:
    """
    Manages persistent SQLite storage for multi-session edge benchmark telemetry.
    Ensures ACID compliance and relational indexing across targets, operators, and test runs.
    """

    def __init__(self, db_path: str | Path = "data/sessions.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for high-concurrency read/write operations without table locking
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_schema(self) -> None:
        with self._get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS test_runs (
                    run_id TEXT PRIMARY KEY,
                    operator_name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    target_count INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS endpoint_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    target TEXT NOT NULL,
                    resolved_ip TEXT NOT NULL,
                    cdn_name TEXT NOT NULL DEFAULT '',
                    location TEXT NOT NULL DEFAULT '',
                    ip_version TEXT NOT NULL,
                    operator_name TEXT NOT NULL,
                    ping_ms REAL NOT NULL,
                    download_mbps REAL NOT NULL,
                    jitter_ms REAL NOT NULL,
                    packet_loss_pct REAL NOT NULL,
                    bytes_downloaded INTEGER NOT NULL,
                    duration_s REAL NOT NULL,
                    http_status INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    tested_at TEXT NOT NULL,
                    services_badges TEXT NOT NULL DEFAULT '',
                    services_passed INTEGER NOT NULL DEFAULT 0,
                    fitness_multiplier REAL NOT NULL DEFAULT 1.0,
                    FOREIGN KEY(run_id) REFERENCES test_runs(run_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_endpoint_target ON endpoint_results(target);
                CREATE INDEX IF NOT EXISTS idx_endpoint_resolved_ip ON endpoint_results(resolved_ip);
                CREATE INDEX IF NOT EXISTS idx_endpoint_operator ON endpoint_results(operator_name);
                CREATE INDEX IF NOT EXISTS idx_endpoint_status ON endpoint_results(status);
                """
            )
            for col_def in (
                "cdn_name TEXT NOT NULL DEFAULT ''",
                "location TEXT NOT NULL DEFAULT ''",
                "services_badges TEXT NOT NULL DEFAULT ''",
                "services_passed INTEGER NOT NULL DEFAULT 0",
                "fitness_multiplier REAL NOT NULL DEFAULT 1.0",
            ):
                try:
                    conn.execute(f"ALTER TABLE endpoint_results ADD COLUMN {col_def};")
                except sqlite3.OperationalError:
                    pass

    def create_run(self, run_id: str, operator_name: str, target_count: int) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO test_runs (run_id, operator_name, started_at, target_count)
                VALUES (?, ?, ?, ?);
                """,
                (
                    run_id,
                    operator_name,
                    datetime.now(timezone.utc).isoformat(),
                    target_count,
                ),
            )

    def save_probe_results(self, run_id: str, results: Sequence[ProbeResult]) -> None:
        if not results:
            return

        records = [
            (
                run_id,
                r.target.host,
                r.resolved_ip,
                r.cdn_name or detect_cdn_for_ip(r.resolved_ip, r.target.source_file),
                r.location,
                r.ip_version,
                r.operator_name,
                r.ping_ms,
                r.download_mbps,
                r.jitter_ms,
                r.packet_loss_pct,
                r.bytes_downloaded,
                r.duration_s,
                r.http_status,
                getattr(r.status, "value", str(r.status)),
                r.error_message,
                r.tested_at,
                r.services_badges,
                r.services_passed,
                r.fitness_multiplier,
            )
            for r in results
        ]

        with self._get_connection() as conn:
            conn.executemany(
                """
                INSERT INTO endpoint_results (
                    run_id, target, resolved_ip, cdn_name, location, ip_version, operator_name,
                    ping_ms, download_mbps, jitter_ms, packet_loss_pct,
                    bytes_downloaded, duration_s, http_status, status,
                    error_message, tested_at, services_badges, services_passed, fitness_multiplier
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                records,
            )

    def complete_run(self, run_id: str, success_count: int) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE test_runs
                SET completed_at = ?, success_count = ?
                WHERE run_id = ?;
                """,
                (datetime.now(timezone.utc).isoformat(), success_count, run_id),
            )

    def get_all_tested_operators(self) -> list[str]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT DISTINCT operator_name
                FROM endpoint_results
                ORDER BY operator_name ASC;
                """
            )
            return [row["operator_name"] for row in cursor.fetchall()]

    def get_latest_results_by_operator(self, operator_name: str) -> list[ProbeResult]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT target, resolved_ip, cdn_name, location, ip_version, operator_name,
                       ping_ms, download_mbps, jitter_ms, packet_loss_pct,
                       bytes_downloaded, duration_s, http_status, status,
                       error_message, tested_at, services_badges, services_passed, fitness_multiplier
                FROM endpoint_results
                WHERE id IN (
                    SELECT MAX(id)
                    FROM endpoint_results
                    WHERE operator_name = ?
                    GROUP BY target, resolved_ip
                )
                ORDER BY download_mbps DESC, ping_ms ASC;
                """,
                (operator_name,),
            )
            results: list[ProbeResult] = []
            for row in cursor.fetchall():
                t = Target.from_string(row["target"])
                if not t:
                    ip_type = (
                        TargetType.IPV6
                        if row["ip_version"] == "IPv6"
                        else TargetType.IPV4
                    )
                    t = Target(
                        raw_input=row["target"],
                        target_type=ip_type,
                        host=row["target"],
                        cdn_name=row["cdn_name"] if "cdn_name" in row.keys() and row["cdn_name"] else "",
                    )

                c_name = row["cdn_name"] if "cdn_name" in row.keys() and row["cdn_name"] else (t.cdn_name or detect_cdn_for_ip(row["resolved_ip"], row["target"]))
                loc = row["location"] if "location" in row.keys() and row["location"] else ""
                badges = row["services_badges"] if "services_badges" in row.keys() and row["services_badges"] else ""
                passed = row["services_passed"] if "services_passed" in row.keys() and row["services_passed"] else 0
                mult = row["fitness_multiplier"] if "fitness_multiplier" in row.keys() and row["fitness_multiplier"] else 1.0

                results.append(
                    ProbeResult(
                        target=t,
                        resolved_ip=row["resolved_ip"],
                        ip_version=row["ip_version"],
                        operator_name=row["operator_name"],
                        ping_ms=row["ping_ms"],
                        download_mbps=row["download_mbps"],
                        jitter_ms=row["jitter_ms"],
                        packet_loss_pct=row["packet_loss_pct"],
                        bytes_downloaded=row["bytes_downloaded"],
                        duration_s=row["duration_s"],
                        http_status=row["http_status"],
                        status=ProbeStatus(row["status"]),
                        error_message=row["error_message"] or "",
                        tested_at=row["tested_at"],
                        cdn_name=c_name,
                        location=loc,
                        services_badges=badges,
                        services_passed=passed,
                        fitness_multiplier=mult,
                    )
                )
            return results

    def get_all_latest_results(self) -> list[ProbeResult]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT target, resolved_ip, cdn_name, location, ip_version, operator_name,
                       ping_ms, download_mbps, jitter_ms, packet_loss_pct,
                       bytes_downloaded, duration_s, http_status, status,
                       error_message, tested_at, services_badges, services_passed, fitness_multiplier
                FROM endpoint_results
                WHERE id IN (
                    SELECT MAX(id)
                    FROM endpoint_results
                    GROUP BY target, resolved_ip, operator_name
                );
                """
            )
            results: list[ProbeResult] = []
            for row in cursor.fetchall():
                t = Target.from_string(row["target"])
                if not t:
                    ip_type = (
                        TargetType.IPV6
                        if row["ip_version"] == "IPv6"
                        else TargetType.IPV4
                    )
                    t = Target(
                        raw_input=row["target"],
                        target_type=ip_type,
                        host=row["target"],
                        cdn_name=row["cdn_name"] if "cdn_name" in row.keys() and row["cdn_name"] else "",
                    )
                c_name = row["cdn_name"] if "cdn_name" in row.keys() and row["cdn_name"] else (t.cdn_name or detect_cdn_for_ip(row["resolved_ip"], row["target"]))
                loc = row["location"] if "location" in row.keys() and row["location"] else ""
                badges = row["services_badges"] if "services_badges" in row.keys() and row["services_badges"] else ""
                passed = row["services_passed"] if "services_passed" in row.keys() and row["services_passed"] else 0
                mult = row["fitness_multiplier"] if "fitness_multiplier" in row.keys() and row["fitness_multiplier"] else 1.0

                results.append(
                    ProbeResult(
                        target=t,
                        resolved_ip=row["resolved_ip"],
                        ip_version=row["ip_version"],
                        operator_name=row["operator_name"],
                        ping_ms=row["ping_ms"],
                        download_mbps=row["download_mbps"],
                        jitter_ms=row["jitter_ms"],
                        packet_loss_pct=row["packet_loss_pct"],
                        bytes_downloaded=row["bytes_downloaded"],
                        duration_s=row["duration_s"],
                        http_status=row["http_status"],
                        status=ProbeStatus(row["status"]),
                        error_message=row["error_message"] or "",
                        tested_at=row["tested_at"],
                        cdn_name=c_name,
                        location=loc,
                        services_badges=badges,
                        services_passed=passed,
                        fitness_multiplier=mult,
                    )
                )
            return results

    def clear_database(self) -> None:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM endpoint_results;")
            conn.execute("DELETE FROM test_runs;")


class Aggregator:
    """
    Computes cross-operator intersection rankings and harmonic throughput metrics.
    """

    @classmethod
    def compute_cross_isp_scores(
        cls, results: Sequence[ProbeResult]
    ) -> list[AggregatedScore]:
        if not results:
            return []

        # Group latest results by unique endpoint key (target + resolved_ip)
        endpoint_map: dict[tuple[str, str], list[ProbeResult]] = {}
        all_operators: set[str] = set()

        for r in results:
            key = (r.target.host, r.resolved_ip)
            if key not in endpoint_map:
                endpoint_map[key] = []
            endpoint_map[key].append(r)
            all_operators.add(r.operator_name)

        total_isps_count = len(all_operators)
        scores: list[AggregatedScore] = []

        for (target_host, resolved_ip), probe_list in endpoint_map.items():
            # Retain only the latest result per operator for this endpoint
            by_op: dict[str, ProbeResult] = {}
            for p in probe_list:
                by_op[p.operator_name] = p

            tested_ops = sorted(by_op.keys())
            successful_ops = [
                op for op, p in by_op.items() if p.status == ProbeStatus.SUCCESS
            ]
            success_count = len(successful_ops)
            coverage_str = f"{success_count}/{total_isps_count} ISPs"

            ip_version = by_op[tested_ops[0]].ip_version

            successful_probes = [by_op[op] for op in successful_ops]

            if successful_probes:
                speeds = [p.download_mbps for p in successful_probes]
                pings = [p.ping_ms for p in successful_probes]

                min_speed = min(speeds)
                arithmetic_mean = statistics.fmean(speeds)

                # Harmonic mean: H = n / sum(1 / x_i)
                # In networking, harmonic mean penalizes asymmetric routing or single-ISP throttles
                # heavily compared to arithmetic mean, ensuring that an IP fast on Operator A but
                # congested or throttled on Operator B receives an accurate baseline score.
                # A small epsilon prevents zero-division for non-zero successful connections.
                harmonic_mean = len(speeds) / sum(
                    1.0 / max(s, 0.001) for s in speeds
                )

                avg_ping = statistics.fmean(pings)
                min_ping = min(pings)
                max_ping = max(pings)
            else:
                min_speed = 0.0
                arithmetic_mean = 0.0
                harmonic_mean = 0.0
                avg_ping = 9999.0
                min_ping = 9999.0
                max_ping = 9999.0

            pass_rate = (success_count / total_isps_count) * 100.0 if total_isps_count else 0.0

            first_probe = by_op[tested_ops[0]]
            cdn_name = first_probe.cdn_name or detect_cdn_for_ip(resolved_ip, target_host)

            # Aggregate service audit metrics and location across tested operators
            badges = ""
            location = ""
            max_passed = 0
            best_mult = 1.0
            for p in by_op.values():
                if not location and p.location and p.location != "Unknown":
                    location = p.location
                if p.services_passed > max_passed:
                    max_passed = p.services_passed
                    badges = p.services_badges
                    best_mult = p.fitness_multiplier
                    if p.location and p.location != "Unknown":
                        location = p.location
                elif not badges and p.services_badges:
                    badges = p.services_badges
                    best_mult = p.fitness_multiplier

            if not location:
                location = "Unknown"

            # Universal composite score:
            # Quadratic coverage ratio weighting ensures endpoints with 100% reachability
            # vastly outrank endpoints missing even one operator.
            # Multiplied by best_mult (Service Fitness Multiplier) to favor IPs working on all major services.
            coverage_factor = (success_count / max(total_isps_count, 1)) ** 2
            latency_penalty = 1.0 + (avg_ping / 150.0)
            universal_score = ((coverage_factor * harmonic_mean) / latency_penalty) * best_mult

            scores.append(
                AggregatedScore(
                    target_repr=target_host,
                    resolved_ip=resolved_ip,
                    ip_version=ip_version,
                    total_isps_tested=total_isps_count,
                    successful_isps_count=success_count,
                    isp_coverage=coverage_str,
                    tested_operators=tested_ops,
                    successful_operators=successful_ops,
                    min_speed_mbps=min_speed,
                    harmonic_mean_speed_mbps=harmonic_mean,
                    arithmetic_mean_speed_mbps=arithmetic_mean,
                    avg_ping_ms=avg_ping,
                    min_ping_ms=min_ping,
                    max_ping_ms=max_ping,
                    pass_rate_pct=pass_rate,
                    universal_score=universal_score,
                    cdn_name=cdn_name,
                    location=location,
                    services_badges=badges,
                    services_passed=max_passed,
                    fitness_multiplier=best_mult,
                )
            )

        return scores
