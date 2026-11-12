"""The measurement of the guidance gap."""

from __future__ import annotations

from app.cli.guidance_audit import build_report, load_catalogue


def test_the_catalogue_is_not_empty() -> None:
    """A catalogue of nothing would report full coverage of nothing."""
    catalogue = load_catalogue()
    assert catalogue, "the detector catalogue is empty"
    for entry in catalogue:
        assert entry["detector_id"].startswith("slither.")
        assert entry["check"]


def test_the_report_says_what_is_missing() -> None:
    """The gap is measured, not remembered."""
    report = build_report()
    catalogue = {entry["detector_id"] for entry in load_catalogue()}

    assert report["catalogue"] == len(catalogue)
    assert report["with_guidance"] <= report["catalogue"]
    assert set(report["missing"]) <= catalogue
    assert report["with_guidance"] == report["catalogue"] - len(report["missing"])


def test_every_slither_guidance_names_a_real_detector() -> None:
    """A typo in a detector id would otherwise sit in the seed for ever."""
    report = build_report()
    assert report["unknown"] == []
