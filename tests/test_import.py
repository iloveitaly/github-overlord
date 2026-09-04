"""Test github-overlord."""

import github_overlord


def test_import() -> None:
    """Test that the package can be imported."""
    assert isinstance(github_overlord.__name__, str)


def test_version() -> None:
    """Test that the version is available."""
    assert isinstance(github_overlord.__version__, str)
