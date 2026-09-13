"""Tests for the outflows categories.txt loader (legacy + typed formats)."""

import pytest

from abicus.apps.outflows.categories import (
    DEFAULT_TYPE,
    load_categories,
    load_category_types,
)


def write(tmp_path, text):
    p = tmp_path / "categories.txt"
    p.write_text(text)
    return p


# ---------------------------------------------------------------- legacy format


def test_legacy_format(tmp_path):
    p = write(tmp_path, "Groceries\nMortgage,exclude\n\n# comment\nMisc\n")
    all_cats, excluded = load_categories(p)
    assert all_cats == {"Groceries", "Mortgage", "Misc"}
    assert excluded == {"Mortgage"}


def test_legacy_lines_default_type(tmp_path):
    p = write(tmp_path, "Groceries\nMortgage,exclude\n")
    assert load_category_types(p) == {
        "Groceries": DEFAULT_TYPE,
        "Mortgage": DEFAULT_TYPE,
    }


# ----------------------------------------------------------------- typed format


def test_typed_format(tmp_path):
    p = write(tmp_path, "Groceries,V\nMortgage,F,exclude\nUnknown,NA\n")
    all_cats, excluded = load_categories(p)
    assert all_cats == {"Groceries", "Mortgage", "Unknown"}
    assert excluded == {"Mortgage"}
    assert load_category_types(p) == {
        "Groceries": "V",
        "Mortgage": "F",
        "Unknown": "NA",
    }


def test_na_does_not_imply_excluded(tmp_path):
    p = write(tmp_path, "Unknown,NA\nTransfer,NA,exclude\n")
    _, excluded = load_categories(p)
    assert excluded == {"Transfer"}


def test_mixed_formats(tmp_path):
    p = write(tmp_path, "Groceries,V\nMisc\nFees,exclude\n")
    all_cats, excluded = load_categories(p)
    assert all_cats == {"Groceries", "Misc", "Fees"}
    assert excluded == {"Fees"}
    types = load_category_types(p)
    assert types["Groceries"] == "V"
    assert types["Misc"] == DEFAULT_TYPE
    assert types["Fees"] == DEFAULT_TYPE


def test_flags_case_insensitive(tmp_path):
    p = write(tmp_path, "Groceries,v\nMortgage,f,EXCLUDE\n")
    _, excluded = load_categories(p)
    assert excluded == {"Mortgage"}
    assert load_category_types(p) == {"Groceries": "V", "Mortgage": "F"}


# -------------------------------------------------------------------- rejection


@pytest.mark.parametrize(
    "line",
    [
        "Groceries,bogus",  # unknown flag
        "Groceries,V,F",  # duplicate type
        "Groceries,exclude,exclude",  # duplicate exclude
        "Groceries,V,exclude,extra",  # too many columns
        ",V",  # empty category name
    ],
)
def test_malformed_lines_rejected(tmp_path, line):
    p = write(tmp_path, line + "\n")
    with pytest.raises(ValueError):
        load_categories(p)


def test_duplicate_category_rejected(tmp_path):
    p = write(tmp_path, "Groceries,V\nGroceries,F\n")
    with pytest.raises(ValueError):
        load_categories(p)


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_categories(tmp_path / "nope.txt")


def test_empty_file(tmp_path):
    p = write(tmp_path, "# only comments\n\n")
    with pytest.raises(ValueError):
        load_categories(p)


# ------------------------------------------------------------------- real files


def test_shipped_config_loads():
    all_cats, excluded = load_categories()
    types = load_category_types()
    assert all_cats
    assert excluded <= all_cats
    assert set(types) == all_cats
