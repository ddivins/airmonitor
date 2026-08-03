# Filter comparison: baseline vs. chamber filter vs. room filter (EXP1–EXP3)

**Printer:** Bambu X1-Carbon, same `.3mf` file and ABS spool (GFB99, `#76D9F4`) for every run.
**Sensor:** fixed position at the top of the enclosure, near the AMS filament feed-through — a
known, unsealed leak point on this printer, not the chamber's own exhaust port.
**Dashboard:** [AirMonitor Compare Prints](../../grafana/dashboards/airmonitor-compare-prints.json),
which overlays VOC (SGX sensor) and PM2.5 (SPS30 sensor) time series for two prints, aligned to
minutes-since-print-start.
**Room filter:** Levoit Core 400S, rated for 400 sq ft, used in a 255 sq ft room — meaningfully
oversized (~1.6x rated capacity) for this space.
**"No filter" (EXP1-baseline):** means *no filtration at all* — not just Bento/Levoit disabled.
The X1-Carbon's own built-in chamber filter cartridge was physically removed for this run, so
EXP1 represents the printer's raw, completely unfiltered emissions, not "stock filter only."

| Run | Condition | VOC avg | VOC max | PM2.5 max | Duration |
|---|---|---|---|---|---|
| EXP1-baseline | No filtration | 0.81 ppm | 2.0 ppm | 55.1 µg/m³ | 155 min |
| EXP2-bento-only | Chamber-adjacent HEPA+carbon (Bento), fan on | 1.58 ppm | 3.70 ppm | 33.9 µg/m³ | 159 min |
| EXP3-levoit-only | Standalone room HEPA+carbon (Levoit), fan speed 4 | ~0 ppm* | 2.30 ppm* | 9.51 µg/m³ | 168 min |

*EXP3's VOC number needs a footnote — see below.

## EXP1 vs. EXP2: the chamber filter helps PM, and makes VOC worse

![EXP1 vs EXP2](images/exp1-vs-exp2-full.png)

Bento (HEPA + activated carbon, mounted at the printer's own chamber exhaust) roughly **halves peak
PM2.5** compared to baseline — the huge, sustained ~50 µg/m³ trending into the print disappears down
to isolated small peaks. But VOC goes the *other* direction: baseline averaged 0.81 ppm, Bento
averaged 1.58 ppm, almost double.

This isn't a measurement error. It's a real, physically-grounded result: Bento's fan creates
negative pressure inside the chamber, which pulls more total makeup air through *every* unsealed
path — including the sensor's own leak point at the top seam — not just through Bento's own ducted
intake. Whatever fraction of that air exits through the leak never touches the carbon media at all.
Particulates get knocked out along the way regardless (inertial deposition in ductwork and turns
doesn't require a filter to "catch" them), which is why PM still improves. Gas-phase VOC molecules
have no equivalent free ride — carbon adsorption only works if the gas spends real residence time
in contact with the media, and a bypass path is a complete skip, not a partial one. Net effect: more
total airflow through a leaky enclosure works *for* PM containment and *against* VOC containment,
simultaneously, from the same fan.

## EXP1 vs. EXP3: the room filter doesn't touch the leak, and that's the point

![EXP1 vs EXP3](images/exp1-vs-exp3-full.png)

Levoit is a standalone HEPA+carbon room purifier — it processes air *after* it's already escaped
into the room, completely independent of whatever is or isn't sealed on the printer's own
enclosure. It was switched on manually about 18 minutes before EXP3 started (verified via the
`airmonitor-levoit` service log: `Turning purifier ON ... Setting purifier fan speed: 4` at
2026-08-03 00:44:21 EDT); the VOC chart shows the tail of that decay — from ~2.3 ppm down to 0 —
completing right around print start, then holding flat at the sensor's resolution floor for the
entire 2h48m print. PM2.5 also improves over baseline, though less dramatically than Bento (a
standalone room unit further from the source has less throughput at the print itself).

Worth noting: this unit is rated for 400 sq ft and the room is only 255 sq ft, so it's delivering
meaningfully more air changes per hour here than its rating implies for a room this size. That
headroom is likely a real contributor to how completely it suppressed VOC — a 400S running at the
edge of its rated capacity in a larger room would plausibly show a smaller effect.

*Footnote on EXP3's VOC average: because the reading is genuinely pinned at the sensor's ~0.1 ppm
resolution floor for the whole print, "average" isn't a meaningful number the way it is for the
other two runs — there's no real signal above the floor to average. It isn't a sensor fault (the
sensor's temperature/humidity channels varied normally throughout on the same frames, and the SPS30
PM sensor kept reporting real data too) — it's the Levoit legitimately holding VOC below what this
setup can detect.

## Practical takeaway

For VOC specifically, filter *position relative to the enclosure's leak* matters more than
filtration technology. A chamber-adjacent filter that isn't airtight-ducted to the chamber is
fighting a battle it can't win on gas-phase emissions — adding fan-driven airflow can actively make
VOC escape worse even while it improves particulate capture. A room-level filter sidesteps that
problem entirely, at some cost to peak PM performance right at the source.

This is two single runs per condition, not replicates — worth treating the ~2x VOC gap (EXP1 vs
EXP2) and the near-total VOC suppression (EXP3) as strong first observations, not final claims,
until EXP4–EXP6 either reproduce or complicate the pattern.

## Data provenance note

Two things worth knowing if you're digging into the underlying database:

- A print-session-tracking bug (fixed in [`print_tracker.py`](../../src/airmonitor/print_tracker.py))
  briefly fragmented each of these prints into extra short "phantom" rows around the real start of
  the print, caused by a transient printer state reported during bed-leveling/calibration. The
  affected sample rows were reattached to the correct real print before this analysis; the fix
  prevents it from recurring for EXP4 onward.
- A short IPA cleaning-alcohol spike on the sensor between runs was independently confirmed via its
  decay curve and alert history, unrelated to any print, and does not appear in these charts' time
  windows.
