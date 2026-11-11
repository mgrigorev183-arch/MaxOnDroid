"""Installing APKs and split bundles, and saving installed apps as files.

Bundles (``.apks`` from bundletool or SAI, ``.xapk``, ``.apkm``) are zip files
with several APKs inside. We extract only the ``.apk`` entries, by base name,
into a fresh temporary folder (no path from the archive is ever used), pick
the splits that match the device, and run ``adb install-multiple``.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from maxondroid.core.adb import AdbResult, AdbRunner
from maxondroid.core.packages import apk_paths, check_package

APK_SUFFIXES = (".apk",)
BUNDLE_SUFFIXES = (".apks", ".xapk", ".apkm")
INSTALLABLE_SUFFIXES = APK_SUFFIXES + BUNDLE_SUFFIXES

MAX_ENTRIES = 300
MAX_TOTAL_BYTES = 8 * 1024**3  # a bundle larger than this is not an app
INSTALL_TIMEOUT = 900.0

ABI_TOKENS = ("arm64_v8a", "armeabi_v7a", "armeabi", "x86_64", "x86", "mips64", "mips")
DPI_VALUES = {"ldpi": 120, "mdpi": 160, "tvdpi": 213, "hdpi": 240, "xhdpi": 320, "xxhdpi": 480, "xxxhdpi": 640}


class BundleError(RuntimeError):
    """``code`` is a stable key the UI translates."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def is_installable(path: Path) -> bool:
    return path.suffix.lower() in INSTALLABLE_SUFFIXES


def _tokens(name: str) -> list[str]:
    stem = Path(name).stem.lower().replace("-", ".")
    return [t for t in re.split(r"[.]", stem) if t]


def _abi_of(name: str) -> str | None:
    tokens = _tokens(name)
    for abi in ABI_TOKENS:
        if abi in tokens:
            return abi
    return None


def _dpi_of(name: str) -> str | None:
    tokens = _tokens(name)
    for dpi in DPI_VALUES:
        if dpi in tokens:
            return dpi
    return None


def choose_splits(names: list[str], abis: tuple[str, ...], density: int | None) -> list[str]:
    """Keep the base, language and feature splits; one ABI split and one density split."""
    device_abis = [a.replace("-", "_").lower() for a in abis]
    abi_splits = {n: _abi_of(n) for n in names if _abi_of(n)}
    dpi_splits = {n: _dpi_of(n) for n in names if _dpi_of(n) and n not in abi_splits}
    chosen = [n for n in names if n not in abi_splits and n not in dpi_splits]

    if abi_splits:
        for abi in device_abis:
            match = [n for n, a in abi_splits.items() if a == abi]
            if match:
                chosen += match
                break
        else:
            raise BundleError("no_matching_abi", ", ".join(sorted(set(abi_splits.values()))))

    if dpi_splits:
        target = density or DPI_VALUES["xhdpi"]
        available = sorted({d for d in dpi_splits.values()}, key=lambda d: DPI_VALUES[d])
        at_least = [d for d in available if DPI_VALUES[d] >= target]
        pick = at_least[0] if at_least else available[-1]
        chosen += [n for n, d in dpi_splits.items() if d == pick]
    if not any(n not in abi_splits and n not in dpi_splits for n in chosen):
        raise BundleError("no_base")
    return chosen


def _safe_name(name: str, used: set[str]) -> str:
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(name.replace("\\", "/")).name) or "split.apk"
    if not base.lower().endswith(".apk"):
        base += ".apk"
    candidate, index = base, 1
    while candidate.lower() in used:
        candidate = f"{Path(base).stem}-{index}.apk"
        index += 1
    used.add(candidate.lower())
    return candidate


def extract_bundle(bundle: Path, folder: Path) -> list[Path]:
    """Write the bundle's APKs into ``folder`` by base name only. Returns their paths."""
    try:
        archive = zipfile.ZipFile(bundle)
    except (zipfile.BadZipFile, OSError) as exc:
        raise BundleError("bad_bundle", str(exc)) from exc
    with archive:
        entries = [i for i in archive.infolist() if not i.is_dir() and i.filename.lower().endswith(".apk")]
        if not entries:
            raise BundleError("no_apks")
        if len(entries) > MAX_ENTRIES:
            raise BundleError("too_many_entries", str(len(entries)))
        if sum(i.file_size for i in entries) > MAX_TOTAL_BYTES:
            raise BundleError("too_large")
        if any(i.flag_bits & 0x1 for i in entries):
            raise BundleError("encrypted")
        used: set[str] = set()
        out = []
        for info in entries:
            target = folder / _safe_name(info.filename, used)
            with archive.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
            out.append(target)
        return out


