"""Local model discovery and resolver helpers.

This is a Ghost-native absorption of the useful OpenDrop local-model ideas:
hardware posture, HF/local source resolution, license posture, and preview-only
inventory.  It performs no downloads, conversion, serving, scraping, or
training.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

MODEL_EXTENSIONS = {".gguf", ".safetensors"}
OPEN_LICENSES = {"apache-2.0", "mit", "cc-by-4.0", "cc-by-sa-4.0", "openrail", "gemma", "mistral", "llama3"}


@dataclass(frozen=True)
class HardwareProfile:
    ram_mb: int = 0
    free_ram_mb: int = 0
    usable_vram_mb: int = 0
    cpu_cores: int = 1
    cpu_arch: str = ""
    gpu_kind: str = "none"
    gpu_name: str = ""
    os_name: str = ""

    @property
    def effective_memory_mb(self) -> int:
        if self.usable_vram_mb > 0:
            return self.usable_vram_mb
        if self.free_ram_mb > 0:
            return int(self.free_ram_mb * 0.60)
        return int(self.ram_mb * 0.50)

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["effective_memory_mb"] = self.effective_memory_mb
        return payload


@dataclass(frozen=True)
class LocalModelCandidate:
    source: str
    source_type: str
    model_id: str = ""
    display_name: str = ""
    local_path: str = ""
    file_type: str = ""
    quantization: str = ""
    compatibility_status: str = "candidate"
    license_id: str = ""
    license_warning: str = ""
    auto_download: bool = False
    auto_activate: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def detect_hardware_profile() -> HardwareProfile:
    """Return a best-effort hardware profile using only stdlib probes."""

    ram_mb, free_ram_mb = _memory_mb()
    gpu_kind, gpu_name, vram = _gpu_probe()
    return HardwareProfile(
        ram_mb=ram_mb,
        free_ram_mb=free_ram_mb,
        usable_vram_mb=vram,
        cpu_cores=os.cpu_count() or 1,
        cpu_arch=platform.machine(),
        gpu_kind=gpu_kind,
        gpu_name=gpu_name,
        os_name=platform.system(),
    )


def resolve_model_source(source: str, *, license_id: str = "") -> LocalModelCandidate:
    """Resolve a HF URL/model ID/local file into a preview-only candidate."""

    raw = str(source or "").strip()
    if not raw:
        return LocalModelCandidate(source=raw, source_type="unknown", compatibility_status="invalid")
    parsed = urlparse(raw)
    warning = license_warning(license_id)
    if parsed.netloc in {"huggingface.co", "hf.co"}:
        model_id = _hf_model_id_from_url(raw)
        filename = Path(parsed.path).name
        is_file = _is_model_file(filename) or "/resolve/" in parsed.path
        return LocalModelCandidate(
            source=raw,
            source_type="huggingface_file" if is_file else "huggingface_model",
            model_id=model_id or "",
            display_name=model_id or raw,
            file_type=Path(filename).suffix.lower().lstrip(".") if filename else "",
            quantization=_parse_quant(filename),
            compatibility_status="candidate",
            license_id=license_id,
            license_warning=warning,
        )
    if re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.:-]+$", raw):
        return LocalModelCandidate(
            source=raw,
            source_type="huggingface_model",
            model_id=raw,
            display_name=raw,
            compatibility_status="candidate",
            license_id=license_id,
            license_warning=warning,
        )
    path = Path(raw).expanduser()
    if path.exists() and path.is_file() and path.suffix.lower() in MODEL_EXTENSIONS:
        suffix = path.suffix.lower().lstrip(".")
        return LocalModelCandidate(
            source=raw,
            source_type=f"local_{suffix}",
            model_id=path.stem,
            display_name=path.name,
            local_path=str(path),
            file_type=suffix,
            quantization=_parse_quant(path.name),
            compatibility_status="ready",
            license_id=license_id,
            license_warning=warning,
        )
    return LocalModelCandidate(
        source=raw,
        source_type="local_path",
        model_id=path.stem,
        display_name=path.name or raw,
        local_path=str(path),
        compatibility_status="missing",
        license_id=license_id,
        license_warning=warning,
    )


def discover_local_model_inventory(roots: list[str | Path] | None = None) -> dict[str, object]:
    """Scan approved local roots for model files and return preview candidates."""

    scan_roots = _candidate_roots(roots)
    candidates: list[LocalModelCandidate] = []
    scanned: list[str] = []
    for root in scan_roots:
        if not root.exists() or not root.is_dir():
            continue
        scanned.append(str(root))
        for ext in MODEL_EXTENSIONS:
            for file_path in root.rglob(f"*{ext}"):
                candidates.append(resolve_model_source(str(file_path)))
    models = sorted((candidate.to_dict() for candidate in candidates), key=lambda item: str(item["display_name"]))
    return {
        "ok": True,
        "policy": {
            "activation": "preview_only",
            "requires_user_approval": True,
            "auto_download": False,
            "auto_training": False,
        },
        "hardware": detect_hardware_profile().to_dict(),
        "search_roots": [str(root) for root in scan_roots],
        "scanned_roots": scanned,
        "count": len(models),
        "models": models,
    }


def recommend_quantization(params_b: float, hardware: HardwareProfile | None = None) -> str:
    """Recommend a conservative quantization label for a parameter count."""

    hw = hardware or detect_hardware_profile()
    memory_gb = hw.effective_memory_mb / 1024
    params = max(0.1, float(params_b))
    if memory_gb >= params * 2.4:
        return "F16"
    if memory_gb >= params * 1.2:
        return "Q8_0"
    if memory_gb >= params * 0.9:
        return "Q6_K"
    if memory_gb >= params * 0.65:
        return "Q5_K_M"
    return "Q4_K_M"


def license_warning(license_id: str) -> str:
    license_text = str(license_id or "").strip().lower()
    if not license_text:
        return "License unspecified; review the source model card before commercial or redistributed use."
    if license_text in OPEN_LICENSES:
        return ""
    if "gpl" in license_text or "agpl" in license_text:
        return f"License {license_id!r} may impose copyleft obligations; review before redistribution."
    return f"License {license_id!r} should be reviewed before use."


def _candidate_roots(roots: list[str | Path] | None) -> list[Path]:
    raw = roots or [Path.cwd() / "models", Path.home() / ".cache" / "ghostchimera" / "models", Path("D:/models")]
    deduped: list[Path] = []
    seen: set[str] = set()
    for root in raw:
        path = Path(root).expanduser()
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            deduped.append(path)
    return deduped


def _hf_model_id_from_url(url: str) -> str | None:
    path = urlparse(url).path.strip("/")
    parts = path.split("/")
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return None


def _is_model_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in MODEL_EXTENSIONS


def _parse_quant(filename: str) -> str:
    for pattern in (r"\.(Q\d+_K_[MSL])", r"\.(Q\d+_K)", r"\.(Q\d+_\d+)", r"\.(Q\d+)", r"\.(IQ\d+_\w+)"):
        match = re.search(pattern, filename, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper()
    if re.search(r"\.(fp16|f16)", filename, flags=re.IGNORECASE):
        return "F16"
    return ""


def _memory_mb() -> tuple[int, int]:
    if platform.system() == "Linux":
        try:
            data = Path("/proc/meminfo").read_text(encoding="ascii")
            total = _meminfo_value(data, "MemTotal")
            available = _meminfo_value(data, "MemAvailable") or total
            return total, available
        except OSError:
            pass
    return 0, 0


def _meminfo_value(data: str, key: str) -> int:
    match = re.search(rf"^{re.escape(key)}:\s+(\d+)", data, flags=re.MULTILINE)
    return int(match.group(1)) // 1024 if match else 0


def _gpu_probe() -> tuple[str, str, int]:
    if shutil.which("nvidia-smi"):
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                name, _, memory = result.stdout.strip().splitlines()[0].partition(",")
                return "nvidia", name.strip(), int(memory.strip() or "0")
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    if shutil.which("rocm-smi"):
        return "amd", "AMD GPU", 0
    return "none", "No GPU detected", 0


__all__ = [
    "HardwareProfile",
    "LocalModelCandidate",
    "detect_hardware_profile",
    "discover_local_model_inventory",
    "license_warning",
    "recommend_quantization",
    "resolve_model_source",
]
