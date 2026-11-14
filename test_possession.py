"""Tests use invented data, not the supplied match."""

from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import possession as algorithm


def main():
    def point(label="H", source="motion", x=10.0):
        return algorithm.Evidence(label, 2 if source == "motion" else 0 if source == "tag" else 1, source, (x, 20), True)

    unknown = algorithm.Evidence("X", 0, "missing")
    dead = algorithm.Evidence("D", 1, "boundary", (-1, 20), False)
    assert algorithm.segment([point()] * 5) == list("HHHHH")
    assert algorithm.segment([point(source="proximity")] * 24) == ["X"] * 24
    assert algorithm.segment([point(source="proximity")] * 25) == ["H"] * 25
    assert algorithm.segment([point(source="tag")] * 49) == ["X"] * 49
    assert algorithm.segment([point(source="tag")] * 50) == ["H"] * 50
    assert algorithm.segment([point()] * 5, adaptive=False) == ["X"] * 5
    assert algorithm.segment([point()] * 5 + [point("A")] * 4 + [unknown]) == ["H"] * 10
    assert algorithm.segment([point()] * 5 + [point("A")] * 5) == list("HHHHHAAAAA")
    assert algorithm.segment([point(source="tag")] * 4 + [point()] * 5) == list("XXXXHHHHH")
    assert algorithm.segment([point("A")] * 4 + [unknown] + [point("A")] * 5) == list("XXXXXAAAAA")
    blocks = ((1, 5), (7, 11))
    assert algorithm.segment([point()] * 12, play_blocks=blocks) == list("XHHHHHXHHHHH")
    # Inclusive public block endpoints and reset of evidence across each half.
    for start, end in algorithm.PLAY_BLOCKS:
        assert algorithm.block_at(start - 1, algorithm.PLAY_BLOCKS) is None
        assert algorithm.block_at(start, algorithm.PLAY_BLOCKS) is not None
        assert algorithm.block_at(end, algorithm.PLAY_BLOCKS) is not None
        assert algorithm.block_at(end + 1, algorithm.PLAY_BLOCKS) is None
    assert algorithm.segment([dead] * 25 + [point(source="tag")] * 60) == ["D"] * 85
    assert algorithm.segment([dead] * 25 + [point()] * 20) == ["D"] * 45  # placement is not restart
    restart = [dead] * 25 + [point()] * 5 + [point(x=11.1)] * 5
    assert algorithm.segment(restart) == ["D"] * 30 + ["H"] * 5
    assert algorithm.segment(restart, restart_guard=False) == ["D"] * 25 + ["H"] * 10
    stopped = point("D", "stoppage")
    assert algorithm.segment([stopped] * 24) == ["X"] * 24
    assert algorithm.segment([stopped] * 25 + [point(x=11.1)] * 5) == ["D"] * 25 + ["H"] * 5
    assert algorithm.segment([stopped] * 25 + [unknown] * 10 + [point()] * 10) == ["D"] * 45
    assert algorithm.segment([]) == []
    for duration in (0, -1, True, 1.5):
        try:
            algorithm.segment([], confirm_frames=duration)
            raise AssertionError("Invalid duration accepted.")
        except ValueError:
            pass
    for item in (
        algorithm.Evidence("Z", 0, "missing"), algorithm.Evidence("D", 1, "tag"),
        algorithm.Evidence("H", 2, "rejected"), algorithm.Evidence("X", 0, "motion"),
        algorithm.Evidence("H", True, "motion"), algorithm.Evidence("H", 2, "motion", (float("nan"), 0), True),
        algorithm.Evidence("H", 2, "motion"), algorithm.Evidence("D", 1, "boundary", (0, 0), True),
        algorithm.Evidence("D", 1, "stoppage"), algorithm.Evidence("D", 1, "stoppage", (0, 0), False),
        algorithm.Evidence("D", 2, "stoppage", (0, 0), True),
        algorithm.Evidence("H", 1, "stoppage", (0, 0), True),
    ):
        try:
            algorithm.segment([item])
            raise AssertionError("Invalid evidence accepted.")
        except ValueError:
            pass
    for params in (
        {"unknown": 1}, {"relative_control_speed": 0},
        {"restart_distance": float("inf")}, {"max_ball_speed": "fast"},
        {"stationary_tolerance": -1},
    ):
        try:
            algorithm.settings(params)
            raise AssertionError("Invalid settings accepted.")
        except ValueError:
            pass

    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        raw = directory / "invented_tracking.txt"

        def run(balls, home=None, away=None, tags=None, **kwargs):
            home = home if home is not None else [(10, 20)] * len(balls)
            away = away if away is not None else [(50, 20)] * len(balls)

            def group(p):
                return "NaN,NaN,NaN" if p is None else f"{p[0] / 100},{p[1] / 60},NaN"

            raw.write_text(
                "".join(
                    f"{i + 1}:{group(h)};{group(a)}:{group(ball)}\n"
                    for i, (h, a, ball) in enumerate(zip(home, away, balls))
                ), encoding="utf-8",
            )
            return list(algorithm.observations(
                raw, ["H", "A"], len(balls), (100, 60),
                tagging=[algorithm.Tag(team) for team in tags] if isinstance(tags, str) else tags,
                **kwargs,
            ))

        moving = [(10 + i * 0.1, 20) for i in range(7)]
        observed = run(moving, home=moving)
        assert observed[0].source == "proximity"
        assert all(item.source == "motion" and item.label == "H" for item in observed[1:])
        assert algorithm.segment(observed) == list("XHHHHHH")
        # A passing ball near the opponent cannot become possession via distance or tags.
        passing = run([(49, 20), (50, 20), (51, 20)], tags="AAA")
        assert [item.source for item in passing] == ["proximity", "flight", "flight"]
        no_motion = run([(49, 20), (50, 20), (51, 20)], use_motion=False)
        assert all(item.label == "A" for item in no_motion)
        assert algorithm.segment(passing, confirm_frames=2) == ["X"] * 3
        assert algorithm.segment(no_motion, confirm_frames=2) == ["A"] * 3
        contested = run([(30, 20)], home=[(29.8, 20)], away=[(30.2, 20)], tags="H")
        assert contested[0].label == "X" and contested[0].source == "contested"
        assert run([None] * 50, tags="A" * 50)[0].source == "tag"
        assert algorithm.segment(run([None] * 50, tags="A" * 50)) == ["A"] * 50
        assert algorithm.segment(run([None] * 50, tags="A" * 50, use_tags=False)) == ["X"] * 50
        assert run([(10, 20), (1000, 20), (10, 20)], tags="AAA")[1].source == "rejected"
        assert run([(10, 20), (1000, 20)], use_guard=False)[1].label == "D"
        assert run([(10, 20), (50, 20), (50, 20)])[2].label == "A"  # reacquisition
        gap = run([(10, 20), None, (10, 20)])
        assert gap[-1].source == "proximity"  # no derivative across missing frame
        swapped = run([(10, 20), (10, 20)], home=[(99, 20), (10, 20)])
        assert swapped[-1].source == "proximity"  # tracklet jump cannot supply co-motion
        assert run([(-0.1, 20)])[0].label == "X"  # uncertain boundary projection
        assert run([(-1, 20)])[0].label == "D"
        halves = run([(10, 20), (10, 20), (1000, 20), (50, 20)], play_blocks=((0, 1), (3, 3)))
        assert halves[-1].label == "A" and halves[-1].source == "proximity"
        assert halves[2].source == "inactive"
        # Full raw-record flow: return/placement is not enough; controlled movement is.
        moving_restart = [(10 + 0.3 * i, 20) for i in range(1, 10)]
        balls = [(-1, 20)] * 25 + [(10, 20)] * 10 + moving_restart
        homes = [(10, 20)] * 35 + moving_restart
        assert algorithm.segment(run(balls, home=homes)) == ["D"] * 38 + ["H"] * 6
        # Preserve the established team during observed flight, then confirm the receiver.
        flight = [(10 + i, 20) for i in range(1, 11)]
        balls = [(10, 20)] * 6 + flight + [(20, 20)] * 6
        labels = algorithm.segment(run(balls, away=[(20, 20)] * len(balls), tags="A" * len(balls)))
        assert labels[1:16] == ["H"] * 15 and labels[16:] == ["A"] * 6
        # In-pitch dead balls need BOTH a set-piece cue and quiet, reliable control.
        cue = algorithm.Tag("X", True)
        quiet = [(10, 20)] * 30
        assert "D" not in algorithm.segment(run(quiet))
        preparation = run(quiet, tags=[cue] * 30)
        assert all(item.source == "stoppage" for item in preparation[1:])
        assert algorithm.segment(preparation) == ["X"] + ["D"] * 29
        assert "D" not in algorithm.segment(run(quiet[:25], tags=[cue] * 25))
        assert "D" not in algorithm.segment(run(quiet, tags=[cue] * 30, use_tags=False))
        assert "D" not in algorithm.segment(run(quiet, tags=[cue] * 30, use_motion=False))
        travelling = [(10 + 0.1 * i, 20) for i in range(50)]
        assert "D" not in algorithm.segment(run(travelling, home=travelling, tags=[cue] * 50))
        duel = run(quiet, home=[(9.8, 20)] * 30, away=[(10.2, 20)] * 30, tags=[cue] * 30)
        assert all(item.source == "contested" for item in duel)
        for home, away in (([None] * 30, [None] * 30), (None, [None] * 30), ([None] * 30, None)):
            assert "D" not in algorithm.segment(run(quiet, home=home, away=away, tags=[cue] * 30))
        jumping = run([(10, 20), (50, 20), (50, 20)], tags=[cue] * 3)
        assert jumping[1].source == "rejected" and all(item.source != "stoppage" for item in jumping)
        broken = quiet[:13] + [None] + quiet[:13]
        assert "D" not in algorithm.segment(run(broken, tags=[cue] * len(broken)))
        # Cue expiry and missing tracking do not restart a stationary dead ball.
        expiring = [cue] * 30 + [algorithm.Tag("H")] * 30
        assert algorithm.segment(run(quiet * 2, tags=expiring)) == ["X"] + ["D"] * 59
        # Controlled movement resumes play; a broad cue cannot mark a later pause dead.
        movement = [(10 + 0.3 * i, 20) for i in range(1, 10)]
        sequence = quiet + movement + [None] + [movement[-1]] * 30
        homes = quiet + movement + [movement[-1]] * 31
        resumed = run(sequence, home=homes, tags=[cue] * len(sequence))
        assert algorithm.segment(resumed) == ["X"] + ["D"] * 32 + ["H"] * 37
        assert all(item.source != "stoppage" for item in resumed[30:])
        # A genuinely new cue can re-arm; a gap by itself cannot.
        sequence += [movement[-1]] * 31
        homes += [movement[-1]] * 31
        renewed = [cue] * 70 + [algorithm.Tag("X")] + [cue] * 30
        assert algorithm.segment(run(sequence, home=homes, tags=renewed))[-30:] == ["D"] * 30
        # Even an unbroken tag interval starts afresh in the next half.
        sequence = travelling + [travelling[-1]] * 30
        halves = run(sequence, home=sequence, tags=[cue] * 80, play_blocks=((0, 49), (50, 79)))
        assert halves[50].source == "proximity" and halves[51].source == "stoppage"
        assert algorithm.segment(halves, play_blocks=((0, 49), (50, 79)))[50:] == ["X"] + ["D"] * 29
        assert run([]) == []
        for tags in ("H", "HHH", "HD", [algorithm.Tag("H", 1)] * 2, [("H", True)] * 2):
            try:
                run([(10, 20)] * 2, tags=tags)
                raise AssertionError("Invalid tags accepted.")
            except ValueError:
                pass
        for record, n in (
            ("2:0.1,0.5,0;0.9,0.5,0:0.1,0.5,0\n", 1),
            ("1:0.1,0.5,0:0.1,0.5,0\n", 1),
            ("1:bad,0.5,0;0.9,0.5,0:0.1,0.5,0\n", 1),
            ("1:0.1,0.5,0;0.9,0.5,0:inf,0.5,0\n", 1),
            ("1:0.1,0.5,0;0.9,0.5,0:0.1,0.5,0\n", 2),
        ):
            raw.write_text(record, encoding="utf-8")
            try:
                list(algorithm.observations(raw, ["H", "A"], n, (100, 60)))
                raise AssertionError("Invalid tracking accepted.")
            except ValueError:
                pass
        output = directory / "invented_output.csv"
        for iteration in range(2):
            labels = algorithm.segment(run(moving, home=moving))
            algorithm.write_csv(output, labels, len(moving))
            algorithm.validate_csv(output, len(moving))
            if iteration == 0:
                saved = output.read_bytes()
            else:
                assert output.read_bytes() == saved
        try:
            algorithm.write_csv(output, ["H"], len(moving))
            raise AssertionError("Short output accepted.")
        except ValueError:
            assert output.read_bytes() == saved
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "invented.txt"

        def run(balls, visible=0, **kwargs):
            def group(point):
                return "NaN,NaN,NaN" if point is None else f"{point[0] / 100},{point[1] / 60},NaN"

            path.write_text("".join(
                f"{i + 1}:{group((10, 20) if i < visible else None)};"
                f"{group((50, 20) if i < visible else None)}:{group(ball)}\n"
                for i, ball in enumerate(balls)
            ), encoding="utf-8")
            return list(algorithm.observations(
                path, ["H", "A"], len(balls), (100, 60),
                tagging=[algorithm.Tag("A")] * len(balls), **kwargs,
            ))

        balls = [(10, 20)] * 6 + [(10 + 0.2 * (i + 1), 20) for i in range(55)]
        evidence = run(balls, visible=6)
        assert all(item.source == "flight" for item in evidence[6:])
        assert algorithm.segment(evidence) == ["X"] + ["H"] * 60
        assert all(item.source == "flight" for item in run(balls, visible=6, use_tags=False)[6:])
        assert algorithm.segment(run(balls, visible=6, use_motion=False))[6:] == ["A"] * 55
        # With no motion evidence, the existing weak fallback is still available.
        stationary = run([(10, 20)] * 50)
        assert all(item.source == "tag" for item in stationary)
        assert algorithm.segment(stationary) == ["A"] * 50
        gap = run([(10, 20), None, (11, 20), (11.2, 20)])
        assert [item.source for item in gap] == ["tag", "tag", "tag", "flight"]
        assert run([(10, 20), (1000, 20)])[1].source == "rejected"
        assert run([(10, 20), (10.2, 20)], play_blocks=((0, 0), (1, 1)))[1].source == "tag"
        assert run([(-0.1, 20)])[0].source == "ambiguous"
        assert run([(-1, 20)])[0].source == "boundary"
        # Reject dangerous output paths before any dataset is read.
        for output in (
            Path(directory) / "source.py",
            Path(directory) / ".git" / "result.csv",
            Path(directory) / ".venv" / "result.csv",
            Path(directory) / "node_modules" / "result.csv",
            Path(directory) / "result.csv",  # Inside the requested input folder.
        ):
            failed = subprocess.run([
                sys.executable, str(Path(algorithm.__file__).resolve()),
                "--data-dir", directory, "--out", str(output),
            ], capture_output=True)
            assert failed.returncode == 2 and not output.exists()
        protected = Path(directory) / "source.py"
        protected.write_text("# invented source\n", encoding="utf-8")
        subprocess.run([
            sys.executable, str(Path(algorithm.__file__).resolve()),
            "--data-dir", directory, "--out", str(protected),
        ], capture_output=True, check=False)
        assert protected.read_text(encoding="utf-8") == "# invented source\n"
    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory).resolve()
        metadata = directory / "invented_metadata.xml"
        metadata.write_text(
            '<root><Team id="home"/><Team id="away"/>'
            '<Player teamId="home"/><Player teamId="away"/></root>', encoding="utf-8",
        )
        assert algorithm.track_teams(metadata) == ["H", "A"]
        for xml in (
            '<root><Team id="home"/><Player teamId="home"/></root>',
            '<root><Team id="home"/><Team id="home"/><Player teamId="home"/></root>',
            '<root><Team id="home"/><Team id="away"/><Player teamId="unknown"/></root>',
        ):
            metadata.write_text(xml, encoding="utf-8")
            try:
                algorithm.track_teams(metadata)
                raise AssertionError("Invalid team metadata accepted.")
            except ValueError:
                pass
        tags = directory / "invented_tags.xml"
        tag_root = ET.Element("root")
        for start, end, code, team in (
            (0, 4, "BUILD UP", "Barcelona"),
            (2, 4, "PROGRESSION", "Atletic Club"),
            (4, 6, "Defending in middle third", "Barcelona"),
            (6, 7, "SET PIECES", "Barcelona"),
            (7, 8, "PROGRESSION", "Athletic Club"),
        ):
            event = ET.SubElement(tag_root, "instance")
            for name, value in (("start", start), ("end", end), ("code", code)):
                ET.SubElement(event, name).text = str(value)
            label = ET.SubElement(event, "label")
            ET.SubElement(label, "group").text = "TEAM"
            ET.SubElement(label, "text").text = team
        ET.ElementTree(tag_root).write(tags, encoding="utf-8")
        expected = [algorithm.Tag(team, frame == 6) for frame, team in enumerate("HHXXAAXA")]
        assert list(algorithm.tagging_evidence(tags, 8, fps=1)) == expected
        # Overlapping and unknown-team cues merge; negative/empty/outside intervals are clipped.
        for start, end, team in ((5, 8, "Unknown"), (6, 9, ""), (1, 1, ""), (-3, -1, ""), (9, 10, "")):
            event = ET.SubElement(tag_root, "instance")
            for name, value in (("start", start), ("end", end), ("code", " set  PIECES ")):
                ET.SubElement(event, name).text = str(value)
            if team:
                label = ET.SubElement(event, "label")
                ET.SubElement(label, "group").text = "Team"
                ET.SubElement(label, "text").text = team
        ET.ElementTree(tag_root).write(tags, encoding="utf-8")
        assert list(algorithm.tagging_evidence(tags, 8, fps=1)) == [
            algorithm.Tag(team, frame >= 5) for frame, team in enumerate("HHXXAAXA")
        ]
        for rows, fps in ((-1, 25), (True, 25), (8, 0), (8, True), (8, float("nan"))):
            try:
                list(algorithm.tagging_evidence(tags, rows, fps=fps))
                raise AssertionError("Invalid phase timeline accepted.")
            except ValueError:
                pass
        for start, end in (("NaN", "1"), ("2", "1"), ("", "1"), ("0", "inf")):
            tags.write_text(
                f"<root><instance><start>{start}</start><end>{end}</end>"
                "<code>BUILD UP</code></instance></root>", encoding="utf-8",
            )
            try:
                list(algorithm.tagging_evidence(tags, 8))
                raise AssertionError("Invalid automatic phase accepted.")
            except ValueError:
                pass
    print("PASS: synthetic control, phases, motion, restarts, timeline, validation and reproducibility.")


if __name__ == "__main__":
    main()
