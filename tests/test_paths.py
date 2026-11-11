from maxondroid.core import paths

FAMILY = "PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0"


def make_env(tmp_path):
    roaming = tmp_path / "AppData" / "Roaming"
    local = tmp_path / "AppData" / "Local"
    roaming.mkdir(parents=True)
    local.mkdir(parents=True)
    return {"APPDATA": str(roaming), "LOCALAPPDATA": str(local)}, roaming, local


def test_store_python_folders_map_to_the_real_location(tmp_path):
    env, roaming, local = make_env(tmp_path)
    real_presets = local / "Packages" / FAMILY / "LocalCache" / "Roaming" / "MaxOnDroid" / "presets"
    real_presets.mkdir(parents=True)
    real_logs = local / "Packages" / FAMILY / "LocalCache" / "Local" / "MaxOnDroid" / "logs"
    real_logs.mkdir(parents=True)
    assert paths.explorer_path(roaming / "MaxOnDroid" / "presets", FAMILY, env) == real_presets
    assert paths.explorer_path(local / "MaxOnDroid" / "logs", FAMILY, env) == real_logs


def test_paths_stay_when_not_packaged_or_not_redirected(tmp_path):
    env, roaming, local = make_env(tmp_path)
    target = roaming / "MaxOnDroid" / "presets"
    assert paths.explorer_path(target, None, env) == target  # ordinary Python
    assert paths.explorer_path(target, "", env) == target
    assert paths.explorer_path(target, FAMILY, env) == target  # packaged, but the folder was never redirected
    documents = tmp_path / "Documents" / "MaxOnDroid"
    assert paths.explorer_path(documents, FAMILY, env) == documents  # outside AppData
    already = local / "Packages" / FAMILY / "LocalCache" / "Local" / "x"
    assert paths.explorer_path(already, FAMILY, env) == already


def test_package_family_name_is_none_off_windows():
    import sys

    if sys.platform != "win32":
        assert paths.package_family_name() is None
