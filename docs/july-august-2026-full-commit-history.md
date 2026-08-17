# July-August 2026 commit log — TGA / NOMAD / eLabFTW pipeline

Everything that went into this pipeline, in order, from the first week (20
July) through the most recent commit (`f97d085`, 13 Aug). Written down so
whoever picks this up next doesn't have to reconstruct the reasoning from
commit messages alone — some of these decisions only make sense if you know
what got tried right before them.

`git show <hash>` if you want the full diff. What's below is the parts that
actually mattered plus the "why," not a mechanical transcript.

Scope is `nomad/plugins/` (schema, processor, tprc_builder, tri_format,
entrypoint, startup.sh), the operator app (`tga/src/tga_nomad_app.pyw`), and
`docs/`. Left out the unrelated monorepo stuff (econversion, elab-app,
datatagger) — not our territory.

---

## July

**`9eb6eb4`** — one-line signature fix in
`tga/plugins/instrument-data/instrument_data/entrypoint.py`,
`TgaParser.is_mainfile()`. NOMAD 1.4.2 calls this with 5 args
(`filename, mime, buffer, decoded_buffer, compression`); ours only took
`(filename, logger)`. Every single upload was crashing with
`takes 3 positional arguments but 6 were given` until this landed.

**`9b2a3ae`** — first real schema work, still in the old
`tga/plugins/instrument-data/` location. `TemperatureSegment(MSection)`
shows up for the first time here — `segment_type` was a plain string back
then, no `MEnum`:

```python
class TemperatureSegment(MSection):
    segment_type = Quantity(type=str, description="ramp | isothermal")
    end_temp = Quantity(type=float, unit="°C")
    rate = Quantity(type=float, unit="°C/minute")
    duration_min = Quantity(type=float, unit="minute")
```

`TgaMeasurement` picked up `PlotSection` as a base class and `normalize()`
got its first plot, built from the real measurement signal:

```python
if self.temperature_signal and self.weight_signal and \
        len(self.temperature_signal) == len(self.weight_signal):
    fig = px.scatter(x=self.temperature_signal, y=self.weight_signal, ...)
    self.figures.append(PlotlyFigure(label='TGA curve', figure=fig.to_plotly_json()))
```

Small thing that bit us later if I hadn't caught it here: `self.figures = []`
had to move out of the `if process_now:` block to the top of `normalize()`,
otherwise figures just kept piling up on every save that didn't trigger
processing.

**`a08cf18`** — `.gitignore` +6 lines, NOMAD secret patterns.
Housekeeping, but it's the first commit in a whole thread of secret cleanup
that runs through early August.

**`21ab7de`** — moved my schema from the dead
`tga/plugins/instrument-data/` path to `nomad/plugins/instrument_data/`,
which is what the server actually bind-mounts. Deleted the old directory
outright — 703-line `elabftw_client.py` and all. Everything before this
commit had basically been happening in a folder nobody read.

**`0cb4f51`** — swapped the old YAML plugin config for
`pip install -e` plus a config volume mount. `nomad/configs/nomad.yaml`
−3, `startup.sh` +3.

**`b14aa10`** — first attempt at getting NOMAD to actually see the
plugin: hand-wrote an `.egg-info` folder with entry points
`instrument-schema` and `tga_parser`. Missed that it should've been
`tga-parser` with a hyphen — small thing, came back to bite later.

**`4303b3e`** — moved the whole NOMAD stack into the monorepo.
`docker-compose.yaml` got rewritten almost top to bottom (241 in / 321
out of 562 lines). Every path-related commit for the next two weeks traces
back to this one.

**`e5e9c9d`** — one-liner, `patch-nomad-distro.py` now points at
the monorepo `nomad/` path. Direct fallout from `4303b3e`.

**`eca2d8b`** — found a `.nomad_pat` file that was still tracked
in git despite the gitignore rule. Removed it, fixed the pattern.

**`3c2d9a6`** — `NOMAD_PAT` moved from a file mount to `.env` via
`env_file`. One secret, one place.

**`61c4602`** — merge, nothing in it.

---

## August

**`38b62f2`** — ripped `pip install` out of `startup.sh` (19 lines
gone). No internet in the container, so it was never going to work
reliably — `.pth` + `sys.path` is enough.

