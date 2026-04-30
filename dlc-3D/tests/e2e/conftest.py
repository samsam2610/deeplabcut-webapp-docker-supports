import pytest

@pytest.fixture(scope="session")
def base_url():
    return "http://172.26.0.5:5050/dlc-3d/"
