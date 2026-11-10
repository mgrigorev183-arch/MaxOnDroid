"""A stand-in for adb used by the tests.

Usage: ``python fake_adb.py <adb arguments...>`` with ``FAKE_ADB_SCENARIO``
pointing at a JSON file::

    {"rules": [
        {"args": ["devices", "-l"], "stdout": "...", "rc": 0},
        {"args": ["-s", "SERIAL", "shell", "*"], "stdout": "..."},
        {"args": ["mdns", "services"], "responses": [{"stdout": ""}, {"stdout": "..."}]}
    ]}

``*`` as the last element matches any remaining arguments. ``responses`` are
returned one per call (the last one repeats). Every call is appended to
``FAKE_ADB_LOG`` as one JSON array per line so tests can check the exact argv.
Unknown commands exit 1 with "fake adb: no rule".
"""

import json
import os
import sys
import time
from pathlib import Path


def matches(pattern, args):
    if pattern and pattern[-1] == "*":
        head = pattern[:-1]
        return args[: len(head)] == head
    return pattern == args


def main(argv):
    scenario_path = Path(os.environ["FAKE_ADB_SCENARIO"])
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    log_path = os.environ.get("FAKE_ADB_LOG")
    if log_path:
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(argv, ensure_ascii=False) + "\n")
    for index, rule in enumerate(scenario.get("rules", [])):
        if not matches(rule["args"], argv):
            continue
        response = rule
        if "responses" in rule:
            counter = scenario_path.with_name(scenario_path.name + f".count{index}")
            count = int(counter.read_text()) if counter.exists() else 0
            counter.write_text(str(count + 1))
            responses = rule["responses"]
            response = responses[min(count, len(responses) - 1)]
        if response.get("sleep"):
            time.sleep(response["sleep"])
        sys.stdout.buffer.write(response.get("stdout", "").encode("utf-8"))
        sys.stderr.buffer.write(response.get("stderr", "").encode("utf-8"))
        return int(response.get("rc", 0))
    sys.stderr.write("fake adb: no rule for " + " ".join(argv) + "\n")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
