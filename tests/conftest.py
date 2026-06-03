import pathlib


def pytest_ignore_collect(collection_path: pathlib.Path, config) -> bool:
    # Live smoke scripts hit real endpoints; run them manually, not in CI.
    return "tests/scripts" in str(collection_path)
