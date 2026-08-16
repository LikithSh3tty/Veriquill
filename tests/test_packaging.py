import veriquill


def test_package_exposes_version():
    assert isinstance(veriquill.__version__, str)
    assert veriquill.__version__ != ""
