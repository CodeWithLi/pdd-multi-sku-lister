"""pytest 公共 fixture。"""

import pytest


@pytest.fixture
def project_root():
    from dy_agent.paths import PROJECT_ROOT

    return PROJECT_ROOT
