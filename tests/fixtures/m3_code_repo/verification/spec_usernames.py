import pytest

from sample_project import normalize_username


def test_normalize_username_strips_and_lowercases():
    assert normalize_username("  Ada  ") == "ada"


def test_normalize_username_rejects_empty_values():
    with pytest.raises(ValueError, match="username cannot be empty"):
        normalize_username("   ")
