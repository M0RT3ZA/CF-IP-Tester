from __future__ import annotations

import csv
import sqlite3
from enum import StrEnum
from pathlib import Path
from typing import Sequence

from src.models import AggregatedScore, ProbeResult, ProbeStatus


class SortCriteria(StrEnum):
    SPEED_FIRST = "SPEED_FIRST"
    PING_FIRST = "PING_FIRST"
    UNIVERSAL_SCORE = "UNIVERSAL_SCORE"
    SERVICES_FIRST = "SERVICES_FIRST"


class BenchmarkExporter:
    """
    Exports edge benchmark telemetry into industry-standard network configuration
    and analytical formats, tailored for universal proxy panel routing and multi-operator auditing.
    """

    @classmethod
    def sort_probe_results(
        cls, results: Sequence[ProbeResult], criteria: SortCriteria = SortCriteria.SPEED_FIRST
    ) -> list[ProbeResult]:
        """
        Sorts single-run probe results deterministically based on network performance criteria.
        Failed/timed-out probes are penalized and sorted after successful probes.
        """
        res_list = list(results)

        def key_speed(p: ProbeResult):
            is_ok = 1 if p.status == ProbeStatus.SUCCESS else 0
            ping_val = p.ping_ms if p.ping_ms > 0 else 9999.0
            return (is_ok, p.download_mbps, -ping_val)

        def key_ping(p: ProbeResult):
            is_ok = 1 if p.status == ProbeStatus.SUCCESS else 0
            ping_val = p.ping_ms if p.ping_ms > 0 else 9999.0
            return (is_ok, -ping_val, p.download_mbps)

        def key_services(p: ProbeResult):
            is_ok = 1 if p.status == ProbeStatus.SUCCESS else 0
            return (is_ok, p.services_passed, p.download_mbps, -p.ping_ms)

        if criteria == SortCriteria.PING_FIRST or str(criteria) == "PING_FIRST":
            res_list.sort(key=key_ping, reverse=True)
        elif criteria == SortCriteria.SERVICES_FIRST or str(criteria) == "SERVICES_FIRST":
            res_list.sort(key=key_services, reverse=True)
        else:
            # Default to speed first
            res_list.sort(key=key_speed, reverse=True)

        return res_list

    @classmethod
    def sort_aggregated_scores(
        cls,
        scores: Sequence[AggregatedScore],
        criteria: SortCriteria = SortCriteria.UNIVERSAL_SCORE,
    ) -> list[AggregatedScore]:
        """
        Sorts cross-ISP aggregated scores strictly following the specified criteria.
        """
        res_list = list(scores)

        def key_universal(s: AggregatedScore):
            # Prioritize full coverage across operators, then composite universal score (which includes service multiplier)
            return (
                s.successful_isps_count,
                s.universal_score,
                s.harmonic_mean_speed_mbps,
                -s.avg_ping_ms,
            )

        def key_speed(s: AggregatedScore):
            return (
                s.harmonic_mean_speed_mbps,
                s.min_speed_mbps,
                s.successful_isps_count,
                -s.avg_ping_ms,
            )

        def key_ping(s: AggregatedScore):
            ping_val = s.avg_ping_ms if s.avg_ping_ms < 9000 else 9999.0
            return (-ping_val, s.successful_isps_count, s.harmonic_mean_speed_mbps)

        def key_services(s: AggregatedScore):
            return (
                s.services_passed,
                s.successful_isps_count,
                s.universal_score,
                s.harmonic_mean_speed_mbps,
            )

        if criteria == SortCriteria.SPEED_FIRST or str(criteria) == "SPEED_FIRST":
            res_list.sort(key=key_speed, reverse=True)
        elif criteria == SortCriteria.PING_FIRST or str(criteria) == "PING_FIRST":
            res_list.sort(key=key_ping, reverse=True)
        elif criteria == SortCriteria.SERVICES_FIRST or str(criteria) == "SERVICES_FIRST":
            res_list.sort(key=key_services, reverse=True)
        else:
            res_list.sort(key=key_universal, reverse=True)

        return res_list

    @classmethod
    def export_clean_txt(
        cls,
        path: str | Path,
        results: Sequence[ProbeResult] | None = None,
        aggregated: Sequence[AggregatedScore] | None = None,
        criteria: SortCriteria = SortCriteria.SPEED_FIRST,
        ordered_endpoints: Sequence[str] | None = None,
    ) -> int:
        """
        Exports clean, deduplicated endpoints formatted for proxy panels and client routing configs
        (e.g., X-UI, Marzban, Hiddify, Sing-box, V2Ray, Clash, Workers, and Pages).
        Encoded strictly in UTF-8 without byte order marks (BOM) to prevent daemon parsing errors.
        Respects the exact sorting order specified by criteria or visible table rows.
        """
        target_path = Path(path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        winning_lines: list[str] = []
        seen: set[str] = set()

        if ordered_endpoints:
            # Maintain exact user visual table ordering if provided
            for ep in ordered_endpoints:
                cleaned = ep.strip()
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    winning_lines.append(cleaned)
        elif aggregated:
            sorted_agg = cls.sort_aggregated_scores(aggregated, criteria)
            for s in sorted_agg:
                if s.successful_isps_count == 0:
                    continue
                ep = s.resolved_ip if s.resolved_ip and s.resolved_ip != "0.0.0.0" else s.target_repr
                loc_tag = f" ({s.location})" if s.location and s.location != "Unknown" else ""
                tag = f" # {s.cdn_name}{loc_tag}" if s.cdn_name else (f" # {s.location}" if loc_tag else "")
                entry = f"{ep}{tag}"
                if ep and ep not in seen:
                    seen.add(ep)
                    winning_lines.append(entry)
        elif results:
            sorted_results = cls.sort_probe_results(results, criteria)
            for r in sorted_results:
                r_status = getattr(r.status, "value", str(r.status))
                if r_status != ProbeStatus.SUCCESS.value:
                    continue
                ep = r.resolved_ip if r.resolved_ip and r.resolved_ip != "0.0.0.0" else r.target.host
                loc_tag = f" ({r.location})" if r.location and r.location != "Unknown" else ""
                tag = f" # {r.cdn_name}{loc_tag}" if r.cdn_name else (f" # {r.location}" if loc_tag else "")
                entry = f"{ep}{tag}"
                if ep and ep not in seen:
                    seen.add(ep)
                    winning_lines.append(entry)

        with open(target_path, "w", encoding="utf-8", newline="\n") as f:
            for line in winning_lines:
                f.write(f"{line}\n")

        return len(winning_lines)

    # Backward-compatible alias for existing callers
    export_zeus_txt = export_clean_txt

    @classmethod
    def export_csv(
        cls,
        path: str | Path,
        results: Sequence[ProbeResult],
        criteria: SortCriteria = SortCriteria.SPEED_FIRST,
    ) -> int:
        sorted_results = cls.sort_probe_results(results, criteria)
        target_path = Path(path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        fieldnames = [
            "target",
            "resolved_ip",
            "cdn",
            "location",
            "ip_version",
            "operator_name",
            "ping_ms",
            "download_mbps",
            "services_badges",
            "services_passed",
            "fitness_multiplier",
            "status",
            "tested_at",
        ]

        with open(target_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(fieldnames)
            for r in sorted_results:
                writer.writerow(
                    [
                        r.target.host,
                        r.resolved_ip,
                        r.cdn_name,
                        r.location or "Unknown",
                        r.ip_version,
                        r.operator_name,
                        round(r.ping_ms, 2),
                        round(r.download_mbps, 2),
                        r.services_badges,
                        r.services_passed,
                        round(r.fitness_multiplier, 2),
                        getattr(r.status, "value", str(r.status)),
                        r.tested_at,
                    ]
                )

        return len(sorted_results)

    @classmethod
    def export_matrix_csv(
        cls,
        path: str | Path,
        aggregated: Sequence[AggregatedScore],
        operators: Sequence[str] | None = None,
        criteria: SortCriteria = SortCriteria.UNIVERSAL_SCORE,
        all_results: Sequence[ProbeResult] | None = None,
    ) -> int:
        """
        Exports the consolidated cross-ISP comparison matrix directly to CSV.
        """
        sorted_agg = cls.sort_aggregated_scores(aggregated, criteria)
        target_path = Path(path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        ops = list(operators) if operators else []
        op_lookup: dict[tuple[str, str, str], ProbeResult] = {}
        if all_results:
            for r in all_results:
                op_lookup[(r.target.host, r.resolved_ip, r.operator_name)] = r

        base_headers = [
            "target",
            "resolved_ip",
            "cdn",
            "location",
            "ip_version",
            "isp_coverage",
            "services_badges",
            "services_passed",
            "fitness_multiplier",
            "min_speed_mbps",
            "harmonic_mean_speed_mbps",
            "arithmetic_mean_speed_mbps",
            "avg_ping_ms",
            "universal_score",
        ]
        op_headers = [f"isp_{op}_mbps" for op in ops]
        all_headers = base_headers + op_headers

        with open(target_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(all_headers)
            for s in sorted_agg:
                row_vals = [
                    s.target_repr,
                    s.resolved_ip,
                    s.cdn_name,
                    s.location or "Unknown",
                    s.ip_version,
                    s.isp_coverage,
                    s.services_badges,
                    s.services_passed,
                    round(s.fitness_multiplier, 2),
                    round(s.min_speed_mbps, 2),
                    round(s.harmonic_mean_speed_mbps, 2),
                    round(s.arithmetic_mean_speed_mbps, 2),
                    round(s.avg_ping_ms, 2),
                    round(s.universal_score, 2),
                ]
                for op in ops:
                    probe = op_lookup.get((s.target_repr, s.resolved_ip, op))
                    if probe and (probe.status == ProbeStatus.SUCCESS or getattr(probe.status, "value", str(probe.status)) == "SUCCESS"):
                        row_vals.append(round(probe.download_mbps, 2))
                    elif probe:
                        row_vals.append(getattr(probe.status, "value", str(probe.status)))
                    else:
                        row_vals.append("N/A")
                writer.writerow(row_vals)

        return len(sorted_agg)

    @classmethod
    def export_xlsx(
        cls,
        path: str | Path,
        results: Sequence[ProbeResult],
        aggregated: Sequence[AggregatedScore] | None = None,
        criteria: SortCriteria = SortCriteria.SPEED_FIRST,
    ) -> None:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment

        target_path = Path(path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        wb = openpyxl.Workbook()
        ws_raw = wb.active
        ws_raw.title = "Operator Results"

        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")

        # Sheet 1: Raw results sorted by active criteria
        raw_headers = [
            "Target",
            "Resolved IP",
            "CDN",
            "Location",
            "IP Version",
            "Operator",
            "Ping (ms)",
            "Speed (Mbps)",
            "Jitter (ms)",
            "Loss (%)",
            "Services (TG/YT/IG/X)",
            "Services Passed",
            "Fitness Multiplier",
            "Status",
            "Tested At",
        ]
        ws_raw.append(raw_headers)
        for col_idx in range(1, len(raw_headers) + 1):
            cell = ws_raw.cell(row=1, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center")

        sorted_results = cls.sort_probe_results(results, criteria)
        for r in sorted_results:
            ws_raw.append(
                [
                    r.target.host,
                    r.resolved_ip,
                    r.cdn_name,
                    r.location or "Unknown",
                    r.ip_version,
                    r.operator_name,
                    round(r.ping_ms, 2),
                    round(r.download_mbps, 2),
                    round(r.jitter_ms, 2),
                    round(r.packet_loss_pct, 1),
                    r.services_badges,
                    r.services_passed,
                    round(r.fitness_multiplier, 2),
                    getattr(r.status, "value", str(r.status)),
                    r.tested_at,
                ]
            )

        for col in ws_raw.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = col[0].column_letter
            ws_raw.column_dimensions[col_letter].width = max(max_len + 3, 12)

        # Sheet 2: Cross-ISP Summary sorted by active criteria
        if aggregated:
            ws_summary = wb.create_sheet(title="Cross-ISP Summary")
            summary_headers = [
                "Target",
                "Resolved IP",
                "CDN",
                "Location",
                "IP Version",
                "ISP Coverage",
                "Services (TG/YT/IG/X)",
                "Services Passed",
                "Fitness Multiplier",
                "Tested Operators",
                "Successful Operators",
                "Min Speed (Mbps)",
                "Harmonic Mean Speed (Mbps)",
                "Arithmetic Mean Speed (Mbps)",
                "Avg Ping (ms)",
                "Universal Score",
            ]
            ws_summary.append(summary_headers)
            for col_idx in range(1, len(summary_headers) + 1):
                cell = ws_summary.cell(row=1, column=col_idx)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal="center")

            sorted_agg = cls.sort_aggregated_scores(aggregated, criteria)
            for s in sorted_agg:
                ws_summary.append(
                    [
                        s.target_repr,
                        s.resolved_ip,
                        s.cdn_name,
                        s.location or "Unknown",
                        s.ip_version,
                        s.isp_coverage,
                        s.services_badges,
                        s.services_passed,
                        round(s.fitness_multiplier, 2),
                        ", ".join(s.tested_operators),
                        ", ".join(s.successful_operators),
                        round(s.min_speed_mbps, 2),
                        round(s.harmonic_mean_speed_mbps, 2),
                        round(s.arithmetic_mean_speed_mbps, 2),
                        round(s.avg_ping_ms, 2),
                        round(s.universal_score, 2),
                    ]
                )

            for col in ws_summary.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                col_letter = col[0].column_letter
                ws_summary.column_dimensions[col_letter].width = max(max_len + 3, 14)

        wb.save(target_path)

    @classmethod
    def export_xls(
        cls,
        path: str | Path,
        results: Sequence[ProbeResult],
        aggregated: Sequence[AggregatedScore] | None = None,
        criteria: SortCriteria = SortCriteria.SPEED_FIRST,
    ) -> None:
        import xlwt

        target_path = Path(path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        wb = xlwt.Workbook(encoding="utf-8")
        ws_raw = wb.add_sheet("Operator Results")

        header_style = xlwt.easyxf(
            "font: bold on, color white; pattern: pattern solid, fore_colour dark_blue; align: horiz center"
        )

        raw_headers = [
            "Target",
            "Resolved IP",
            "CDN",
            "Location",
            "IP Version",
            "Operator",
            "Ping (ms)",
            "Speed (Mbps)",
            "Status",
            "Tested At",
        ]
        for c_idx, h in enumerate(raw_headers):
            ws_raw.write(0, c_idx, h, header_style)

        sorted_results = cls.sort_probe_results(results, criteria)
        for r_idx, r in enumerate(sorted_results, start=1):
            ws_raw.write(r_idx, 0, r.target.host)
            ws_raw.write(r_idx, 1, r.resolved_ip)
            ws_raw.write(r_idx, 2, r.cdn_name)
            ws_raw.write(r_idx, 3, r.location or "Unknown")
            ws_raw.write(r_idx, 4, r.ip_version)
            ws_raw.write(r_idx, 5, r.operator_name)
            ws_raw.write(r_idx, 6, round(r.ping_ms, 2))
            ws_raw.write(r_idx, 7, round(r.download_mbps, 2))
            ws_raw.write(r_idx, 8, getattr(r.status, "value", str(r.status)))
            ws_raw.write(r_idx, 9, r.tested_at)

        if aggregated:
            ws_summary = wb.add_sheet("Cross-ISP Summary")
            summary_headers = [
                "Target",
                "Resolved IP",
                "CDN",
                "Location",
                "Coverage",
                "Min Speed (Mbps)",
                "Harmonic Mean (Mbps)",
                "Avg Ping (ms)",
                "Universal Score",
            ]
            for c_idx, h in enumerate(summary_headers):
                ws_summary.write(0, c_idx, h, header_style)

            sorted_agg = cls.sort_aggregated_scores(aggregated, criteria)
            for r_idx, s in enumerate(sorted_agg, start=1):
                ws_summary.write(r_idx, 0, s.target_repr)
                ws_summary.write(r_idx, 1, s.resolved_ip)
                ws_summary.write(r_idx, 2, s.cdn_name)
                ws_summary.write(r_idx, 3, s.location or "Unknown")
                ws_summary.write(r_idx, 4, s.isp_coverage)
                ws_summary.write(r_idx, 5, round(s.min_speed_mbps, 2))
                ws_summary.write(r_idx, 6, round(s.harmonic_mean_speed_mbps, 2))
                ws_summary.write(r_idx, 7, round(s.avg_ping_ms, 2))
                ws_summary.write(r_idx, 8, round(s.universal_score, 2))

        wb.save(str(target_path))

    @classmethod
    def export_sqlite(
        cls,
        path: str | Path,
        results: Sequence[ProbeResult],
        aggregated: Sequence[AggregatedScore] | None = None,
        criteria: SortCriteria = SortCriteria.SPEED_FIRST,
    ) -> None:
        target_path = Path(path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if target_path.exists():
            target_path.unlink()

        conn = sqlite3.connect(str(target_path))
        with conn:
            conn.executescript(
                """
                CREATE TABLE endpoint_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target TEXT NOT NULL,
                    resolved_ip TEXT NOT NULL,
                    cdn TEXT NOT NULL,
                    location TEXT NOT NULL,
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
                    services_badges TEXT NOT NULL,
                    services_passed INTEGER NOT NULL,
                    fitness_multiplier REAL NOT NULL
                );

                CREATE TABLE cross_isp_summary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target TEXT NOT NULL,
                    resolved_ip TEXT NOT NULL,
                    cdn TEXT NOT NULL,
                    location TEXT NOT NULL,
                    ip_version TEXT NOT NULL,
                    isp_coverage TEXT NOT NULL,
                    services_badges TEXT NOT NULL,
                    services_passed INTEGER NOT NULL,
                    fitness_multiplier REAL NOT NULL,
                    tested_operators TEXT NOT NULL,
                    successful_operators TEXT NOT NULL,
                    min_speed_mbps REAL NOT NULL,
                    harmonic_mean_speed_mbps REAL NOT NULL,
                    arithmetic_mean_speed_mbps REAL NOT NULL,
                    avg_ping_ms REAL NOT NULL,
                    universal_score REAL NOT NULL
                );
                """
            )

            sorted_results = cls.sort_probe_results(results, criteria)
            res_records = [
                (
                    r.target.host,
                    r.resolved_ip,
                    r.cdn_name,
                    r.location or "Unknown",
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
                for r in sorted_results
            ]
            conn.executemany(
                """
                INSERT INTO endpoint_results (
                    target, resolved_ip, cdn, location, ip_version, operator_name,
                    ping_ms, download_mbps, jitter_ms, packet_loss_pct,
                    bytes_downloaded, duration_s, http_status, status,
                    error_message, tested_at, services_badges, services_passed, fitness_multiplier
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                res_records,
            )

            if aggregated:
                sorted_agg = cls.sort_aggregated_scores(aggregated, criteria)
                agg_records = [
                    (
                        s.target_repr,
                        s.resolved_ip,
                        s.cdn_name,
                        s.location or "Unknown",
                        s.ip_version,
                        s.isp_coverage,
                        s.services_badges,
                        s.services_passed,
                        s.fitness_multiplier,
                        ", ".join(s.tested_operators),
                        ", ".join(s.successful_operators),
                        s.min_speed_mbps,
                        s.harmonic_mean_speed_mbps,
                        s.arithmetic_mean_speed_mbps,
                        s.avg_ping_ms,
                        s.universal_score,
                    )
                    for s in sorted_agg
                ]
                conn.executemany(
                    """
                    INSERT INTO cross_isp_summary (
                        target, resolved_ip, cdn, location, ip_version, isp_coverage,
                        services_badges, services_passed, fitness_multiplier,
                        tested_operators, successful_operators, min_speed_mbps,
                        harmonic_mean_speed_mbps, arithmetic_mean_speed_mbps,
                        avg_ping_ms, universal_score
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    agg_records,
                )
        conn.close()