**`2e3ee87`** — hardcoded `ELABFTW_API_KEY` out of `startup.sh`,
now reads from `.env`.

**`5d5b660`** — deleted tracked `.bak` files (one had a key in it),
ignored the pattern going forward.

**`bffaa7f`** — two things in one commit. First, moved the `.tri`
parser package (`tri_format/`) out of that same dead directory `21ab7de`
had already emptied out once — it kept coming back because someone (me,
probably) kept working in the old copy without noticing. Second, fixed
`entrypoint.py` so `.tri` files actually route to the right parser:

```python
# before: everything went through the text parser
data = parse_file(mainfile)
if data:
    archive.data = TgaMeasurement(**data)

# after: .tri gets its own binary path
if str(mainfile).endswith(".tri"):
    fields = extract_key_fields(mainfile)
    archive.data = TgaMeasurement(
        sample=InstrumentSample(sample_name=fields.get("sample_name"), ...),
        instrument_name=fields.get("instrument_name"),
        crucible_type=fields.get("crucible_type"),
        ...
    )
    return
data = parse_file(mainfile)
```

Before the fix a `.tri` upload didn't even error out — it fed binary data
through a text parser and quietly produced 500-something garbage metadata
keys plus `NaN` everywhere in the signal columns. No crash, just wrong.
Worth remembering if you ever see an entry with a suspiciously huge
metadata list.

**`510680f`** — made the plugin registration from `b14aa10` survive
a container restart: `startup.sh` now re-copies `instrument_data.egg-info`
into `site-packages` on every boot instead of relying on `pip install`.

**`8e2f00d`** — added `_generate_tprc_from_entry()` to
`processor.py`. Point of it: `source_upload_id` becomes optional. If it's
empty, instead of just logging a warning, `normalize_tga_entry()` calls the
new function, which pulls `heating_rate`/`temperature_end` off the first
segment and calls `build_tprc(params)` directly — you can now get a
`.tprc` out of NOMAD without ever uploading a measurement file. Also added
`generated_tprc`/`tprc_filename` to the schema to hold the result.

**`9e404f2`** — `generated_tprc` stopped being just a base64 blob
sitting in a text field. Added:

```python
upload_files = archive.m_context.upload_files
if upload_files is not None and hasattr(upload_files, "add_rawfiles") and not upload_files.is_frozen:
    ...
    upload_files.add_rawfiles(tmp_path, target_dir="")
```

so it shows up as a real, downloadable file under "Upload Files" too.

**`65291b8`** — turns out subsections in NOMAD need a bare
`a_eln=ELNAnnotation()` with no `component=` to render in the form at all.
`TemperatureSegment` didn't have one — added it, same for
`temperature_segments` itself. Before this the segment list just didn't
show up, full stop.

**`7338638`** — `procedure_segments` stopped being something the
user types by hand and became a derived field — built from the segment
list instead (`"10 K/min to 400 C; Isothermal for 30 min"`, that kind of
string). Added a separate `comments` field for anything the user actually
wants to write themselves.

**`dac792c`** — two fixes together. `_to_float()` added because
segment values coming through were sometimes pint `Quantity` objects (unit
attached) and `float()` on those throws `DimensionalityError`:

```python
def _to_float(value):
    if hasattr(value, "magnitude"):
        return float(value.magnitude)
    return float(value)
```

And `segment_type`/`crucible_type` became real `MEnum` dropdowns instead of
free text — first time either field had an actual constraint.

**`77f6feb`** — `_to_float` just dropped units, which isn't enough
when the `.tprc` format expects a specific unit (degrees C, minutes,
whatever). `_to_unit(value, target)` does the real conversion via pint,
falls back to raw magnitude if the conversion itself fails.

**`dae144b`** — `upload_limit: 100` in `nomad.yaml`. One line.

**`eb1404e`** — the multi-segment rewrite. `build_tprc` went from
taking fixed params to taking a segment list:

```python
def build_tprc(params, segments, template_path=None, logger=None):
```

with `_validate_segments()` checking each one's required fields before any
byte gets touched, and `ramp_count`/`iso_count` as separate counters so
segments land in the right `SGMT` block regardless of what order Ramp and
Isothermal steps come in. At this point Isothermal was still keyed to type
byte `0x05` and required `end_temp` — both wrong, I just didn't know it
yet.

