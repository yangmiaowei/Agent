"""Rule-based problem-type taxonomy for SWE-bench issues.

Used only to stratify the evaluation suite; it never reaches the agent.

Keyword matching on raw problem statements is unreliable for three reasons,
each handled explicitly below:

  * Issue templates. xarray/matplotlib/sklearn issues carry large HTML comment
    blocks ("<!-- ... post a Minimal, Complete and Verifiable Example ... -->")
    whose wording matches almost any rule.
  * Code samples. A repro containing `\"\"\"Docstring.\"\"\"` or `ValueError`
    says nothing about the symptom being reported.
  * Environment dumps. xarray's `xr.show_versions()` output is pasted inside a
    <details> block and lists `sphinx: 1.7.1`, `IPython: 8.2.0` and friends,
    which made unrelated issues look like documentation-rendering bugs.

`_prose()` strips all three. A traceback is the one signal read from the raw
text, since it lives inside a code block and is the strongest crash evidence
available.

Rule priority, first match wins:

  1. Strong feature markers ("feature request", an imperative "Add X" title)
  2. Traceback  -> crash, because hard evidence outranks a passing remark like
     "it would be useful if ..." that often appears late in a bug report
  3. Soft feature phrasing ("would be nice to ...")
  4. crash / rendering / wrong-output / api-behavior keyword rules

`api-behavior` is matched last and kept narrow: phrases like "adding
multi_class as an argument" usually describe a *suggested fix* inside an
otherwise ordinary bug report, so leaning on them mislabels wrong-output cases.

Bump TAXONOMY_VERSION when rules change; a frozen suite records the version it
was built with.
"""

import re

TAXONOMY_VERSION = "v4"

OTHER = "other"

#: Types eligible to act as strata. `other` is intentionally excluded: it is a
#: residual bucket, not a coherent category, so sampling from it would make the
#: per-type comparison meaningless.
STRATUM_TYPES = ("crash", "rendering", "api-behavior", "wrong-output")

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_DETAILS_BLOCK = re.compile(r"<details>.*?</details>", re.S | re.I)
_FENCED_CODE = re.compile(r"```.*?```", re.S)
_INDENTED_CODE = re.compile(r"^(?: {4}|\t).*$", re.M)
_INLINE_CODE = re.compile(r"`{1,3}[^`]*`{1,3}")
# Leftover "package: 1.2.3" / "package: None" lines from version dumps that are
# pasted without a <details> wrapper.
_VERSION_LINE = re.compile(r"^[ \t]*[\w.+-]+[ \t]*:[ \t]*(?:None|\d[\w.+-]*)[ \t]*$", re.M)
_TRACEBACK = re.compile(r"Traceback \(most recent call last\)")

# Unambiguous "this is a request for new behaviour" markers.
_STRONG_FEATURE = re.compile(
    r"\bfeature request\b|\benhancement\b"
    r"|\bdescribe the workflow you want to enable\b"
    r"|\bproposed? (?:api|solution|behaviou?r)\b"
    r"|\bplease support\b",
    re.I,
)

# Softer phrasing; loses to a traceback.
_SOFT_FEATURE = re.compile(
    r"\b(?:would|it'?d|it would) be (?:nice|good|great|useful|helpful|better)\b"
    r"|\bi(?: would|'d)? (?:like|want) to be able to\b"
    r"|\bit (?:would|should) be possible to\b",
    re.I,
)

# Imperative issue titles ("Add X", "Support Y") request missing capability.
# `add\b` deliberately does not match "Adding", which reads as a bug report.
_FEATURE_TITLE = re.compile(
    r"^\s*(?:\[?(?:enh|rfe|rfc|feature|proposal)\]?:?\s*)?"
    r"(?:add|implement|support|allow|expose|provide)\b",
    re.I,
)

# A title describing breakage is never a feature request, whatever it starts with.
_BUG_TITLE = re.compile(
    r"\bdoes\s?n[o']?t work\b|\bfails?\b|\bbroken\b|\bcrash(?:es)?\b"
    r"|\berror\b|\bincorrect\b|\bwrong\b|\bregression\b|\[bug\]",
    re.I,
)