@dataclass(frozen=True)
class InstallResult:
    ok: bool
    file: Path
    error_code: str | None  # INSTALL_FAILED_... or a BundleError code
    message: str
    installed: tuple[str, ...] = ()
    result: AdbResult | None = None


_FAILURE = re.compile(r"\b(INSTALL_[A-Z_]+|DELETE_[A-Z_]+)\b")


def parse_install_output(text: str) -> tuple[bool, str | None]:
    if any(line.strip() == "Success" for line in text.splitlines()):
        return True, None
    match = _FAILURE.search(text)
    return False, match.group(1) if match else "UNKNOWN"


def install_files(runner: AdbRunner, serial: str, apks: list[Path], log_name: Path) -> InstallResult:
    if len(apks) == 1:
        args = ["install", "-r", str(apks[0])]
    else:
        args = ["install-multiple", "-r", *[str(p) for p in apks]]
    result = runner.run(args, serial=serial, timeout=INSTALL_TIMEOUT)
    ok, code = parse_install_output(result.output)
    if result.timed_out:
        ok, code = False, "TIMEOUT"
    return InstallResult(ok, log_name, code, result.display_output().strip(), tuple(p.name for p in apks), result)


def install(
    runner: AdbRunner,
    serial: str,
    file: Path,
    abis: tuple[str, ...] = (),
    density: int | None = None,
    temp_root: Path | None = None,
) -> InstallResult:
    suffix = file.suffix.lower()
    if suffix not in INSTALLABLE_SUFFIXES:
        return InstallResult(False, file, "unsupported_file", file.name)
    if not file.is_file():
        return InstallResult(False, file, "missing_file", str(file))
    if suffix in APK_SUFFIXES:
        return install_files(runner, serial, [file], file)
    folder = Path(tempfile.mkdtemp(prefix="maxondroid-", dir=temp_root))
    try:
        try:
            extracted = extract_bundle(file, folder)
            by_name = {p.name: p for p in extracted}
            chosen = choose_splits(list(by_name), abis, density)
        except BundleError as err:
            return InstallResult(False, file, err.code, err.detail)
        return install_files(runner, serial, [by_name[n] for n in chosen], file)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# --- saving an installed app as a file ---------------------------------------------


@dataclass(frozen=True)
class ExtractResult:
    ok: bool
    file: Path | None
    message: str


def _windows_safe(text: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text).strip(" .")
    return cleaned[:120] or "app"


def extract_apk(
    runner: AdbRunner,
    serial: str,
    package: str,
    folder: Path,
    version: str | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ExtractResult:
    """Pull the app's APKs. One APK is saved as ``.apk``; base plus splits as one ``.apks`` file."""
    package = check_package(package)
    paths = apk_paths(runner, serial, package)
    if not paths:
        return ExtractResult(False, None, "pm path: not found")
    folder.mkdir(parents=True, exist_ok=True)
    stem = _windows_safe(f"{package}-{version}" if version else package)
    work = Path(tempfile.mkdtemp(prefix="maxondroid-pull-", dir=folder))
    try:
        pulled = []
        used: set[str] = set()
        for index, remote in enumerate(paths):
            local = work / _safe_name(remote.rsplit("/", 1)[-1], used)
            result = runner.run(["pull", remote, str(local)], serial=serial, timeout=600)
            if not result.ok or not local.is_file():
                return ExtractResult(False, None, result.display_output().strip())
            pulled.append(local)
            if progress:
                progress(index + 1, len(paths))
        if len(pulled) == 1:
            target = _unique(folder / f"{stem}.apk")
            shutil.move(str(pulled[0]), target)
        else:
            target = _unique(folder / f"{stem}.apks")
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as bundle:
                for path in pulled:
                    bundle.write(path, arcname=path.name)
        return ExtractResult(True, target, str(target))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(path)
