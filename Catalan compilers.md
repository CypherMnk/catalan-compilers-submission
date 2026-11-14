# Catalan compilers

More than a Hack 2027 - Initial Challenge

## 1. Approach

We built a rule-based algorithm that estimates team possession from automatic
player and ball tracking. It uses proximity, movement and consistent evidence
over time rather than assigning possession to whichever player is nearest.

We chose this approach because the supplied positions can be used directly,
without training a model or processing the video. It runs locally and produces
the same output from the same inputs.

## 2. Assets used

| Asset | How we use it |
|---|---|
| `BAR-ATH_tactical_atd.txt` | Ball and available player positions at each frame. |
| `BAR-ATH_tactical_atd.xml` | Match metadata and team membership of player-tracking slots. |
| `BAR-ATH_tactical_smart_tagging.xml` | Automatic phases as weak support when tracking is unclear. |

Coordinates are converted to metres using a 105.3 by 68 metre pitch. Movement
is calculated from consecutive positions at 25 frames per second. Missing
positions are not filled in, and tracking slots are not treated as permanent
player identities.

We do not use the video, Broadcast data, homography or audio. No manual
annotations or corrections from the supplied game are used.

## 3. Training data

No labelled datasets were used, and no model training, fitting or calibration
was performed. The parameters are fixed engineering assumptions, not values
tuned on the supplied game, video or ground-truth possession.

Invented examples are used for software tests only. They do not measure
football accuracy, and we have not obtained an external accuracy score.

## 4. Possession rules

- **Control:** a player must be within 2 metres of the ball and more than
  0.5 metres closer than the nearest observed opponent. Moving with the ball
  strengthens the evidence; excessive relative motion rejects it.
- **Loose balls and challenges:** a fast passing ball or close contest does
  not establish a change. The last confirmed label is retained until new
  control is confirmed. Before the first confirmation, the label is `X`.
- **Automatic phases:** tags can support missing or ambiguous tracking, but
  cannot override a close contest, observed ball flight or a rejected position
  jump. The motion check still applies when all player observations are missing.
- **Confirmation:** control supported by movement needs 0.2 seconds of
  consecutive evidence; proximity alone needs 1 second and tags need 2 seconds.
  Missing or conflicting evidence resets a pending change.
- **Dead balls and restarts:** the ball must remain more than 0.25 metres
  outside the pitch for 1 second to establish `D`. Returning to possession
  requires the ball to be inside, move at least 1 metre from its restart
  placement and show confirmed player control. Tags alone cannot restart play.
- **Tracking quality and timeline:** implausible ball jumps are filtered.
  State resets between halves, and frames outside the documented active
  periods are `X`.

The algorithm works offline. Once a change is confirmed, it labels the
confirming sequence from its start rather than only from the final frame.

## 5. Limitations and improvements

Proximity and 2D movement cannot prove control, especially without ball height.
Missing players, slot changes and tracking errors can produce wrong decisions.
Keeping the previous team through uncertainty can extend an incorrect possession,
and broad automatic phases can miss turnovers. Stoppages inside the pitch are
not detected, and restart confirmation can delay a genuine restart.

With more time, we would evaluate and tune the rules on licensed external
development matches, then test on separate held-out matches.

## 6. Reproduction

Use [our source repository](https://github.com/CypherMnk/catalan-compilers-submission)
with **Python 3.10 or newer**. Inference uses only the standard library, with
no packages to install or model weights to download.

Place the three input files listed above in `Tactical`, then run from the
repository root:

```sh
python possession.py --data-dir "Tactical" --out "outputs/Catalan compilers.csv"
```

Use your actual input folder if it is elsewhere. The command leaves inputs
unchanged and writes a `frame,label` CSV with 199,319 rows, numbered 0 to 199318.
Labels are `H` (home), `A` (away), `D` (dead ball) and `X` (unknown or outside
the evaluated timeline).

The command checks CSV structure, not prediction accuracy. Match assets and
generated results are not included in the public repository.
