"""pytest 公共 fixture。"""

import pytest


@pytest.fixture
def project_root():
    """myTest 根目录。"""
    from pdd_agent.paths import PROJECT_ROOT

    return PROJECT_ROOT
