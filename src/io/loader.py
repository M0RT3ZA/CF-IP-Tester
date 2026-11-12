from __future__ import annotations

import csv
import os
import sqlite3
from pathlib import Path
from typing import Sequence

from src.models import Target, TargetType


class TargetLoader:
    """
    Ingests and validates targets across text, structured delimited files,
    spreadsheets, and relational database dumps.
    """

    SUPPORTED_EXTENSIONS = {".txt", ".csv", ".xlsx", ".xls", ".sqlite", ".db"}

    @classmethod
    def load_directory(
        cls, dir_path: str | Path = "inputs"
    ) -> tuple[list[Target], list[str]]:
        """
        Scans directory for all supported file formats and aggregates parsed targets.
        Returns a tuple of (deduplicated_targets, loaded_file_names).
        """
        folder = Path(dir_path)
        if not folder.exists() or not folder.is_dir():
            return [], []

        all_targets: list[Target] = []
        loaded_files: list[str] = []

        for entry in sorted(folder.iterdir()):
            if entry.is_file() and entry.suffix.lower() in cls.SUPPORTED_EXTENSIONS:
                try:
                    targets = cls.load_file(entry)
                    if targets:
                        all_targets.extend(targets)
                        loaded_files.append(entry.name)
                except Exception:
                    # Continue scanning remaining files if a single file is corrupt
                    continue

        return cls.deduplicate_targets(all_targets), loaded_files

    @classmethod
    def load_file(cls, file_path: str | Path) -> list[Target]:
        path = Path(file_path)
        if not path.is_file():
            return []

        suffix = path.suffix.lower()
        if suffix == ".txt":
            return cls._parse_txt(path)
        elif suffix == ".csv":
            return cls._parse_csv(path)
        elif suffix == ".xlsx":
            return cls._parse_xlsx(path)
        elif suffix == ".xls":
            return cls._parse_xls(path)
        elif suffix in (".sqlite", ".db"):
            return cls._parse_sqlite(path)

        return []

    @classmethod
    def deduplicate_targets(cls, targets: Sequence[Target]) -> list[Target]:
        """
        Deduplicates targets while strictly preserving insertion order and source provenance.
        Keying by (target_type, host) ensures IPv4 literals, IPv6 canonicals,
        and domain names do not collide.
        """
        seen: set[tuple[TargetType, str]] = set()
        deduped: list[Target] = []

        for t in targets:
            key = (t.target_type, t.host)
            if key not in seen:
                seen.add(key)
                deduped.append(t)

        return deduped

    @staticmethod
    def _parse_txt(path: Path) -> list[Target]:
        targets: list[Target] = []
        # Support both UTF-8 (with/without BOM) and Latin-1 fallback
        try:
            content = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            content = path.read_text(encoding="latin-1", errors="replace")

        for line in content.splitlines():
            target = Target.from_string(line, source_file=path.name)
            if target:
                targets.append(target)

        return targets

    @staticmethod
    def _parse_csv(path: Path) -> list[Target]:
        targets: list[Target] = []
        try:
            with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
                reader = csv.reader(f)
                header_checked = False
                target_col_idx: int | None = None

                for row in reader:
                    if not row:
                        continue

                    # Heuristic column detection for CSV headers
                    if not header_checked:
                        header_checked = True
                        for idx, cell in enumerate(row):
                            lower = cell.strip().lower()
                            if lower in ("ip", "host", "target", "domain", "address", "endpoint"):
                                target_col_idx = idx
                                break
                        if target_col_idx is not None:
                            continue

                    if target_col_idx is not None and target_col_idx < len(row):
                        candidate = row[target_col_idx]
                        t = Target.from_string(candidate, source_file=path.name)
                        if t:
                            targets.append(t)
                    else:
                        # Scan all cells in the row if no explicit header column was identified
                        for cell in row:
                            t = Target.from_string(cell, source_file=path.name)
                            if t:
                                targets.append(t)
                                break
        except OSError:
            pass

        return targets

    @staticmethod
    def _parse_xlsx(path: Path) -> list[Target]:
        targets: list[Target] = []
        try:
            import openpyxl

            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            for sheet in wb.worksheets:
                for row in sheet.iter_rows(values_only=True):
                    if not row:
                        continue
                    for cell_val in row:
                        if cell_val is not None:
                            val_str = str(cell_val).strip()
                            t = Target.from_string(val_str, source_file=path.name)
                            if t:
                                targets.append(t)
                                break
            wb.close()
        except Exception:
            pass

        return targets

    @staticmethod
    def _parse_xls(path: Path) -> list[Target]:
        targets: list[Target] = []
        try:
            import xlrd

            wb = xlrd.open_workbook(str(path))
            for sheet in wb.sheets():
                for row_idx in range(sheet.nrows):
                    row_vals = sheet.row_values(row_idx)
                    for val in row_vals:
                        if val is not None:
                            val_str = str(val).strip()
                            # xlrd floats (e.g. integers stored as floats in legacy spreadsheets)
                            if val_str.endswith(".0") and not Target._is_raw_ipv6(val_str):
                                val_str = val_str[:-2]
                            t = Target.from_string(val_str, source_file=path.name)
                            if t:
                                targets.append(t)
                                break
        except Exception:
            pass

        return targets

    @staticmethod
    def _parse_sqlite(path: Path) -> list[Target]:
        targets: list[Target] = []
        try:
            conn = sqlite3.connect(str(path))
            cursor = conn.cursor()

            # Retrieve user-defined tables, ignoring internal sqlite tables
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
            )
            tables = [row[0] for row in cursor.fetchall()]

            for tbl in tables:
                cursor.execute(f"PRAGMA table_info('{tbl}');")
                columns_info = cursor.fetchall()
                col_names = [col[1] for col in columns_info]

                # Identify potential target columns by name
                target_col = None
                for name in col_names:
                    lower = name.lower()
                    if lower in ("target", "ip", "host", "domain", "address", "endpoint", "resolved_ip"):
                        target_col = name
                        break

                if target_col:
                    cursor.execute(f"SELECT [{target_col}] FROM [{tbl}] WHERE [{target_col}] IS NOT NULL;")
                    for row in cursor.fetchall():
                        val = str(row[0])
                        t = Target.from_string(val, source_file=path.name)
                        if t:
                            targets.append(t)
                else:
                    # Scan all rows and columns up to a safe batch limit
                    cursor.execute(f"SELECT * FROM [{tbl}] LIMIT 10000;")
                    for row in cursor.fetchall():
                        for cell in row:
                            if cell is not None:
                                t = Target.from_string(str(cell), source_file=path.name)
                                if t:
                                    targets.append(t)
                                    break
            conn.close()
        except sqlite3.Error:
            pass

        return targets
