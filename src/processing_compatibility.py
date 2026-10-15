"""Fail-closed software-version identity; never a cross-pipeline calibration."""
import re


def version(value):
    text = str(value).strip() if value is not None else ''
    if not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', text):
        return None
    parts = tuple(int(v) for v in text.split('.'))
    return parts + (0,) if len(parts) == 2 else parts


def same_version(patient, reference):
    a, b = version(patient), version(reference)
    return a is not None and b is not None and a == b


def all_versions_match(values, reference):
    values = list(values)
    return bool(values) and all(same_version(v, reference) for v in values)
