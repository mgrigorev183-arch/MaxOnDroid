"""Installed packages: listing them and the actions on one package.

Every package name is validated before use and every argument is quoted for
the device shell (``AdbRunner.shell``), so a package name can never become a
second command on the device.

Removal policy (agreed in the planning interview):

* system apps are removed **for the user only** with ``pm uninstall -k --user 0``;
  the APK stays on the system partition and ``cmd package install-existing``
  brings the app back;
* apps the user installed are uninstalled for real; the caller saves a copy of
  the APK first so that the change can be undone by reinstalling it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from maxondroid.core.adb import AdbResult, AdbRunner

_PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")


class InvalidPackageError(ValueError):
    pass


def check_package(name: str) -> str:
    """Accepts real Android package names only (``com.example.app``; plus the special ``android``)."""
    if name == "android" or (_PACKAGE.match(name) and len(name) <= 255):
        return name
    raise InvalidPackageError(name)


class PkgState(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    REMOVED = "removed"  # still on the device, not installed for this user


@dataclass(frozen=True)
class Package:
    name: str
    system: bool
    state: PkgState
    version_name: str | None = None
    version_code: int | None = None


@dataclass(frozen=True)
class Snapshot:
    """Everything the Apps and Debloat tabs need, read in one round trip."""

    packages: dict[str, Package]
    home: str | None = None  # package of the default launcher
    ime: str | None = None  # package of the default keyboard
    abis: tuple[str, ...] = ()
    density: int | None = None
    sdk: int | None = None
    leanback: bool = False
    extra: dict = field(default_factory=dict)

    def get(self, name: str) -> Package | None:
        return self.packages.get(name)


LIST_SCRIPT = (
    "echo @@all; pm list packages -u 2>/dev/null; "
    "echo @@installed; pm list packages 2>/dev/null; "
    "echo @@system; pm list packages -s -u 2>/dev/null; "
    "echo @@disabled; pm list packages -d 2>/dev/null; "
    "echo @@versions; dumpsys package packages 2>/dev/null | grep -E '^  Package \\[|^    versionCode=|^    versionName='; "
    "echo @@home; cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME 2>/dev/null | tail -n 1; "
    "echo @@ime; settings get secure default_input_method 2>/dev/null; "
    "echo @@abi; getprop ro.product.cpu.abilist; getprop ro.product.cpu.abi; "
    "echo @@sdk; getprop ro.build.version.sdk; "
    "echo @@density; wm density 2>/dev/null; "
    "echo @@leanback; pm has-feature android.software.leanback 2>/dev/null; "
    "echo @@end"
)


def _sections(output: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = None
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("@@") and stripped[2:].isalpha():
            current = stripped[2:]
            sections[current] = []
        elif current is not None:
            sections[current].append(line.rstrip())
    return sections


def _names(lines: list[str]) -> set[str]:
    out = set()
    for line in lines:
        line = line.strip()
        if line.startswith("package:"):
            name = line[len("package:") :].strip()
            if "=" in name:  # "-f" style "path=name" is not used, but be tolerant
                name = name.rsplit("=", 1)[-1]
            try:
                out.add(check_package(name))
            except InvalidPackageError:
                continue
    return out


_PKG_HEADER = re.compile(r"^\s*Package \[([^\]]+)\]")
_VCODE = re.compile(r"versionCode=(\d+)")
_VNAME = re.compile(r"versionName=(.*)$")


def parse_versions(lines: list[str]) -> dict[str, tuple[str | None, int | None]]:
    versions: dict[str, tuple[str | None, int | None]] = {}
    current = None
    for line in lines:
        header = _PKG_HEADER.match(line)
        if header:
            current = header.group(1)
            versions.setdefault(current, (None, None))
            continue
        if current is None:
            continue
        name, code = versions[current]
        if (match := _VCODE.search(line)) and code is None:
            code = int(match.group(1))
        if (match := _VNAME.search(line.strip())) and name is None:
            name = match.group(1).strip() or None
        versions[current] = (name, code)
    return versions


def _component_package(line: str) -> str | None:
    line = line.strip()
    if "/" not in line:
        return None
    candidate = line.split("/", 1)[0]
    try:
        return check_package(candidate)
    except InvalidPackageError:
        return None


def parse_snapshot(output: str) -> Snapshot:
    s = _sections(output)
    all_names = _names(s.get("all", [])) | _names(s.get("installed", []))
    installed = _names(s.get("installed", []))
    system = _names(s.get("system", []))
    disabled = _names(s.get("disabled", []))
    versions = parse_versions(s.get("versions", []))
    packages = {}
    for name in sorted(all_names):
        if name not in installed:
            state = PkgState.REMOVED
        elif name in disabled:
            state = PkgState.DISABLED
        else:
            state = PkgState.ENABLED
        version_name, version_code = versions.get(name, (None, None))
        packages[name] = Package(name, name in system, state, version_name, version_code)

    home = next((p for line in s.get("home", []) if (p := _component_package(line))), None)
    ime = next((p for line in s.get("ime", []) if (p := _component_package(line))), None)
    abis: list[str] = []
    for line in s.get("abi", []):
        for abi in line.strip().split(","):
            abi = abi.strip()
            if abi and abi not in abis:
                abis.append(abi)
    density = None
    for line in s.get("density", []):
        if ":" in line:
            try:
                density = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
    sdk = None
    for line in s.get("sdk", []):
        if line.strip().isdigit():
            sdk = int(line.strip())
    leanback = any(line.strip() == "true" for line in s.get("leanback", []))
    return Snapshot(packages, home, ime, tuple(abis), density, sdk, leanback)


class PackageError(RuntimeError):
    def __init__(self, result: AdbResult):
        super().__init__(result.display_output() or "adb failed")
        self.result = result


def read_snapshot(runner: AdbRunner, serial: str, log: bool = True) -> Snapshot:
    result = runner.shell_script(serial, LIST_SCRIPT, timeout=90, log=log)
    if not result.ok or "@@end" not in result.stdout:
        raise PackageError(result)
    snapshot = parse_snapshot(result.stdout)
    if not snapshot.packages:
        raise PackageError(result)
    return snapshot


# --- actions ------------------------------------------------------------------


class Action(StrEnum):
    REMOVE_FOR_USER = "remove_for_user"  # system app: pm uninstall -k --user 0
    UNINSTALL = "uninstall"  # user app: full uninstall
    DISABLE = "disable"
    ENABLE = "enable"
    RESTORE = "restore"  # install-existing
    CLEAR = "clear"
    FORCE_STOP = "force_stop"
    LAUNCH = "launch"


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    action: Action
    package: str
    message: str  # raw adb text
    result: AdbResult | None = None


def _done(action: Action, package: str, result: AdbResult, ok: bool) -> ActionResult:
    return ActionResult(ok and not result.timed_out, action, package, result.display_output().strip(), result)


def _success_word(result: AdbResult) -> bool:
    return any(line.strip() == "Success" for line in result.output.splitlines())


def remove_for_user(runner: AdbRunner, serial: str, package: str) -> ActionResult:
    package = check_package(package)
    result = runner.shell(serial, "pm", "uninstall", "-k", "--user", "0", package, timeout=60)
    return _done(Action.REMOVE_FOR_USER, package, result, _success_word(result))


def uninstall(runner: AdbRunner, serial: str, package: str) -> ActionResult:
    package = check_package(package)
    result = runner.shell(serial, "pm", "uninstall", package, timeout=60)
    return _done(Action.UNINSTALL, package, result, _success_word(result))


def disable(runner: AdbRunner, serial: str, package: str) -> ActionResult:
    package = check_package(package)
    result = runner.shell(serial, "pm", "disable-user", "--user", "0", package, timeout=30)
    return _done(Action.DISABLE, package, result, "new state: disabled" in result.output)


def enable(runner: AdbRunner, serial: str, package: str) -> ActionResult:
    package = check_package(package)
    result = runner.shell(serial, "pm", "enable", "--user", "0", package, timeout=30)
    return _done(Action.ENABLE, package, result, "new state: enabled" in result.output)


def restore(runner: AdbRunner, serial: str, package: str, sdk: int | None = None) -> ActionResult:
    """Bring back a system app removed for the user (Android 8+ uses ``cmd package``)."""
    package = check_package(package)
    tool = ["cmd", "package"] if (sdk or 26) >= 26 else ["pm"]
    result = runner.shell(serial, *tool, "install-existing", "--user", "0", package, timeout=60)
    ok = "installed for user" in result.output.lower() or _success_word(result)
    if not ok and tool[0] == "cmd":
        fallback = runner.shell(serial, "pm", "install-existing", "--user", "0", package, timeout=60)
        if "installed for user" in fallback.output.lower() or _success_word(fallback):
            return _done(Action.RESTORE, package, fallback, True)
    return _done(Action.RESTORE, package, result, ok)


def clear_data(runner: AdbRunner, serial: str, package: str) -> ActionResult:
    package = check_package(package)
    result = runner.shell(serial, "pm", "clear", "--user", "0", package, timeout=60)
    return _done(Action.CLEAR, package, result, _success_word(result))


def force_stop(runner: AdbRunner, serial: str, package: str) -> ActionResult:
    package = check_package(package)
    result = runner.shell(serial, "am", "force-stop", package, timeout=30)
    return _done(Action.FORCE_STOP, package, result, result.ok and "error" not in result.output.lower())


def launch(runner: AdbRunner, serial: str, package: str, leanback: bool = False) -> ActionResult:
    """Start the app's launcher activity (the TV launcher entry first on TVs)."""
    package = check_package(package)
    categories = ["android.intent.category.LEANBACK_LAUNCHER", "android.intent.category.LAUNCHER"] if leanback else [
        "android.intent.category.LAUNCHER",
        "android.intent.category.LEANBACK_LAUNCHER",
    ]
    result = None
    for category in categories:
        result = runner.shell(serial, "monkey", "-p", package, "-c", category, "1", timeout=30)
        if "Events injected: 1" in result.output:
            return _done(Action.LAUNCH, package, result, True)
    assert result is not None
    return _done(Action.LAUNCH, package, result, False)


def apk_paths(runner: AdbRunner, serial: str, package: str) -> list[str]:
    """Device paths of the base APK and its splits (``pm path``)."""
    package = check_package(package)
    result = runner.shell(serial, "pm", "path", package, timeout=30)
    paths = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("package:"):
            path = line[len("package:") :]
            if path.startswith("/") and path.endswith(".apk") and "\n" not in path and ".." not in path.split("/"):
                paths.append(path)
    return paths
