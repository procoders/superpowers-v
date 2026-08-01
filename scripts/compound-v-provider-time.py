#!/usr/bin/env python3
"""Compound V strict provider timestamp/delay helpers (Python 3.9-safe)."""

import datetime
import json
import math
import os
import sys


def parse_utc_timestamp(value, field):
    """Parse one timezone-aware ISO-8601 string and normalize it to UTC.

    Python 3.9's documented ``fromisoformat`` grammar does not accept terminal
    ``Z``, so normalize that spelling explicitly before parsing. Provider/state
    strings are untrusted: wrong types, malformed values, and naive timestamps
    all fail closed as ``ValueError``.
    """
    if not isinstance(value, str) or not value:
        raise ValueError("%s must be a non-empty timestamp string" % field)
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.datetime.fromisoformat(normalized)
    except (TypeError, ValueError) as e:
        raise ValueError("%s must be a valid ISO-8601 timestamp: %s" % (field, e))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("%s must be timezone-aware" % field)
    return parsed.astimezone(datetime.timezone.utc)


def format_utc_timestamp(value):
    """Format one aware datetime as canonical UTC ISO-8601 ending in ``Z``."""
    if not isinstance(value, datetime.datetime):
        raise ValueError("timestamp must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    rendered = value.astimezone(datetime.timezone.utc).isoformat()
    if not rendered.endswith("+00:00"):
        raise ValueError("timestamp did not normalize to UTC")
    return rendered[:-6] + "Z"


def parse_delay(value, field):
    """Return a finite, non-negative numeric delay; reject bools and strings."""
    if (isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0):
        raise ValueError("%s must be a finite non-negative number" % field)
    return value


def _selftest():
    checked = [0]
    failures = []

    def check(name, condition):
        checked[0] += 1
        if condition:
            print("  ok   - %s" % name)
        else:
            print("  FAIL - %s" % name)
            failures.append(name)

    def raises_value_error(fn):
        try:
            fn()
        except ValueError:
            return True
        except Exception:
            return False
        return False

    parse_timestamp = globals().get("parse_utc_timestamp")
    format_timestamp = globals().get("format_utc_timestamp")
    parse_numeric_delay = globals().get("parse_delay")

    z_value = (parse_timestamp("2026-08-01T07:20:00Z", "retry_at")
               if callable(parse_timestamp) else None)
    check("terminal Z parses as aware UTC datetime",
          isinstance(z_value, datetime.datetime)
          and z_value.tzinfo is not None
          and z_value.utcoffset() == datetime.timedelta(0))

    offset_value = (parse_timestamp("2026-08-01T09:20:00+02:00", "retry_at")
                    if callable(parse_timestamp) else None)
    check("offset timestamp normalizes to the same UTC instant",
          isinstance(offset_value, datetime.datetime)
          and offset_value == datetime.datetime(
              2026, 8, 1, 7, 20, tzinfo=datetime.timezone.utc))
    check("UTC formatter emits one canonical terminal-Z form",
          callable(format_timestamp)
          and isinstance(offset_value, datetime.datetime)
          and format_timestamp(offset_value) == "2026-08-01T07:20:00Z")

    check("naive timestamp is rejected",
          callable(parse_timestamp)
          and raises_value_error(lambda: parse_timestamp(
              "2026-08-01T07:20:00", "retry_at")))
    check("malformed timestamp is rejected",
          callable(parse_timestamp)
          and raises_value_error(lambda: parse_timestamp(
              "not-a-timestamp", "retry_at")))
    check("non-string timestamp is rejected",
          callable(parse_timestamp)
          and raises_value_error(lambda: parse_timestamp(123, "retry_at")))
    check("formatter rejects naive datetime",
          callable(format_timestamp)
          and raises_value_error(lambda: format_timestamp(
              datetime.datetime(2026, 8, 1, 7, 20))))

    check("zero delay is accepted",
          callable(parse_numeric_delay)
          and parse_numeric_delay(0, "retry_after_seconds") == 0)
    check("positive fractional delay is accepted",
          callable(parse_numeric_delay)
          and parse_numeric_delay(1.5, "delay") == 1.5)
    for name, bad in (
            ("boolean delay", True),
            ("negative delay", -1),
            ("NaN delay", float("nan")),
            ("positive Infinity delay", float("inf")),
            ("negative Infinity delay", float("-inf")),
            ("string delay", "5")):
        check("%s is rejected" % name,
              callable(parse_numeric_delay)
              and raises_value_error(lambda value=bad: parse_numeric_delay(
                  value, "delay")))

    # Python's stdlib JSON decoder accepts these non-standard constants by
    # default. Prove the public delay boundary rejects the decoded values.
    for token in ("NaN", "Infinity", "-Infinity"):
        decoded = json.loads(token)
        check("JSON %s is rejected at the delay boundary" % token,
              callable(parse_numeric_delay)
              and not math.isfinite(decoded)
              and raises_value_error(lambda value=decoded: parse_numeric_delay(
                  value, "retry_after_seconds")))

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    schema_path = os.path.join(repo_root, "schemas", "job_result.schema.json")
    example_path = os.path.join(repo_root, "examples", "job_result.example.json")
    contract_path = os.path.join(repo_root, "skills", "backend-launcher", "SKILL.md")
    with open(schema_path, "r", encoding="utf-8") as fh:
        schema = json.load(fh)
    properties = schema.get("properties", {})
    failure_enum = properties.get("failure_class", {}).get("enum", [])
    check("schema includes usage_window_exhausted failure class",
          "usage_window_exhausted" in failure_enum)
    check("schema includes model_unavailable failure class",
          "model_unavailable" in failure_enum)
    check("schema rejects negative retry_after_seconds",
          properties.get("retry_after_seconds", {}).get("minimum") == 0)
    retry_at = properties.get("retry_at", {})
    check("schema exposes nullable RFC3339 retry_at",
          retry_at.get("type") == ["string", "null"]
          and retry_at.get("format") == "date-time")
    network_scope = properties.get("network_scope", {})
    check("schema exposes nullable narrow network_scope enum",
          network_scope.get("type") == ["string", "null"]
          and network_scope.get("enum")
          == [None, "no_response", "provider_reported"])

    with open(example_path, "r", encoding="utf-8") as fh:
        example = json.load(fh)
    check("success example omits retry_at",
          example.get("status") == "success" and "retry_at" not in example)
    check("success example omits network_scope",
          example.get("status") == "success" and "network_scope" not in example)

    with open(contract_path, "r", encoding="utf-8") as fh:
        contract = fh.read()
    check("launcher contract documents retry_at and network_scope",
          "`retry_at`" in contract and "`network_scope`" in contract)
    check("launcher contract requires success/blocked omission",
          "success/blocked" in contract
          and "MUST omit" in contract)

    fail_count = len(failures)
    print("SELFTEST: %d ok, %d fail"
          % (checked[0] - fail_count, fail_count))
    return 1 if failures else 0


def main(argv):
    if argv[1:] == ["--selftest"]:
        return _selftest()
    print("usage: compound-v-provider-time.py --selftest", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
