from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Sequence

from PySide6.QtCore import QObject, QThread, Signal

from src.core.isp_detector import IspDetector
from src.core.prober import CloudflareProber
from src.io.loader import TargetLoader
from src.models import ProbeResult, Target


class IspDetectWorker(QThread):
    """
    Executes external ASN and ISP metadata discovery asynchronously,
    preventing DNS and HTTP socket handshakes from blocking the Qt event loop.
    """

    detected = Signal(dict)
    failed = Signal(str)

    def run(self) -> None:
        try:
            info = IspDetector.detect_current_isp(timeout_s=4.0)
            self.detected.emit(info)
        except Exception as exc:
            self.failed.emit(str(exc))


class FileLoaderWorker(QThread):
    """
    Performs directory scanning and multi-format target parsing off the main UI thread.
    """

    loaded = Signal(list, list)  # (targets: list[Target], sources: list[str])

    def __init__(
        self,
        folder_path: Path | None = None,
        file_paths: Sequence[Path] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.folder_path = folder_path
        self.file_paths = file_paths

    def run(self) -> None:
        all_targets: list[Target] = []
        sources: list[str] = []

        if self.folder_path and self.folder_path.exists():
            targets, files = TargetLoader.load_directory(self.folder_path)
            all_targets.extend(targets)
            sources.extend(files)
        elif self.file_paths:
            for p in self.file_paths:
                targets = TargetLoader.load_file(p)
                all_targets.extend(targets)
                sources.append(p.name)

        deduped = TargetLoader.deduplicate_targets(all_targets)
        self.loaded.emit(deduped, sources)


class BenchmarkWorker(QThread):
    """
    Orchestrates concurrent low-level Cloudflare edge probes across a bounded thread pool.
    Exposes thread-safe pause, resume, and abort states via synchronization primitives.
    """

    target_started = Signal(str)
    result_ready = Signal(object)  # ProbeResult
    progress_updated = Signal(int, int)  # (current, total)
    throughput_sample = Signal(float)  # Current probe download speed in Mbps
    finished = Signal(list, str)  # (results: list[ProbeResult], run_id: str)
    aborted = Signal()

    def __init__(
        self,
        targets: Sequence[Target],
        operator_name: str,
        concurrency: int = 4,
        payload_bytes: int = 5_000_000,
        download_timeout_s: float = 7.0,
        sni_host: str = "speed.cloudflare.com",
        download_path: str = "/__down?bytes={bytes}",
        audit_services: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.targets = list(targets)
        self.operator_name = operator_name
        self.concurrency = max(1, min(concurrency, 16))
        self.payload_bytes = payload_bytes
        self.download_timeout_s = download_timeout_s
        self.sni_host = sni_host
        self.download_path = download_path
        self.audit_services = audit_services

        self._abort_flag = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Not paused initially

        self._run_id = f"run_{uuid.uuid4().hex[:12]}"
        self._results: list[ProbeResult] = []

    def pause(self) -> None:
        self._pause_event.clear()

    def resume(self) -> None:
        self._pause_event.set()

    def abort(self) -> None:
        self._abort_flag.set()
        self._pause_event.set()  # Unblock thread if paused so it can cleanly exit

    @property
    def is_paused(self) -> bool:
        return not self._pause_event.is_set()

    def run(self) -> None:
        prober = CloudflareProber(
            payload_bytes=self.payload_bytes,
            connect_timeout_s=3.5,
            download_timeout_s=self.download_timeout_s,
            jitter_probes=3,
            sni_host=self.sni_host,
            download_path=self.download_path,
            audit_services=self.audit_services,
        )

        total_targets = len(self.targets)
        completed_count = 0

        # Execute bounded worker pool
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            future_to_target = {}
            for target in self.targets:
                if self._abort_flag.is_set():
                    break
                fut = executor.submit(
                    self._probe_task, prober, target, self.operator_name
                )
                future_to_target[fut] = target

            for future in as_completed(future_to_target):
                if self._abort_flag.is_set():
                    break

                # Block execution if user pressed Pause
                self._pause_event.wait()

                try:
                    target_results = future.result()
                    for res in target_results:
                        self._results.append(res)
                        self.result_ready.emit(res)
                        if res.download_mbps > 0:
                            self.throughput_sample.emit(res.download_mbps)
                except Exception:
                    pass

                completed_count += 1
                self.progress_updated.emit(completed_count, total_targets)

        if self._abort_flag.is_set():
            self.aborted.emit()
        else:
            self.finished.emit(self._results, self._run_id)

    def _probe_task(
        self, prober: CloudflareProber, target: Target, operator_name: str
    ) -> list[ProbeResult]:
        self._pause_event.wait()
        if self._abort_flag.is_set():
            return []

        self.target_started.emit(target.host)
        return prober.probe(
            target=target,
            operator_name=operator_name,
            cancel_check=self._abort_flag.is_set,
        )
