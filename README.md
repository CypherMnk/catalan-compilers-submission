# More than a Hack 2027 - Ball Possession

**Team: Catalan compilers**

Our entry for Metrica Sports' [More than a Hack 2027](https://github.com/metrica-sports/more-than-a-hack-2027)
Initial Challenge predicts which team has possession at each frame of the match.
It runs locally using automatic tracking and Smart Tagging, without the video.

## Inputs

Place these three supplied files in a folder named `Tactical`:

| File | Purpose |
|---|---|
| `BAR-ATH_tactical_atd.txt` | Ball and available player positions at each frame. |
| `BAR-ATH_tactical_atd.xml` | Match metadata and the team for each player-tracking slot. |
| `BAR-ATH_tactical_smart_tagging.xml` | Automatic phases of play used as supporting evidence. |

Match data is not included in this repository and must be obtained separately.

## How it works

The algorithm looks for a player close to the ball. If opponents are visible,
that player must be clearly closer than the nearest opponent. Moving with the
ball strengthens that evidence; a fast pass or brief challenge does not
automatically change possession.

It waits for consistent evidence before switching teams and keeps the last
confirmed team when the data is unclear. Automatic phases provide weak support
when tracking is missing or ambiguous. It also filters implausible ball jumps
and checks for the ball leaving the pitch. For some in-pitch stoppages, it
combines a set-piece tag with sustained near-stationary tracking. Restarting
requires observed ball movement and confirmed control, not just a tag.

## Run

Use **Python 3.10 or newer**. No additional packages or model weights are needed.
From the repository root:

```sh
python possession.py --data-dir "Tactical" --out "outputs/Catalan compilers.csv"
```

Replace `Tactical` with your input folder if it is elsewhere. Inputs are not modified.

The CSV has a `frame,label` header and one row per frame, numbered from zero:

| Label | Meaning |
|---|---|
| `H` | Home-team possession |
| `A` | Away-team possession |
| `D` | Dead ball |
| `X` | Unknown or outside the evaluated timeline |

See [Catalan compilers.md](Catalan%20compilers.md) for the approach, possession
rules, training-data statement and limitations.
