"""Smoke test: verify that the policyfuzz package is importable."""


def test_import_policyfuzz():
    """Phase 0 acceptance: the package is installed and importable."""
    import policyfuzz
    assert policyfuzz.__doc__ is not None