**`9ae3c31`** — `docs/server-update-guide.md`, 171 lines. Restart
order, seven recurring errors. Read this before you touch the server.

**`5113e57`** — spent an afternoon diffing three real `.tprc` files
that only differed by one segment's duration. Isothermal's type byte is
`0x04`, not `0x05`. And `duration_min` is little-endian at `+12` — the one
field in the whole format that isn't big-endian:

```python
def _patch_le_f32(data, offset, value):
    packed = struct.pack('<f', float(value))
    for i in range(4):
        if offset + i < len(data):
            data[offset + i] = packed[i]
```

Also fixed validation to require `duration_min` instead of `end_temp` for
Isothermal — makes sense once you think about it, isothermal just means
"stay at whatever temperature you were already at."

**`fd1782d`** — added `overview=True` to `InstrumentSample` and
`TemperatureSegment` hoping that would make them show up on the Overview
tab. It didn't, not by itself — see the next commit.

**`f9ee327`** — turns out a brand-new entry's raw JSON doesn't have
`sample` or `temperature_segments` in it at all, not even empty ones, so
`overview=True` had nothing to point at. Fix was two lines at the top of
`normalize()`:

```python
if self.sample is None:
    self.sample = InstrumentSample()
if not self.temperature_segments:
    self.temperature_segments.append(TemperatureSegment())
```

Obvious in hindsight. Took a wasted commit to get there.

**`3be3494`** — added a preview plot that draws the planned heating
profile straight from the segments, before any real measurement exists.
Ramp contributes a sloped line, `duration = |target - current| / rate`;
Isothermal contributes a flat segment for `duration_min`. Assumes 25 °C
start since there's no starting-temperature field. Draws nothing if there
aren't at least two points.

**`a8b687d`** — the one that actually stung. Same class of bug as
`5113e57`, but nobody had checked whether it also applied to Ramp:

```python
# what eb1404e shipped, four days earlier:
_patch_be_f32(data, idx + 8, float(seg['end_temp']))
_patch_be_f32(data, idx + 12, float(seg['rate']))

# what it should have been all along:
_patch_le_f32(data, idx + 12, float(seg['end_temp']))
_patch_le_f32(data, idx + 16, float(seg['rate']))
```

Found it the same way as Isothermal — isolated test files, plus a real
template whose filename literally spelled out its own parameters
(`1Cmin_1000C`), which is a nice sanity check when you have it. Every Ramp
`.tprc` generated between `eb1404e` and this commit has the wrong target
temperature and rate baked into it. No error, just wrong numbers. If
anyone finds one of those files lying around, don't trust it.

**`3cecc1a`** — new file, `tga_nomad_app.pyw`, 660 lines. This is
where the operator-side GUI starts — a NOMAD-native replacement for the old
elabFTW agent. Separate track from the schema work, ran in parallel from
here on.

**`675b6ae`** — EXE rename, `TGA_elabFTW_Agent.exe` →
`TGA_NOMAD_Agent.exe`. Binary rebuild, nothing to read.

**`4929527`** — `_download_tprc` and `_selected_upload_id` got
dropped somewhere in the `3cecc1a` rewrite. `AttributeError` on startup
until this restored them.

**`dd645fe`** — rebuild.

**`2f40388`** — same story, `_render_rows` was missing this time,
refresh was crashing. Fixed.

**`d55e876`** — rebuild.

**`dda7bd1`** — before committing to a real rewrite, I wanted to know
if NOMAD's ELN GUI could even do what I had in mind: pick a concrete
subtype when adding to a repeating list, and only show that subtype's own
fields. Built a throwaway test entry (`TestTypeA`/`TestTypeB`, common base
`TestStepBase`) to check, without touching `TgaMeasurement` at all. Worked.
Also widened the `MEnum` for `segment_type`/`crucible_type` in this same
commit as a stopgap case-sensitivity fix — turned out to be unnecessary an
hour later, see below.

**`d72029f`** — the actual rewrite. `TemperatureSegment` with its
string `segment_type` is gone, replaced by a common base and four real
subtypes:

