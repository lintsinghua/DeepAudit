#!/usr/bin/env python3
"""Generate and refresh DeepAudit's repository-owned Star History chart.

``backfill`` reconstructs daily totals from starredAt timestamps only.
Scheduled updates record one aggregate count, then render light and dark SVGs.
No stargazer identity is stored.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

REPOSITORY = "lintsinghua/DeepAudit"
INTERVAL_DAYS = 13
STATE_RELATIVE = Path(".github/star-history/history.json")
LIGHT_SVG_RELATIVE = Path("docs/images/star-history-light.svg")
DARK_SVG_RELATIVE = Path("docs/images/star-history-dark.svg")
OUTPUT_RELATIVES = (STATE_RELATIVE, LIGHT_SVG_RELATIVE, DARK_SVG_RELATIVE)
MAX_STATE_BYTES = 5_000_000
MAX_COUNT_FILE_BYTES = 64
MAX_STAR_COUNT = (1 << 63) - 1
MAX_HTTP_BYTES = 1_000_000
PAGE_SIZE = 100
UTC = timezone.utc
API_VERSION = "2022-11-28"
USER_AGENT = "DeepAudit-Star-History"

# Reviewed 64x64 JPEG of the public GitHub avatar for lintsinghua. Embedded so
# the generated SVG stays self-contained.
OWNER_AVATAR_BASE64 = (
    "/9j/4AAQSkZJRgABAQAASABIAAD/4QBMRXhpZgAATU0AKgAAAAgAAYdpAAQAAAABAAAAGgAAAAAA"
    "A6ABAAMAAAABAAEAAKACAAQAAAABAAAAQKADAAQAAAABAAAAQAAAAAD/7QA4UGhvdG9zaG9wIDMu"
    "MAA4QklNBAQAAAAAAAA4QklNBCUAAAAAABDUHYzZjwCyBOmACZjs+EJ+/8AAEQgAQABAAwEiAAIR"
    "AQMRAf/EAB8AAAEFAQEBAQEBAAAAAAAAAAABAgMEBQYHCAkKC//EALUQAAIBAwMCBAMFBQQEAAAB"
    "fQECAwAEEQUSITFBBhNRYQcicRQygZGhCCNCscEVUtHwJDNicoIJChYXGBkaJSYnKCkqNDU2Nzg5"
    "OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6g4SFhoeIiYqSk5SVlpeYmZqio6Slpqeo"
    "qaqys7S1tre4ubrCw8TFxsfIycrS09TV1tfY2drh4uPk5ebn6Onq8fLz9PX29/j5+v/EAB8BAAMB"
    "AQEBAQEBAQEAAAAAAAABAgMEBQYHCAkKC//EALURAAIBAgQEAwQHBQQEAAECdwABAgMRBAUhMQYS"
    "QVEHYXETIjKBCBRCkaGxwQkjM1LwFWJy0QoWJDThJfEXGBkaJicoKSo1Njc4OTpDREVGR0hJSlNU"
    "VVZXWFlaY2RlZmdoaWpzdHV2d3h5eoKDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5"
    "usLDxMXGx8jJytLT1NXW19jZ2uLj5OXm5+jp6vLz9PX29/j5+v/bAEMAAgICAgICAwICAwUDAwMF"
    "BgUFBQUGCAYGBgYGCAoICAgICAgKCgoKCgoKCgwMDAwMDA4ODg4ODw8PDw8PDw8PD//bAEMBAgIC"
    "BAQEBwQEBxALCQsQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQ"
    "EBAQEP/dAAQABP/aAAwDAQACEQMRAD8A+hKKKK/sg/DwoyK+Mv2m/wBpuX4WSf8ACF+CwD4vxBc/"
    "6TB5lr9lk3hvmDg78gY4r8lrSzhsofJhztznnnk1+ecR+INHA1vYU4c8lvra3ls9e/Y+nyrhmeIp"
    "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"
    "n5HxJDDLFyng6yq05axktpJ7Nas//9k="
)
OWNER_AVATAR_DATA_URI = f"data:image/jpeg;base64,{OWNER_AVATAR_BASE64}"

# 64x64 RGBA watermark from the MIT-licensed Star History renderer
# (Copyright 2025 Star History).
WATERMARK_LOGO_BASE64 = (
    "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"
    "MTQtMDU6MDDygtFyAAAAAElFTkSuQmCC"
)
WATERMARK_LOGO_DATA_URI = f"data:image/png;base64,{WATERMARK_LOGO_BASE64}"

STATE_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class StarHistoryError(RuntimeError):
    """User-facing error that never includes secrets."""


@dataclass(frozen=True)
class Result:
    changed: bool
    due: bool | None
    message: str


@dataclass(frozen=True)
class ChartPoint:
    at: datetime
    stars: int
    source: str


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC).replace(microsecond=0)


def _strict_non_negative_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise StarHistoryError(f"{label} must be a non-negative integer")
    return value


def _parse_github_timestamp(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise StarHistoryError("GitHub returned an invalid timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(microsecond=0)


def _parse_state_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not STATE_TIMESTAMP_RE.fullmatch(value):
        raise StarHistoryError(f"{label} must be a UTC timestamp")
    return _parse_github_timestamp(value)


def _format_state_timestamp(value: datetime) -> str:
    return _normalize_now(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_now(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise StarHistoryError("clock must return a UTC datetime")
    return value.astimezone(UTC).replace(microsecond=0)


def _expect_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise StarHistoryError(f"{label} contains missing or unknown fields")


def validate_state(state: Any) -> None:
    if not isinstance(state, dict):
        raise StarHistoryError("history state must be a JSON object")
    _expect_keys(
        state,
        {
            "schema_version",
            "repository",
            "timezone",
            "ongoing_interval_days",
            "reconstruction",
            "snapshots",
        },
        "history state",
    )
    if state["schema_version"] != 1 or type(state["schema_version"]) is not int:
        raise StarHistoryError("unsupported history schema_version")
    if state["repository"] != REPOSITORY:
        raise StarHistoryError(f"history repository must be {REPOSITORY}")
    if state["timezone"] != "UTC":
        raise StarHistoryError("history timezone must be UTC")
    if (
        state["ongoing_interval_days"] != INTERVAL_DAYS
        or type(state["ongoing_interval_days"]) is not int
    ):
        raise StarHistoryError(
            f"history interval must be exactly {INTERVAL_DAYS} days"
        )

    reconstruction = state["reconstruction"]
    if not isinstance(reconstruction, dict):
        raise StarHistoryError("reconstruction must be an object")
    _expect_keys(reconstruction, {"method", "generated_at", "daily"}, "reconstruction")
    if reconstruction["method"] != "current_stargazers_starred_at":
        raise StarHistoryError("unsupported reconstruction method")
    generated_at = _parse_state_timestamp(
        reconstruction["generated_at"], "reconstruction.generated_at"
    )
    daily = reconstruction["daily"]
    if not isinstance(daily, list):
        raise StarHistoryError("reconstruction.daily must be a list")

    previous_day: date | None = None
    previous_stars = 0
    for index, raw_point in enumerate(daily):
        if not isinstance(raw_point, dict):
            raise StarHistoryError("reconstruction point must be an object")
        _expect_keys(raw_point, {"date", "stars"}, "reconstruction point")
        raw_date = raw_point["date"]
        if not isinstance(raw_date, str):
            raise StarHistoryError("reconstruction date must be a string")
        try:
            point_day = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise StarHistoryError("reconstruction date is invalid") from exc
        if point_day.isoformat() != raw_date:
            raise StarHistoryError("reconstruction date is not canonical")
        stars = _strict_non_negative_int(raw_point["stars"], "reconstruction stars")
        if index == 0 and stars <= 0:
            raise StarHistoryError("first reconstruction point must have stars")
        if previous_day is not None and point_day <= previous_day:
            raise StarHistoryError("reconstruction dates must be strictly increasing")
        if index > 0 and stars <= previous_stars:
            raise StarHistoryError("reconstruction stars must be strictly increasing")
        if point_day >= generated_at.date():
            raise StarHistoryError("reconstruction must contain only completed UTC dates")
        previous_day = point_day
        previous_stars = stars

    snapshots = state["snapshots"]
    if not isinstance(snapshots, list):
        raise StarHistoryError("snapshots must be a list")
    previous_snapshot: datetime | None = None
    first_snapshot: datetime | None = None
    for raw_snapshot in snapshots:
        if not isinstance(raw_snapshot, dict):
            raise StarHistoryError("snapshot must be an object")
        _expect_keys(raw_snapshot, {"at", "stars"}, "snapshot")
        snapshot_at = _parse_state_timestamp(raw_snapshot["at"], "snapshot.at")
        _strict_non_negative_int(raw_snapshot["stars"], "snapshot stars")
        if previous_snapshot is not None and snapshot_at <= previous_snapshot:
            raise StarHistoryError("snapshot timestamps must be strictly increasing")
        if first_snapshot is None:
            first_snapshot = snapshot_at
        previous_snapshot = snapshot_at

    if first_snapshot is not None:
        if first_snapshot < generated_at:
            raise StarHistoryError("first snapshot cannot predate reconstruction")
        if previous_day is not None and previous_day >= first_snapshot.date():
            raise StarHistoryError("reconstruction dates must predate snapshots")


def canonical_state_bytes(state: Mapping[str, Any]) -> bytes:
    validate_state(state)
    return (json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _workspace_root(workspace: Path) -> Path:
    try:
        root = workspace.resolve(strict=True)
    except OSError as exc:
        raise StarHistoryError("workspace does not exist") from exc
    if not root.is_dir():
        raise StarHistoryError("workspace is not a directory")
    return root


def _target(workspace: Path, relative: Path) -> Path:
    root = _workspace_root(workspace)
    if relative.is_absolute() or ".." in relative.parts:
        raise StarHistoryError("output path escaped the workspace")
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise StarHistoryError("output path escaped the workspace") from exc
    return target


def _read_limited(path: Path, limit: int, label: str) -> bytes:
    try:
        payload = path.read_bytes()
    except FileNotFoundError as exc:
        raise StarHistoryError(f"{label} is missing") from exc
    except OSError as exc:
        raise StarHistoryError(f"could not read {label}") from exc
    if len(payload) > limit:
        raise StarHistoryError(f"{label} exceeded the size limit")
    return payload


def load_star_count_file(path: Path) -> int:
    payload = _read_limited(path, MAX_COUNT_FILE_BYTES, "Star count file")
    if not re.fullmatch(rb"(?:0|[1-9][0-9]*)\n?", payload):
        raise StarHistoryError("Star count file must contain one decimal integer")
    count = int(payload)
    if count > MAX_STAR_COUNT:
        raise StarHistoryError("Star count exceeded the supported range")
    return count


def load_state(workspace: Path, require_canonical: bool = True) -> dict[str, Any]:
    payload = _read_limited(_target(workspace, STATE_RELATIVE), MAX_STATE_BYTES, "history state")
    try:
        state = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StarHistoryError("history state is not valid UTF-8 JSON") from exc
    validate_state(state)
    if require_canonical and canonical_state_bytes(state) != payload:
        raise StarHistoryError("history state is not canonically formatted")
    return state


def _snapshot_due(state: Mapping[str, Any], now: datetime) -> bool:
    normalized = _normalize_now(now)
    generated_at = _parse_state_timestamp(
        state["reconstruction"]["generated_at"], "reconstruction.generated_at"
    )
    if normalized < generated_at:
        raise StarHistoryError("clock is earlier than the reconstruction timestamp")
    snapshots = state["snapshots"]
    if not snapshots:
        return True
    latest = _parse_state_timestamp(snapshots[-1]["at"], "snapshot.at")
    if normalized < latest:
        raise StarHistoryError("clock is earlier than the latest snapshot")
    return normalized - latest >= timedelta(days=INTERVAL_DAYS)


def resolve_token() -> str:
    for key in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(key, "").strip()
        if value and "\n" not in value and "\r" not in value:
            return value
    try:
        completed = subprocess.run(
            ["gh", "auth", "token"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise StarHistoryError("GITHUB_TOKEN is required") from exc
    token = completed.stdout.strip()
    if completed.returncode != 0 or not token:
        raise StarHistoryError("GITHUB_TOKEN is required")
    return token


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _github_get(url: str, token: str, accept: str) -> tuple[Any, str | None]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": API_VERSION,
        },
    )
    opener = urllib.request.build_opener(NoRedirectHandler())
    try:
        with opener.open(request, timeout=20) as response:
            payload = response.read(MAX_HTTP_BYTES + 1)
            if len(payload) > MAX_HTTP_BYTES:
                raise StarHistoryError("GitHub API response exceeded the size limit")
            next_url = _next_link(response.headers.get("Link"))
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise StarHistoryError("GitHub API returned malformed JSON") from exc
            return parsed, next_url
    except urllib.error.HTTPError as exc:
        raise StarHistoryError(f"GitHub API request failed (HTTP {exc.code})") from exc
    except urllib.error.URLError as exc:
        raise StarHistoryError("GitHub API request failed") from exc


def _next_link(value: str | None) -> str | None:
    if not value:
        return None
    for part in value.split(","):
        section = part.strip()
        if 'rel="next"' not in section:
            continue
        start = section.find("<")
        end = section.find(">", start + 1)
        if start >= 0 and end > start:
            return section[start + 1 : end]
    return None


def fetch_star_count(token: str) -> int:
    payload, _ = _github_get(
        f"https://api.github.com/repos/{REPOSITORY}",
        token,
        "application/vnd.github+json",
    )
    if not isinstance(payload, dict):
        raise StarHistoryError("GitHub API returned an unexpected payload")
    return _strict_non_negative_int(payload.get("stargazers_count"), "stargazers_count")


def fetch_starred_at(token: str) -> list[datetime]:
    url: str | None = (
        f"https://api.github.com/repos/{REPOSITORY}/stargazers?per_page={PAGE_SIZE}"
    )
    stamps: list[datetime] = []
    pages = 0
    while url:
        pages += 1
        if pages > 10_000:
            raise StarHistoryError("GitHub API exceeded the page safety limit")
        payload, url = _github_get(url, token, "application/vnd.github.star+json")
        if not isinstance(payload, list):
            raise StarHistoryError("GitHub API returned an unexpected stargazer list")
        for item in payload:
            if not isinstance(item, dict) or not isinstance(item.get("starred_at"), str):
                raise StarHistoryError("GitHub API returned an invalid star timestamp")
            stamps.append(_parse_github_timestamp(item["starred_at"]))
    return stamps


def build_backfill_state(starred_at: Sequence[datetime], now: datetime) -> dict[str, Any]:
    normalized_now = _normalize_now(now)
    daily_increments: Counter[date] = Counter()
    for stamp in starred_at:
        if stamp.date() < normalized_now.date():
            daily_increments[stamp.date()] += 1

    running = 0
    daily: list[dict[str, Any]] = []
    for point_day in sorted(daily_increments):
        running += daily_increments[point_day]
        daily.append({"date": point_day.isoformat(), "stars": running})

    state: dict[str, Any] = {
        "schema_version": 1,
        "repository": REPOSITORY,
        "timezone": "UTC",
        "ongoing_interval_days": INTERVAL_DAYS,
        "reconstruction": {
            "method": "current_stargazers_starred_at",
            "generated_at": _format_state_timestamp(normalized_now),
            "daily": daily,
        },
        "snapshots": [],
    }
    validate_state(state)
    return state


def _updated_with_snapshot(
    state: Mapping[str, Any], now: datetime, stars: int
) -> dict[str, Any]:
    normalized_now = _normalize_now(now)
    _strict_non_negative_int(stars, "stargazers_count")
    updated = json.loads(json.dumps(state))
    snapshots: list[dict[str, Any]] = updated["snapshots"]
    new_snapshot = {"at": _format_state_timestamp(normalized_now), "stars": stars}
    if snapshots:
        latest_at = _parse_state_timestamp(snapshots[-1]["at"], "snapshot.at")
        if normalized_now < latest_at:
            raise StarHistoryError("clock is earlier than the latest snapshot")
        if normalized_now.date() == latest_at.date():
            if snapshots[-1]["stars"] == stars:
                return updated
            snapshots[-1] = new_snapshot
        else:
            snapshots.append(new_snapshot)
    else:
        snapshots.append(new_snapshot)
    validate_state(updated)
    return updated


def _chart_points(state: Mapping[str, Any]) -> list[ChartPoint]:
    points: list[ChartPoint] = []
    for item in state["reconstruction"]["daily"]:
        point_day = date.fromisoformat(item["date"])
        end_of_day = datetime.combine(point_day + timedelta(days=1), time.min, UTC)
        points.append(ChartPoint(end_of_day, item["stars"], "reconstruction"))
    for item in state["snapshots"]:
        points.append(
            ChartPoint(
                _parse_state_timestamp(item["at"], "snapshot.at"),
                item["stars"],
                "snapshot",
            )
        )
    points.sort(key=lambda point: point.at)
    return points


def _nice_y_axis(maximum: int) -> tuple[int, int]:
    if maximum <= 0:
        return 1, 5
    raw = maximum / 5
    exponent = math.floor(math.log10(raw)) if raw > 0 else 0
    base = 10**exponent
    fraction = raw / base
    if fraction <= 1:
        multiplier = 1.0
    elif fraction <= 2:
        multiplier = 2.0
    elif fraction <= 2.5:
        multiplier = 2.5
    elif fraction <= 5:
        multiplier = 5.0
    else:
        multiplier = 10.0
    step = max(1, int(multiplier * base))
    top = max(step, math.ceil(maximum / step) * step)
    return step, top


def _format_number(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}m".replace(".0m", "m")
    if value >= 1_000:
        return f"{value / 1_000:.1f}k".replace(".0k", "k")
    return str(value)


def _format_float(value: float) -> str:
    rendered = f"{value:.2f}".rstrip("0").rstrip(".")
    return rendered if rendered != "-0" else "0"


def _x_tick_label(value: datetime, span_days: float) -> str:
    months = (
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    )
    weekdays = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    if span_days >= 365:
        return f"{months[value.month - 1]} {value.year}"
    if span_days >= 14:
        return f"{value.day:02d} {months[value.month - 1]}"
    return f"{weekdays[value.weekday()]} {value.day:02d}"


def _sign(value: float) -> int:
    if value < 0:
        return -1
    if value > 0:
        return 1
    return 0


def _monotone_x_path(points: Sequence[tuple[float, float]]) -> str:
    """Return a D3 curveMonotoneX-equivalent SVG path.

    D3 uses Steffen monotonic interpolation: interior tangents are limited so a
    smooth cubic cannot overshoot a monotonic run.
    """

    normalized: list[tuple[float, float]] = []
    for x, y in points:
        if not math.isfinite(x) or not math.isfinite(y):
            raise StarHistoryError("chart coordinates must be finite")
        if normalized and x < normalized[-1][0]:
            raise StarHistoryError("chart coordinates must be ordered")
        if normalized and x == normalized[-1][0]:
            normalized[-1] = (x, y)
        else:
            normalized.append((x, y))

    if not normalized:
        return ""

    start_x, start_y = normalized[0]
    commands = [f"M{_format_float(start_x)},{_format_float(start_y)}"]
    if len(normalized) == 1:
        return "".join(commands)
    if len(normalized) == 2:
        end_x, end_y = normalized[1]
        commands.append(f"L{_format_float(end_x)},{_format_float(end_y)}")
        return "".join(commands)

    secants = [
        (normalized[index + 1][1] - normalized[index][1])
        / (normalized[index + 1][0] - normalized[index][0])
        for index in range(len(normalized) - 1)
    ]
    tangents = [0.0] * len(normalized)
    for index in range(1, len(normalized) - 1):
        h0 = normalized[index][0] - normalized[index - 1][0]
        h1 = normalized[index + 1][0] - normalized[index][0]
        slope0 = secants[index - 1]
        slope1 = secants[index]
        weighted = (slope0 * h1 + slope1 * h0) / (h0 + h1)
        tangents[index] = (_sign(slope0) + _sign(slope1)) * min(
            abs(slope0), abs(slope1), 0.5 * abs(weighted)
        )

    tangents[0] = (3 * secants[0] - tangents[1]) / 2
    tangents[-1] = (3 * secants[-1] - tangents[-2]) / 2

    for index in range(len(normalized) - 1):
        x0, y0 = normalized[index]
        x1, y1 = normalized[index + 1]
        third = (x1 - x0) / 3
        commands.append(
            "C"
            f"{_format_float(x0 + third)},{_format_float(y0 + third * tangents[index])} "
            f"{_format_float(x1 - third)},{_format_float(y1 - third * tangents[index + 1])} "
            f"{_format_float(x1)},{_format_float(y1)}"
        )
    return "".join(commands)


def render_svg(state: Mapping[str, Any], theme: str) -> bytes:
    """Render a self-contained Star History-compatible SVG."""

    validate_state(state)
    if theme not in {"light", "dark"}:
        raise StarHistoryError("unsupported SVG theme")

    plot_left = 70.0
    plot_top = 60.0
    plot_width = 700.0
    plot_height = 423.333
    plot_bottom = plot_top + plot_height

    if theme == "light":
        background = "#ffffff"
        foreground = "#000000"
        legend_background = "#ffffff"
        line_color = "#dd4528"
    else:
        background = "#0d1117"
        foreground = "#ffffff"
        legend_background = "#0d1117"
        line_color = "#ff6b6b"

    points = _chart_points(state)
    generated_at = _parse_state_timestamp(
        state["reconstruction"]["generated_at"], "reconstruction.generated_at"
    )
    if points:
        x_min = points[0].at
        x_max = points[-1].at
        if x_max <= x_min:
            try:
                x_min = points[0].at - timedelta(days=1)
            except OverflowError:
                pass
            try:
                x_max = points[-1].at + timedelta(days=1)
            except OverflowError:
                pass
        maximum = max(point.stars for point in points)
    else:
        try:
            x_min = generated_at - timedelta(days=1)
            x_max = generated_at
        except OverflowError:
            x_min = generated_at
            x_max = generated_at + timedelta(days=1)
        maximum = 0

    y_step, empty_y_top = _nice_y_axis(maximum)
    y_domain = maximum if maximum > 0 else empty_y_top
    x_span = max(1.0, (x_max - x_min).total_seconds())

    def x_coord(value: datetime) -> float:
        return plot_left + ((value - x_min).total_seconds() / x_span) * plot_width

    def y_coord(value: int) -> float:
        return plot_bottom - (value / y_domain) * plot_height

    line_coordinates = [(x_coord(point.at), y_coord(point.stars)) for point in points]
    if len({x for x, _ in line_coordinates}) == 1 and line_coordinates:
        x, y = line_coordinates[-1]
        line_path = (
            f"M{_format_float(x - 4)},{_format_float(y)}"
            f"H{_format_float(x + 4)}"
        )
    else:
        line_path = _monotone_x_path(line_coordinates)

    y_ticks: list[str] = []
    y_tick_limit = maximum if maximum > 0 else 5
    for value in range(y_step, y_tick_limit + 1, y_step):
        y = y_coord(value)
        y_ticks.append(
            f'<line x1="69" y1="{_format_float(y)}" x2="70" '
            f'y2="{_format_float(y)}" stroke="{foreground}"/>'
        )
        y_ticks.append(
            f'<text x="63" y="{_format_float(y + 5)}" text-anchor="end" '
            f'font-size="16" fill="{foreground}">{_format_number(value)}</text>'
        )

    x_ticks: list[str] = []
    seen_x_labels: set[str] = set()
    span_days = (x_max - x_min).total_seconds() / 86400
    tick_count = min(6, max(2, math.ceil(span_days) + 1))
    for index in range(tick_count):
        ratio = index / (tick_count - 1)
        value = x_min + (x_max - x_min) * ratio
        label = _x_tick_label(value, span_days)
        if label in seen_x_labels:
            continue
        seen_x_labels.add(label)
        x = x_coord(value)
        if index == 0:
            anchor = "start"
        elif index == tick_count - 1:
            anchor = "end"
        else:
            anchor = "middle"
        escaped = (
            label.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        x_ticks.append(
            f'<text x="{_format_float(x)}" y="{_format_float(plot_bottom + 18)}" '
            f'text-anchor="{anchor}" font-size="16" fill="{foreground}">'
            f"{escaped}</text>"
        )

    description = (
        f"Star history for {REPOSITORY}. Dates reconstructed from starredAt timestamps "
        "and later aggregate snapshots are rendered as one continuous series. "
        "No individual stargazer identity is stored."
    )
    escaped_description = (
        description.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    escaped_repo = REPOSITORY.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    legend_width = max(
        len(REPOSITORY) * 7.5 + 8 + 21,
        len(REPOSITORY) * 7 + 8 + 14 + 6,
    )
    svg = "".join(
        [
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 533.333" '
            'width="800" height="533.333" preserveAspectRatio="xMidYMid meet" '
            'role="img" aria-labelledby="title desc">',
            '<title id="title">DeepAudit Star History</title>',
            f'<desc id="desc">{escaped_description}</desc>',
            f'<rect width="800" height="533.333" fill="{background}"/>',
            "<defs>",
            '<filter id="xkcdify" filterUnits="userSpaceOnUse" x="-5" y="-5" '
            'width="100%" height="100%">',
            '<feTurbulence type="fractalNoise" baseFrequency="0.05" result="noise"/>',
            '<feDisplacementMap scale="5" xChannelSelector="R" yChannelSelector="G" '
            'in="SourceGraphic" in2="noise"/>',
            "</filter>",
            '<clipPath id="clip-circle-title"><circle r="11" cx="327" cy="23"/></clipPath>',
            "</defs>",
            '<g font-family="xkcd">',
            f'<image x="316" y="12" width="22" height="22" '
            f'href="{OWNER_AVATAR_DATA_URI}" clip-path="url(#clip-circle-title)"/>',
            f'<text x="400" y="30" text-anchor="middle" font-size="20" '
            f'font-weight="700" fill="{foreground}">Star History</text>',
            f'<path d="M{_format_float(plot_left)},{_format_float(plot_bottom)}'
            f'H{_format_float(plot_left + plot_width)}" fill="none" '
            f'stroke="{foreground}" stroke-width="3" filter="url(#xkcdify)"/>',
            f'<path d="M{_format_float(plot_left)},{_format_float(plot_bottom)}'
            f'V{_format_float(plot_top)}" fill="none" stroke="{foreground}" '
            f'stroke-width="3" filter="url(#xkcdify)"/>',
            *y_ticks,
            *x_ticks,
            (
                f'<path class="xkcd-chart-xyline" d="{line_path}" fill="none" '
                f'stroke="{line_color}" stroke-width="3" stroke-linecap="round" '
                f'stroke-linejoin="round" filter="url(#xkcdify)"/>'
                if line_path
                else ""
            ),
            f'<rect x="78" y="65" width="{_format_float(legend_width)}" height="32" rx="5" '
            f'fill="{legend_background}" fill-opacity="0.92" stroke="{foreground}" '
            f'stroke-width="2" filter="url(#xkcdify)"/>',
            f'<rect x="85" y="77" width="8" height="8" rx="2" fill="{line_color}" '
            f'filter="url(#xkcdify)"/>',
            f'<text x="99" y="85" font-size="15" fill="{foreground}">{escaped_repo}</text>',
            f'<text x="400" y="523.333" text-anchor="middle" font-size="17" '
            f'fill="{foreground}">Date</text>',
            f'<text x="22" y="272" text-anchor="middle" font-size="17" '
            f'fill="{foreground}" transform="rotate(-90 22 272)">GitHub Stars</text>',
            f'<image x="635" y="508.333" width="20" height="20" '
            f'href="{WATERMARK_LOGO_DATA_URI}"/>',
            '<text x="720" y="523.333" text-anchor="middle" font-size="16" '
            'fill="#666666">star-history.com</text>',
            "</g></svg>\n",
        ]
    )
    payload = svg.encode("utf-8")
    _validate_svg(payload)
    return payload


def _validate_svg(payload: bytes) -> None:
    try:
        decoded = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise StarHistoryError("generated SVG must be strict UTF-8") from exc
    if decoded.startswith("\ufeff") or "\x00" in decoded:
        raise StarHistoryError("generated SVG must be canonical UTF-8")
    upper = decoded.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper or "<?" in decoded:
        raise StarHistoryError("generated SVG contains forbidden XML directives")
    try:
        root = ET.fromstring(decoded)
    except ET.ParseError as exc:
        raise StarHistoryError("generated SVG is not valid XML") from exc
    ns = "{http://www.w3.org/2000/svg}"
    if root.tag != f"{ns}svg":
        raise StarHistoryError("generated SVG root is invalid")
    avatar_count = 0
    watermark_count = 0
    for element in root.iter():
        if not isinstance(element.tag, str) or not element.tag.startswith(ns):
            raise StarHistoryError("generated SVG contains a foreign namespace")
        for name, value in element.attrib.items():
            lowered = value.lower().replace(" ", "")
            if lowered.startswith(("http:", "https:", "//")):
                raise StarHistoryError("generated SVG contains an external resource")
            if "url(" in lowered and lowered not in {
                "url(#xkcdify)",
                "url(#clip-circle-title)",
            }:
                raise StarHistoryError("generated SVG contains an external resource")
        if element.tag == f"{ns}image":
            href = element.attrib.get("href", "")
            if href == OWNER_AVATAR_DATA_URI:
                avatar_count += 1
            elif href == WATERMARK_LOGO_DATA_URI:
                watermark_count += 1
            else:
                raise StarHistoryError("generated SVG contains an unreviewed image")
    if avatar_count != 1 or watermark_count != 1:
        raise StarHistoryError("generated SVG must contain both reviewed images")
    if 'id="xkcdify"' not in decoded or 'filter="url(#xkcdify)"' not in decoded:
        raise StarHistoryError("generated SVG is missing the chart filter")


def _output_payloads(state: Mapping[str, Any]) -> dict[Path, bytes]:
    return {
        STATE_RELATIVE: canonical_state_bytes(state),
        LIGHT_SVG_RELATIVE: render_svg(state, "light"),
        DARK_SVG_RELATIVE: render_svg(state, "dark"),
    }


def _write_outputs(workspace: Path, state: Mapping[str, Any]) -> bool:
    payloads = _output_payloads(state)
    targets = {relative: _target(workspace, relative) for relative in OUTPUT_RELATIVES}
    if all(
        target.exists() and target.read_bytes() == payloads[relative]
        for relative, target in targets.items()
    ):
        return False

    temporary_paths: dict[Path, Path] = {}
    try:
        for relative in OUTPUT_RELATIVES:
            target = targets[relative]
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(payloads[relative])
                handle.flush()
                os.fsync(handle.fileno())
                temporary_paths[relative] = Path(handle.name)
            os.chmod(temporary_paths[relative], 0o644)
        for relative in OUTPUT_RELATIVES:
            os.replace(temporary_paths[relative], targets[relative])
            temporary_paths.pop(relative, None)
    except OSError as exc:
        raise StarHistoryError("could not replace Star History outputs") from exc
    finally:
        for temporary in temporary_paths.values():
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    check_workspace(workspace)
    return True


def check_workspace(workspace: Path) -> None:
    state = load_state(workspace, require_canonical=True)
    expected = _output_payloads(state)
    for relative in OUTPUT_RELATIVES[1:]:
        actual = _read_limited(_target(workspace, relative), MAX_STATE_BYTES, str(relative))
        _validate_svg(actual)
        if actual != expected[relative]:
            raise StarHistoryError(f"{relative} is not synchronized with history.json")


def execute(
    command: str,
    *,
    workspace: Path,
    clock: Any | None = None,
    force: bool = False,
    star_count: int | None = None,
    starred_at: Sequence[datetime] | None = None,
    token: str | None = None,
) -> Result:
    root = _workspace_root(workspace)
    now = _normalize_now((clock or SystemClock()).now())

    if command == "backfill":
        if _target(root, STATE_RELATIVE).exists():
            raise StarHistoryError("history state already exists; refusing to overwrite")
        stamps = list(starred_at) if starred_at is not None else fetch_starred_at(token or resolve_token())
        state = build_backfill_state(stamps, now)
        changed = _write_outputs(root, state)
        return Result(changed, True, "historical Star data was reconstructed")

    if command == "due":
        return Result(False, _snapshot_due(load_state(root), now), "")

    if command in {"record", "update"}:
        state = load_state(root)
        due = _snapshot_due(state, now)
        if not due and not force:
            return Result(False, False, "snapshot is not due")
        if command == "update" and star_count is None:
            star_count = fetch_star_count(token or resolve_token())
        if star_count is None:
            raise StarHistoryError("a fetched Star count is required for recording")
        checked = _strict_non_negative_int(star_count, "stargazers_count")
        if checked > MAX_STAR_COUNT:
            raise StarHistoryError("Star count exceeded the supported range")
        updated = _updated_with_snapshot(state, now, checked)
        if updated == state:
            return Result(False, due, "same-day snapshot is unchanged")
        changed = _write_outputs(root, updated)
        return Result(changed, due, "Star snapshot and charts were updated")

    if command == "check":
        check_workspace(root)
        return Result(False, None, "Star History outputs are valid")

    raise StarHistoryError("unknown Star History command")


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("backfill", help="reconstruct history from starredAt timestamps")
    subparsers.add_parser("due", help=f"print whether a {INTERVAL_DAYS}-day snapshot is due")
    record = subparsers.add_parser("record", help="apply a fetched aggregate count")
    record.add_argument("--count-file", required=True, type=Path)
    record.add_argument("--force", action="store_true")
    update = subparsers.add_parser("update", help="fetch the current count and record if due")
    update.add_argument("--force", action="store_true")
    subparsers.add_parser("check", help="verify state and generated SVG files")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        star_count = (
            load_star_count_file(arguments.count_file)
            if arguments.command == "record"
            else None
        )
        result = execute(
            arguments.command,
            workspace=_repository_root(),
            force=bool(getattr(arguments, "force", False)),
            star_count=star_count,
        )
    except StarHistoryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print("error: unexpected internal error", file=sys.stderr)
        return 1

    if arguments.command == "due":
        print("true" if result.due else "false")
    else:
        print(result.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
