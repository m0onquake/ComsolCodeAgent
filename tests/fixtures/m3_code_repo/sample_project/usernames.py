"""Small deliberately defective module used only by M3 acceptance tests."""


def normalize_username(value: str) -> str:
    return value.strip()
