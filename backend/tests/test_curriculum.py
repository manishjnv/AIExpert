"""Tests for plan template loader (Task 4.1).

AC: Loading the template produces a typed object with 24 weeks.
"""

from app.curriculum.loader import load_template, list_templates


def test_load_generalist_template():
    tpl = load_template("generalist_6mo_intermediate")
    assert tpl.key == "generalist_6mo_intermediate"
    assert tpl.version == "1.0"
    assert tpl.duration_months == 6
    assert tpl.total_weeks == 24
    assert len(tpl.months) == 6


def test_template_has_checks():
    tpl = load_template("generalist_6mo_intermediate")
    assert tpl.total_checks > 100  # 24 weeks * ~5 checks each


def test_week_by_number():
    tpl = load_template("generalist_6mo_intermediate")
    w1 = tpl.week_by_number(1)
    assert w1 is not None
    assert w1.t == "Python, SQL & Dev Environment"
    w24 = tpl.week_by_number(24)
    assert w24 is not None
    assert "Resume" in w24.t


def test_all_weeks_have_resources():
    tpl = load_template("generalist_6mo_intermediate")
    for m in tpl.months:
        for w in m.weeks:
            assert len(w.resources) > 0, f"Week {w.n} has no resources"
            assert len(w.checks) > 0, f"Week {w.n} has no checks"


def test_list_templates():
    keys = list_templates()
    assert "generalist_6mo_intermediate" in keys