_RULES: list[tuple[str, re.Pattern]] = [
    (
        # Something raises where it should not.
        "crash",
        re.compile(
            r"\b(AttributeError|TypeError|ValueError|KeyError|IndexError|ImportError"
            r"|RuntimeError|RecursionError|ZeroDivisionError|UnboundLocalError"
            r"|NotImplementedError|AssertionError|UnicodeDecodeError|OverflowError)\b"
            r"|\b(crash(?:es|ing|ed)?|traceback|segmentation fault)\b"
            r"|\b(raises?|throws?|raising|fails? with|errors? out)\b[^.]{0,40}"
            r"\b(error|exception|assertion)\b",
            re.I,
        ),
    ),
    (
        # Output formatting / textual representation / doc generation.
        # Kept narrow: bare "rendered"/"displayed"/"formatting" matched far too
        # much, and bare "sphinx" matched version dumps.
        "rendering",
        re.compile(
            r"\b(__repr__|__str__|repr\(|pretty[- ]?print(?:er|ing)?|pprint"
            r"|latex|mathml|autodoc)\b"
            r"|\bsphinx (?:build|extension|directive|role|output|renders?)\b"
            r"|\b(?:kbd|rst|restructuredtext) (?:role|directive|output)\b"
            r"|\b(html|pdf|svg|markdown|rst)\s+(?:output|rendering|generation)\b"
            r"|\b(printed|rendered|displayed)\s+"
            r"(?:output|representation|incorrectly|wrongly)\b",
            re.I,
        ),
    ),
    (
        # Runs fine but produces the wrong value.
        "wrong-output",
        re.compile(
            r"\b(incorrect(?:ly)?|wrong(?:ly)?|inconsistent|unexpected(?:ly)?"
            r"|false positive|false negative)\b"
            r"|\bshould (?:return|be|give|produce|equal|yield|honor|honour|respect)\b"
            r"|\binstead of\b|\bbut (?:returns?|gives?|produces?|yields?|outputs?)\b"
            r"|\bdoes\s?n[o']?t (?:work|match|apply|respect|honor|honour|copy|update)\b"
            r"|\bsilently\b|\bis ignored\b|\bare ignored\b|\bnot honored\b",
            re.I,
        ),
    ),
    (
        # Missing capability, or a deliberate validation/messaging change.
        "api-behavior",
        re.compile(
            r"\berror message\b|\bconfusing (?:message|error|output)\b|\bmisleading\b"
            r"|\bshould (?:warn|validate|reject|deprecate)\b"
            r"|\b(?:add|expose|support for)\b[^.]{0,30}"
            r"\b(?:option|parameter|keyword|kwarg|flag)\b",
            re.I,
        ),
    ),
]


# "docstring" alone is a weak signal: it shows up incidentally in issues about
# fixtures, naming and inspection. It only indicates a rendering problem when
# documentation tooling is also in play.
_DOCSTRING = re.compile(r"\bdocstrings?\b", re.I)
_DOC_TOOLING = re.compile(
    r"\b(autodoc|sphinx|documentation|documented|apidoc|napoleon|docs build)\b",
    re.I,
)


def _is_doc_rendering(prose: str) -> bool:
    return bool(_DOCSTRING.search(prose)) and bool(_DOC_TOOLING.search(prose))


def _prose(text: str) -> str:
    """Strip template boilerplate, code and version dumps."""
    text = _HTML_COMMENT.sub(" ", text)
    text = _DETAILS_BLOCK.sub(" ", text)
    text = _FENCED_CODE.sub(" ", text)
    text = _INDENTED_CODE.sub(" ", text)
    text = _INLINE_CODE.sub(" ", text)
    text = _VERSION_LINE.sub(" ", text)
    return text


def _title(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def classify(problem_statement: str) -> str:
    raw = problem_statement or ""
    prose = _prose(raw)
    title = _title(raw)

    title_is_feature = bool(_FEATURE_TITLE.match(title)) and not _BUG_TITLE.search(title)
    if _STRONG_FEATURE.search(prose) or title_is_feature:
        return "api-behavior"

    if _TRACEBACK.search(raw):
        return "crash"

    if _SOFT_FEATURE.search(prose):
        return "api-behavior"

    for name, pattern in _RULES:
        if pattern.search(prose):
            return name
        if name == "rendering" and _is_doc_rendering(prose):
            return name
    return OTHER


def classify_all(problem_statements) -> list[str]:
    return [classify(ps) for ps in problem_statements]


def explain(problem_statement: str) -> dict:
    """Diagnostics for reviewing a label. Not used in selection."""
    raw = problem_statement or ""
    prose = _prose(raw)
    title = _title(raw)
    hits = {}
    for label, pattern in (
        ("strong_feature", _STRONG_FEATURE),
        ("soft_feature", _SOFT_FEATURE),
    ):
        m = pattern.search(prose)
        if m:
            hits[label] = m.group(0)
    if _FEATURE_TITLE.match(title):
        hits["feature_title"] = title[:80]
    if _BUG_TITLE.search(title):
        hits["bug_title"] = _BUG_TITLE.search(title).group(0)
    if _TRACEBACK.search(raw):
        hits["traceback"] = True
    for name, pattern in _RULES:
        m = pattern.search(prose)
        if m:
            hits[f"rule:{name}"] = m.group(0)
    if _is_doc_rendering(prose):
        hits["rule:rendering(docstring+tooling)"] = True
    return {"label": classify(raw), "title": title[:100], "hits": hits}