```python
class TemperatureSegmentBase(MSection):
    m_def = Section(a_eln=ELNAnnotation(overview=True))

class RampSegment(TemperatureSegmentBase):
    end_temp = Quantity(type=float, unit="°C", ...)
    rate = Quantity(type=float, unit="°C/minute", ...)

class IsothermalSegment(TemperatureSegmentBase):
    duration_min = Quantity(type=float, unit="minute", ...)

class MassFlowSegment(TemperatureSegmentBase):
    flow_rate = Quantity(type=float, unit="mL/minute", ...)

class BalanceFlowSegment(TemperatureSegmentBase):
    flow_rate = Quantity(type=float, unit="mL/minute", ...)
```

`processor.py` now checks `isinstance(seg, RampSegment)` instead of
comparing strings. And the `dda7bd1` case-sensitivity widening I did an
hour before this? Gone — there's no string field left to mistype, so it
just wasn't needed anymore. Also added the two segment types TRIOS
actually has that we'd never bothered with: Mass Flow (`0x0E`) and Balance
Flow (`0x13`), same `+12` little-endian pattern as everything else.

**`64454d4`** — the new segment list showed `"0"`, `"1"`, `"2"` in the
UI instead of anything useful. `label_quantity` fixes that:

```python
m_def = Section(a_eln=ELNAnnotation(properties=dict(label_quantity='end_temp')))
```

one per subtype, pointing at whichever field is that type's "headline"
value. Got the annotation key wrong here though — see `4741bd4`.

**`f43dd2e`** — sample status tracking in the operator app:
pending/received/measured, double-click to cycle, right-click for a
context menu, saved to a local JSON file. This is GUI-only state, doesn't
touch NOMAD.

**`a6f3f7a`** — rebuild.

**`f292791`** — the big UI pass. Dark mode, four selectable tab
styles, checkbox multi-select, new columns (entry type, procedure, author),
slot assignment at the filename stage. 1248 lines in, 834 out — basically a
rewrite of the file.

**`864b21b`** — rebuild.

**`4e24122`** — `docs/admin-pat-setup.md`. Worth actually reading
if you touch cross-user access: the upload **list** endpoint in NOMAD
ignores admin status entirely, only the single-upload endpoint honors it.
So an admin PAT can fetch any upload by ID but sees an empty list — the
workaround is a `tga-operators` user group attached to every upload via
`coauthor_groups`, created by hand in MongoDB. One detail that'll waste
your afternoon if you miss it: the group's `_id` has to be a plain string,
not an `ObjectId`, or NOMAD's API response validation breaks.

**`bf0914d`** — three validation tightenings after living with
`d72029f` for a few hours. A segment added but never given a type now gets
flagged instead of silently ignored. The auto-added placeholder segment
from `f9ee327` got removed again — an empty list already renders fine on
Overview, and there's no honest "default" segment type to guess at, so
guessing was worse than leaving it empty. And negative rate/duration/flow
values are rejected outright now, for any segment type — this format
always stores these as positive magnitudes, so a negative number can only
be a mistake.

**`4741bd4`** — the `label_quantity` key from `64454d4` was wrong,
should have been `more=dict(...)` not `properties=dict(...)`:

```python
m_def = Section(a_eln=ELNAnnotation(more=dict(label_quantity='end_temp')))
```

fixed on all four segment classes. Also added `_add_operator_group()`,
which shares an upload with `tga-operators` automatically right after
`.tprc` generation, over the REST API — same reasoning as `4e24122`, the
list endpoint needs coauthor_group membership, admin isn't enough. And in
the operator app, the upload name now falls back to sample/procedure name
instead of `Upload {id[:8]}`, since `upload_name` is basically never set on
ELN-created uploads.

**`b49347c`** — new `procedure_status` field on `TgaMeasurement`, set
at every exit point of `_generate_tprc_from_entry` — missing segment,
validation failure, unexpected error, or success. Point of it: you can see
whether the last `.tprc` attempt actually worked from the Overview page,
without digging into the processing log. Messages were in Turkish in this
commit.

**`f97d085`** — translated those four messages to English, to match
the rest of the schema.

---

Where things actually stand right now: segment types are polymorphic, all
four have verified byte offsets, Overview shows sample/segments/status, and
uploads share themselves with the operators group automatically. What's
still open — `.tri` signal data, `tri_format/` not being the live parser —
is in `handoff-notes.md`.
