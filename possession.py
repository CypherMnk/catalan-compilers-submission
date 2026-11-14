"""Predict team possession from automatic tracking and phases of play."""

import argparse
import csv
from itertools import zip_longest
import math
import os
from pathlib import Path
import tempfile
from typing import NamedTuple
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent


FRAME_COUNT = 199319


PLAY_BLOCKS = ((11185, 90651), (110808, 190197))


ATTACK_CODES = {
    "build up", "progression", "creating chances", "long ball",
    "ball in final third", "ball in the box", "attacking transition",
}


DEFENCE_CODES = {
    "defending in attacking third", "defending in middle third",
    "defending in defensive third",
}


TAG_TEAMS = {"barcelona": "H", "atletic club": "A", "athletic club": "A"}


def track_teams(path):
    """Use the team/slot order specified by the public starter's EPTS loader."""
    root = ET.parse(path).getroot()
    teams = [team.get("id") for team in root.iter("Team")]
    if len(teams) != 2 or None in teams or len(set(teams)) != 2:
        raise ValueError("Metadata must declare two distinct team IDs.")
    mapping = dict(zip(teams, ("H", "A")))
    slots = [player.get("teamId") for player in root.iter("Player")]
    if not slots or any(team not in mapping for team in slots):
        raise ValueError("Tracking slots must belong to a declared team.")
    return [mapping[team] for team in slots]


def position(group):
    values = group.strip().split(",")
    if len(values) != 3:
        raise ValueError("Expected x,y,speed.")
    x, y, speed = map(float, values)
    if math.isinf(x) or math.isinf(y) or math.isinf(speed):
        raise ValueError("Infinite tracking value.")
    return (x, y) if math.isfinite(x) and math.isfinite(y) else None


def tagging_evidence(path, expected_rows, fps=25):
    """Convert automatic phases to weak H/A evidence on half-open frame intervals.

    Conflicting teams produce X, regardless of the number of overlapping tags.
    Set pieces, goals, player counts, and defensive transitions are deliberately
    excluded: their intervals do not establish the exact live-ball state.
    """
    differences = {team: [0] * (expected_rows + 1) for team in ("H", "A")}
    for event in ET.parse(path).iter("instance"):
        start = float(event.findtext("start", ""))
        end = float(event.findtext("end", ""))
        if not math.isfinite(start) or not math.isfinite(end) or end < start:
            raise ValueError("Invalid automatic tag interval.")
        code = " ".join(event.findtext("code", "").casefold().split())
        teams = {
            " ".join(label.findtext("text", "").casefold().split())
            for label in event.findall("label")
            if label.findtext("group", "").strip().casefold() == "team"
        }
        # Unknown, absent, or multiple distinct Team values are not evidence.
        side = TAG_TEAMS.get(next(iter(teams))) if len(teams) == 1 else None
        if side is None or code not in ATTACK_CODES | DEFENCE_CODES:
            continue
        if code in DEFENCE_CODES:
            side = "A" if side == "H" else "H"
        start_frame = round(max(0, min(start, expected_rows / fps)) * fps)
        end_frame = round(max(0, min(end, expected_rows / fps)) * fps)
        differences[side][start_frame] += 1
        differences[side][end_frame] -= 1
    # difference arrays avoid scanning every event per frame;
    # no learned weights or match-derived duration rules.
    home = away = 0
    for frame in range(expected_rows):
        home += differences["H"][frame]
        away += differences["A"][frame]
        yield "H" if home and not away else "A" if away and not home else "X"


def validate_csv(path, expected_rows):
    """Ground-truth-free contract check; no output labels or statistics printed."""
    with Path(path).open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        if next(reader, None) != ["frame", "label"]:
            raise ValueError("CSV header must be frame,label.")
        count = 0
        for frame, row in enumerate(reader):
            if len(row) != 2 or row[0] != str(frame) or row[1] not in {"H", "A", "D", "X"}:
                raise ValueError("CSV contains an invalid row.")
            count += 1
        if count != expected_rows:
            raise ValueError("CSV row count is incorrect.")


