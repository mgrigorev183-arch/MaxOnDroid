import json
import sys
from pathlib import Path

import pytest

from maxondroid.core.adb import AdbRunner

FAKE_ADB = Path(__file__).with_name("fake_adb.py")


class FakeAdb:
    def __init__(self, folder: Path, monkeypatch):
        self.folder = folder
        self.scenario = folder / "scenario.json"
        self.log = folder / "calls.jsonl"
        monkeypatch.setenv("FAKE_ADB_SCENARIO", str(self.scenario))
        monkeypatch.setenv("FAKE_ADB_LOG", str(self.log))
        self.set_rules([])
        self.runner = AdbRunner([sys.executable, str(FAKE_ADB)])

    def set_rules(self, rules):
        for counter in self.folder.glob("scenario.json.count*"):
            counter.unlink()
        self.scenario.write_text(json.dumps({"rules": rules}), encoding="utf-8")

    def calls(self):
        if not self.log.exists():
            return []
        calls = []
        for line in self.log.read_text(encoding="utf-8").splitlines():
            try:
                calls.append(json.loads(line))
            except ValueError:
                continue  # a fake adb process is still writing this line (tests poll while it runs)
        return calls


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("MAXONDROID_HOME", str(home))
    return home


@pytest.fixture
def fake_adb(tmp_path, monkeypatch):
    folder = tmp_path / "fakeadb"
    folder.mkdir()
    return FakeAdb(folder, monkeypatch)
