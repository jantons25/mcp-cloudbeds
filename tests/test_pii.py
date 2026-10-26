import pytest

from cloudbeds_mcp import pii


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("juan.perez@gmail.com", "j***@g***.com"),
        ("ana@empresa.com.pe", "a***@e***.pe"),
        ("sinarroba", "***"),
        ("x@localhost", "x***@l***"),
        ("", ""),
        (None, None),
    ],
)
def test_mask_email(value, expected):
    assert pii.mask_email(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("+51 987 654 321", "***321"), ("(01) 555-1234", "***234"), ("12", "***"), (None, None)],
)
def test_mask_phone(value, expected):
    assert pii.mask_phone(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("12345678", "***78"), ("AB 123 456", "***56"), ("7", "***"), ("", "")],
)
def test_mask_document(value, expected):
    assert pii.mask_document(value) == expected


def test_show_pii_true_devuelve_original():
    assert pii.email("a@b.com", True) == "a@b.com"
    assert pii.phone("987654321", True) == "987654321"
    assert pii.document("12345678", True) == "12345678"


def test_show_pii_false_enmascara():
    assert "a@b.com" != pii.email("a@b.com", False)
    assert pii.phone("987654321", False) == "***321"
    assert pii.document("12345678", False) == "***78"
