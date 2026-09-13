"""Classifier tests. Cases are abridged from real SWE-bench Verified issues
that the first rule set labelled wrongly."""

from src.evaluation.problem_types import STRATUM_TYPES, OTHER, classify


def test_feature_request_asking_for_an_error_is_not_a_crash():
    # pallets__flask-5014
    text = (
        "Require a non-empty name for Blueprints\n"
        "Things do not work correctly if a Blueprint is given an empty name "
        "(e.g. #4944). It would be helpful if a `ValueError` was raised when "
        "trying to do that."
    )
    assert classify(text) == "api-behavior"


def test_issue_template_boilerplate_is_ignored():
    # pydata__xarray-4075: the MCVE template comment used to drive the label.
    text = (
        "[bug] when passing boolean weights to weighted mean\n"
        "<!-- In order for the maintainers to efficiently understand and "
        "prioritize issues, we ask you post a Minimal, Complete and Verifiable "
        "Example (MCVE). See guidelines on how the output is rendered. -->\n"
        "The weighted mean returns an incorrect result when weights are boolean."
    )
    assert classify(text) == "wrong-output"


def test_code_sample_contents_do_not_drive_the_label():
    # pylint-dev__pylint-4604: the repro contains '\"\"\"Docstring.\"\"\"'.
    text = (
        "unused-import false positive for a module used in a type comment\n"
        "### Steps to reproduce\n"
        '```python\n"""Docstring."""\nimport abc\nX = ...  # type: abc.ABC\n```\n'
        "### Current behavior\nUnused import abc (unused-import)\n"
    )
    assert classify(text) == "wrong-output"


def test_attrs_not_copied_is_wrong_output_not_rendering():
    # pydata__xarray-4629
    text = (
        "merge(combine_attrs='override') does not copy attrs but instead "
        "references attrs from the first object"
    )
    assert classify(text) == "wrong-output"


def test_keep_attrs_not_honored_is_wrong_output():
    # pydata__xarray-3305
    text = "DataArray.quantile does not honor `keep_attrs`"
    assert classify(text) == "wrong-output"


def test_add_title_is_a_feature_request():
    # sympy__sympy-13852
    text = "Add evaluation for polylog\nThe answer should be -log(2)**2/2 + pi**2/12"
    assert classify(text) == "api-behavior"


def test_traceback_in_code_block_still_detected():
    text = (
        "Something broke\nRunning the snippet gives:\n```\n"
        "Traceback (most recent call last):\n  File \"x.py\", line 1\n"
        "SomeWeirdError: nope\n```\n"
    )
    assert classify(text) == "crash"


def test_real_crash_report():
    # django__django-15128
    text = (
        "Query.change_aliases raises an AssertionError\n"
        "Description\nPython Version: 3.9.2\nCode to Reproduce ..."
    )
    assert classify(text) == "crash"


def test_genuine_rendering_issue():
    # sphinx-doc__sphinx-8548
    text = (
        "autodoc inherited-members won't work for inherited attributes.\n"
        "autodoc searches for a cached docstring using (namespace, attrname)."
    )
    assert classify(text) == "rendering"


def test_version_dump_does_not_look_like_a_rendering_bug():
    # pydata__xarray-6721: xr.show_versions() output lists "sphinx: None".
    text = (
        "Accessing chunks on zarr backed xarray seems to load entire array "
        "into memory\n### What happened?\nThe entire dataset is loaded into "
        "memory when accessing the chunks attribute.\n"
        "<details>\npytest: 7.1.1\nIPython: 8.2.0\nsphinx: None\n</details>\n"
    )
    assert classify(text) != "rendering"


def test_traceback_beats_a_passing_feature_remark():
    # matplotlib__matplotlib-20859: a real crash that also muses
    # "it would be useful if ..." further down.
    text = (
        "Adding a legend to a `SubFigure` doesn't work\n"
        "### Bug report\n```\nTraceback (most recent call last):\n"
        "TypeError: Legend needs either Axes or Figure as parent\n```\n"
        "I think it would be useful to support this.\n"
    )
    assert classify(text) == "crash"


def test_bug_title_starting_with_a_feature_verb_is_not_a_feature():
    text = "Allow_tags does not work and fails with an error"
    assert classify(text) != "api-behavior"


def test_rfe_prefixed_support_title_is_a_feature_request():
    # sphinx-doc__sphinx-9258
    text = (
        "[RFE] Support union types specification using | (vertical bar/pipe)\n"
        "Current sphinx docstring documentation requires this verbose syntax."
    )
    assert classify(text) == "api-behavior"


def test_incidental_docstring_mention_is_not_rendering():
    # pytest-dev__pytest-8399: about fixture visibility, not documentation.
    text = (
        'Starting v6.2.0, unittest setUpClass fixtures are no longer "private"\n'
        "The fixture is now shown in --fixtures output, and its docstring is "
        "surprising. This is inconsistent with previous behaviour."
    )
    assert classify(text) != "rendering"


def test_docstring_with_doc_tooling_is_rendering():
    # sphinx-doc__sphinx-9461
    text = (
        "Methods decorated with @classmethod and @property do not get documented.\n"
        "When using autodoc, the docstring is not picked up for such methods."
    )
    assert classify(text) == "rendering"


def test_unmatched_text_falls_through_to_other():
    assert classify("Something happened in the module.") == OTHER
    assert classify("") == OTHER


def test_every_label_is_a_known_type():
    samples = [
        "Query.change_aliases raises an AssertionError",
        "autodoc inherited-members won't work",
        "It would be nice to add an option for this",
        "returns the wrong value instead of the expected one",
        "nondescript text",
    ]
    for text in samples:
        assert classify(text) in (*STRATUM_TYPES, OTHER)