def write_csv(path, labels, expected_rows):
    """Validate a temporary file before atomically replacing an existing output."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        try:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(("frame", "label"))
            for frame, label in enumerate(labels):
                writer.writerow((frame, label))
        except BaseException:
            handle.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        validate_csv(temporary, expected_rows)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


DEFAULTS = {
    "control_radius": 2.0,
    "team_margin": 0.5,
    "max_ball_speed": 60.0,
    "max_player_speed": 15.0,
    "relative_control_speed": 3.0,
    "boundary_margin": 0.25,
    "confirm_seconds": 1.0,
    "strong_confirm_seconds": 0.2,
    "tag_confirm_seconds": 2.0,
    "dead_confirm_seconds": 1.0,
    "restart_distance": 1.0,
}


class Evidence(NamedTuple):
    label: str
    strength: int  # Ordinal support: 0 tag/unknown, 1 proximity/boundary, 2 co-motion.
    source: str
    ball: tuple | None = None  # Metres, never invented/interpolated coordinates.
    inside: bool = False


def settings(params=None):
    if params is not None and set(params) - DEFAULTS.keys():
        raise ValueError("Unknown parameter; external tuning must use named settings.")
    result = DEFAULTS | (params or {})
    if any(
        not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v <= 0
        for v in result.values()
    ):
        raise ValueError("Parameters must be positive finite numbers.")
    return result


def block_at(frame, play_blocks):
    return 0 if play_blocks is None else next(
        (i for i, (start, end) in enumerate(play_blocks) if start <= frame <= end), None,
    )


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def records(path, teams, expected_rows, pitch):
    """Parse player and ball records without shifting the timeline."""
    if (
        not teams or any(team not in {"H", "A"} for team in teams)
        or not isinstance(expected_rows, int) or isinstance(expected_rows, bool) or expected_rows < 0
        or len(pitch) != 2 or any(not math.isfinite(v) or v <= 0 for v in pitch)
    ):
        raise ValueError("Invalid tracking metadata, timeline, or pitch.")
    count = 0
    with Path(path).open(encoding="utf-8-sig") as handle:
        for count, line in enumerate(handle, 1):
            try:
                frame, player_text, ball_text = line.strip().split(":")
                groups = player_text.split(";")
                if int(frame) != count or count > expected_rows or len(groups) != len(teams):
                    raise ValueError("Invalid tracking layout.")
                points = [position(group) for group in groups] + [position(ball_text)]
                points = [
                    None if point is None else (point[0] * pitch[0], point[1] * pitch[1])
                    for point in points
                ]
                if any(point is not None and not all(map(math.isfinite, point)) for point in points):
                    raise ValueError("Position scaling overflow.")
            except (ValueError, OverflowError):
                raise ValueError(f"Invalid tracking record {count}; inspect locally.") from None
            yield points[:-1], points[-1]
    if count != expected_rows:
        raise ValueError("Tracking row count does not match the requested timeline.")


def control(players, teams, ball, previous_players, previous_ball, pitch, fps, params, use_motion):
    inside = 0 <= ball[0] <= pitch[0] and 0 <= ball[1] <= pitch[1]
    outside = max(-ball[0], ball[0] - pitch[0], -ball[1], ball[1] - pitch[1], 0)
    if outside > params["boundary_margin"]:
        return Evidence("D", 1, "boundary", ball, False)
    if not inside:
        return Evidence("X", 0, "ambiguous", ball, False)
    ball_velocity = None
    if use_motion and previous_ball is not None:
        ball_velocity = tuple((now - old) * fps for now, old in zip(ball, previous_ball))
    fast_ball = ball_velocity is not None and math.hypot(*ball_velocity) > params["relative_control_speed"]
    nearest = {}
    for slot, (team, player) in enumerate(zip(teams, players)):
        if player is not None:
            separation = distance(player, ball)
            if team not in nearest or separation < nearest[team][0]:
                nearest[team] = separation, slot
    if not nearest:
        # Missing players do not erase trusted ball motion. This is a veto on
        # weak tag evidence, not proof that the ball is uncontrolled.
        return Evidence("X", 0, "flight" if fast_ball else "ambiguous", ball, True)
    team = min(nearest, key=lambda side: nearest[side][0])
    separation, slot = nearest[team]
    other_distance = nearest.get("A" if team == "H" else "H", (math.inf, None))[0]
    if separation > params["control_radius"]:
        return Evidence("X", 0, "flight" if fast_ball else "ambiguous", ball, True)
    if other_distance - separation <= params["team_margin"]:
        return Evidence("X", 0, "contested", ball, True)
    if ball_velocity is not None:
        previous_player = None if previous_players is None else previous_players[slot]
        if previous_player is not None:
            player_velocity = tuple(
                (now - old) * fps for now, old in zip(players[slot], previous_player)
            )
            if math.hypot(*player_velocity) <= params["max_player_speed"]:
                relative_speed = math.hypot(*(
                    vb - vp for vb, vp in zip(ball_velocity, player_velocity)
                ))
                if relative_speed > params["relative_control_speed"]:
                    return Evidence("X", 0, "flight", ball, True)
                return Evidence(team, 2, "motion", ball, True)
        if fast_ball:
            return Evidence("X", 0, "flight", ball, True)
    return Evidence(team, 1, "proximity", ball, True)


def observations(
    path, teams, expected_rows, pitch, control_radius=2.0, team_margin=0.5, *,
    fps=25, tagging=None, play_blocks=None, params=None,
    use_motion=True, use_guard=True, use_tags=True,
):
    params = settings({"control_radius": control_radius, "team_margin": team_margin} | (params or {}))
    if isinstance(fps, bool) or not math.isfinite(fps) or fps <= 0:
        raise ValueError("Frame rate must be positive and finite.")
    if tagging is None:
        tagging = ("X" for _ in range(expected_rows))
    anchor = previous_raw = previous_ball = previous_players = previous_block = None
    for frame, (record, tag) in enumerate(zip_longest(records(path, teams, expected_rows, pitch), tagging)):
        if record is None or tag not in {"H", "A", "X"}:
            raise ValueError("Automatic tags or timeline lengths are invalid.")
        players, ball = record
        block = block_at(frame, play_blocks)
        if block != previous_block or block is None:
            anchor = previous_raw = previous_ball = previous_players = None
        previous_block = block
        if block is None:
            yield Evidence("X", 0, "inactive")
            continue
        if ball is None:
            previous_raw = previous_ball = previous_players = None
            evidence = Evidence("X", 0, "missing")
        else:
            plausible = not use_guard or anchor is None or any(
                distance(ball, sample[1]) <= params["max_ball_speed"] * (frame - sample[0]) / fps
                for sample in (anchor, previous_raw) if sample is not None
            )
            previous_raw = frame, ball
            if not plausible:
                previous_ball = previous_players = None
                yield Evidence("X", 0, "rejected")
                continue
            anchor = previous_raw
            evidence = control(
                players, teams, ball, previous_players, previous_ball, pitch, fps, params, use_motion,
            )
            previous_ball, previous_players = ball, players
        # Observed flight, duels and rejected jumps veto tag fallback. Missing or
        # otherwise ambiguous tracking may use a slower, weak automatic phase.
        if (
            use_tags and tag != "X" and evidence.label == "X"
            and evidence.source in {"missing", "ambiguous"}
            and (evidence.ball is None or evidence.inside)
        ):
            evidence = Evidence(tag, 0, "tag", evidence.ball, evidence.inside)
        yield evidence


def segment(
    evidence, confirm_frames=None, play_blocks=None, *, fps=25, params=None,
    adaptive=True, restart_guard=True,
):
    params = settings(params)
    if isinstance(fps, bool) or not math.isfinite(fps) or fps <= 0:
        raise ValueError("Frame rate must be positive and finite.")
    if confirm_frames is None:
        confirm_frames = max(1, math.ceil(params["confirm_seconds"] * fps))
    if not isinstance(confirm_frames, int) or isinstance(confirm_frames, bool) or confirm_frames < 1:
        raise ValueError("Confirmation duration must be a positive integer.")
    durations = {
        "motion": max(1, math.ceil(params["strong_confirm_seconds"] * fps)),
        "proximity": confirm_frames,
        "tag": max(1, math.ceil(params["tag_confirm_seconds"] * fps)),
        "boundary": max(1, math.ceil(params["dead_confirm_seconds"] * fps)),
    }
    sources = {
        "motion", "proximity", "tag", "boundary", "missing", "ambiguous",
        "contested", "flight", "rejected", "inactive",
    }
    state, pending, count, onset, previous_block, placement = "X", None, 0, None, None, None
    labels = []
    for frame, item in enumerate(evidence):
        if (
            not isinstance(item, Evidence) or item.label not in {"H", "A", "D", "X"}
            or item.source not in sources or not isinstance(item.strength, int)
            or isinstance(item.strength, bool) or item.strength not in {0, 1, 2}
            or item.strength != (2 if item.source == "motion" else 1 if item.source in {"proximity", "boundary"} else 0)
            or not isinstance(item.inside, bool)
            or (item.ball is not None and (len(item.ball) != 2 or not all(map(math.isfinite, item.ball))))
            or (item.inside and item.ball is None)
            or (item.source in {"motion", "proximity"} and (item.ball is None or not item.inside))
            or (item.source == "boundary" and (item.ball is None or item.inside))
            or (item.label in {"H", "A"} and item.source not in {"motion", "proximity", "tag"})
            or (item.label == "D" and item.source != "boundary")
            or (item.label == "X" and item.source in durations)
        ):
            raise ValueError("Invalid control evidence.")
        block = block_at(frame, play_blocks)
        if block is None:
            state, pending, count, onset, previous_block, placement = "X", None, 0, None, None, None
            labels.append("X")
            continue
        if block != previous_block:
            state, pending, count, onset, placement = "X", None, 0, None, None
        previous_block = block
        label = item.label
        if state == "D":
            if item.ball is not None and not item.inside:
                placement = None
            elif item.ball is not None and placement is None:
                placement = item.ball
            if label in {"H", "A"} and (
                item.source == "tag"
                or (restart_guard and (
                    not item.inside or item.ball is None or placement is None
                    or distance(item.ball, placement) < params["restart_distance"]
                ))
            ):
                label = "X"
        labels.append(state)
        if label == "X" or label == state:
            pending, count, onset = None, 0, None
            continue
        required = durations[item.source] if adaptive else confirm_frames
        key = label, required
        # Do not let one strong frame retrospectively upgrade a weak/tag streak.
        if key != pending:
            pending, count, onset = key, 0, frame
        count += 1
        if count >= required:
            state = label
            # offline O(frames) labels; bounded-lookahead
            # streaming only if a longer recording makes memory a bottleneck.
            labels[onset:frame + 1] = [state] * (frame - onset + 1)
            pending, count, onset = None, 0, None
            placement = None
    return labels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "Tactical")
    parser.add_argument("--out", type=Path, default=ROOT / "outputs" / "Catalan compilers.csv")
    args = parser.parse_args()
    data_dir = args.data_dir.resolve()
    output = args.out.resolve()
    if output.suffix.casefold() != ".csv":
        parser.error("Output must be a CSV file.")
    if any(part.casefold() in {".git", ".venv", "venv", "node_modules"} for part in output.parts):
        parser.error("Do not write outputs inside repository metadata or dependency folders.")
    if output.is_relative_to(data_dir):
        parser.error("Write outputs outside the input data directory.")
    try:
        teams = track_teams(data_dir / "BAR-ATH_tactical_atd.xml")
        tags = tagging_evidence(
            data_dir / "BAR-ATH_tactical_smart_tagging.xml", FRAME_COUNT,
        )
        evidence = observations(
            data_dir / "BAR-ATH_tactical_atd.txt", teams, FRAME_COUNT, (105.3, 68.0),
            tagging=tags, play_blocks=PLAY_BLOCKS,
        )
        write_csv(output, segment(evidence, play_blocks=PLAY_BLOCKS), FRAME_COUNT)
    except (OSError, ValueError, ET.ParseError):
        parser.exit(1, "Local processing failed. Inspect inputs locally; no contents disclosed.\n")
    print("PASS: CSV generated and format checked. Accuracy not assessed.")


if __name__ == "__main__":
    main()
