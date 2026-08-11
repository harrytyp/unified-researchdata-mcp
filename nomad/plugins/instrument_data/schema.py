"""NOMAD schemas for instrument measurements (TGA, DMA, FTIR, MS).

Each measurement type is a full EntryData schema with:
- Sample metadata (name, mass, geometry, etc.)
- Measurement parameters (temperature range, heating rate, gas, etc.)
- Parsed signal data (curves as JSON arrays)
- Computed results (Tg, mass loss steps, onset, residue, etc.)
- Reference back to the source elabFTW experiment
"""
from nomad.metainfo.metainfo import SchemaPackage

m_package = SchemaPackage(
    aliases=[
        "instrument_data.schema:TgaMeasurement",
        "instrument_data.schema:DmaMeasurement",
        "instrument_data.schema:FtrMeasurement",
        "instrument_data.schema:MsMeasurement",
        "instrument_data.schema:MockInstrumentRun",
        "instrument_data.schema:PipelineConfigEntry",
        "instrument_data.schema:PolymorphismTest",
    ]
)

from nomad.datamodel.data import EntryData, ElnIntegrationCategory
from nomad.datamodel.metainfo.annotations import ELNAnnotation
from nomad.metainfo import JSON, Datetime, MEnum, Quantity, Section, SubSection, MSection
from nomad.datamodel.metainfo.plot import PlotSection, PlotlyFigure
import plotly.express as px


# ── Shared sub-sections ──────────────────────────────────────────────────────

class ElabftwRef(MSection):
    """Reference to the source elabFTW experiment."""
    experiment_id = Quantity(
        type=str,
        description="elabFTW experiment ID",
        a_eln=ELNAnnotation(component="StringEditQuantity"))
    elabftw_url = Quantity(
        type=str,
        description="Full URL to elabFTW experiment",
        a_eln=ELNAnnotation(component="URLEditQuantity"))
    experiment_title = Quantity(
        type=str,
        description="Title of the elabFTW experiment")
    sync_status = Quantity(
        type=str,
        description="pending | synced | error")
    last_synced = Quantity(
        type=Datetime,
        description="When results were pushed back")


class InstrumentSample(MSection):
    """Physical sample information."""
    m_def = Section(a_eln=ELNAnnotation(overview=True))
    sample_name = Quantity(
        type=str,
        description="Sample identifier / name",
        a_eln=ELNAnnotation(component="StringEditQuantity"))
    sample_mass = Quantity(
        type=float,
        unit="mg",
        description="Sample mass in mg",
        a_eln=ELNAnnotation(component="NumberEditQuantity"))
    sample_mass_unit = Quantity(
        type=str,
        default="mg",
        description="Unit for sample mass")
    operator = Quantity(
        type=str,
        description="Name of the person who ran the measurement",
        a_eln=ELNAnnotation(component="StringEditQuantity"))
    run_date = Quantity(
        type=Datetime,
        description="Date and time of the measurement run")


class TemperatureRamp(MSection):
    """A single temperature segment in the method profile."""
    segment_type = Quantity(
        type=str,
        description="Ramp | Isothermal | Jump")
    rate = Quantity(type=float, description="Heating/cooling rate")
    target_temperature = Quantity(type=float, description="Target temp")
    duration = Quantity(type=float, unit="min", description="Hold time if isothermal")


class TemperatureSegmentBase(MSection):
    """Common base for every procedure segment type. A repeating list of
    these (mixing types freely, in order) makes up the full procedure -
    temperature ramps, isothermal holds, and gas flow steps - matching how
    TRIOS lets a user build up a sequence of Ramp/Isothermal/Mass Flow/
    Balance Flow steps. Which concrete type a given list item is (and
    therefore which fields it has) is chosen per-item in the ELN GUI, not
    via a separate "segment_type" field - see RampSegment, IsothermalSegment,
    MassFlowSegment, BalanceFlowSegment below."""
    m_def = Section(a_eln=ELNAnnotation(overview=True))


class RampSegment(TemperatureSegmentBase):
    """Heat or cool at a fixed rate to a target temperature."""
    # label_quantity: show this field's value (e.g. "450.0") as the list
    # label for this segment instead of a bare index ("0", "1", ...).
    m_def = Section(a_eln=ELNAnnotation(properties=dict(label_quantity='end_temp')))
    end_temp = Quantity(
        type=float, unit="°C",
        description="Target temperature",
        a_eln=ELNAnnotation(component="NumberEditQuantity"))
    rate = Quantity(
        type=float, unit="°C/minute",
        description="Heating/cooling rate",
        a_eln=ELNAnnotation(component="NumberEditQuantity"))


class IsothermalSegment(TemperatureSegmentBase):
    """Hold at whatever temperature the previous segment ended at, for a
    fixed duration."""
    m_def = Section(a_eln=ELNAnnotation(properties=dict(label_quantity='duration_min')))
    duration_min = Quantity(
        type=float, unit="minute",
        description="Hold duration",
        a_eln=ELNAnnotation(component="NumberEditQuantity"))


class MassFlowSegment(TemperatureSegmentBase):
    """Set the sample purge gas flow rate."""
    m_def = Section(a_eln=ELNAnnotation(properties=dict(label_quantity='flow_rate')))
    flow_rate = Quantity(
        type=float, unit="mL/minute",
        description="Sample purge gas flow rate",
        a_eln=ELNAnnotation(component="NumberEditQuantity"))


class BalanceFlowSegment(TemperatureSegmentBase):
    """Set the balance purge gas flow rate."""
    m_def = Section(a_eln=ELNAnnotation(properties=dict(label_quantity='flow_rate')))
    flow_rate = Quantity(
        type=float, unit="mL/minute",
        description="Balance purge gas flow rate",
        a_eln=ELNAnnotation(component="NumberEditQuantity"))


# ── TGA ──────────────────────────────────────────────────────────────────────

class TgaStep(MSection):
    """A detected mass loss step from TGA."""
    onset_temperature = Quantity(type=float)
    offset_temperature = Quantity(type=float)
    mass_loss_pct = Quantity(type=float, unit="%")
    peak_dtg_temperature = Quantity(type=float)
    assignment = Quantity(type=str, description="e.g. moisture, degradation, carbonization")


class TgaResults(MSection):
    """Computed results from TGA measurement."""
    tg_glass_transition = Quantity(
        type=float,
        description="Glass transition temperature from DTA inflection")
    residue_mass_pct = Quantity(
        type=float, unit="%",
        description="Residue mass at end of run as percentage")
    residue_mass_mg = Quantity(
        type=float, unit="mg",
        description="Residue mass at end of run in mg")
    onset_temperature = Quantity(
        type=float,
        description="Onset temperature of primary degradation")
    mass_loss_5pct = Quantity(
        type=float,
        description="Temperature at 5% mass loss (Td5)")
    mass_loss_10pct = Quantity(
        type=float,
        description="Temperature at 10% mass loss (Td10)")
    mass_loss_50pct = Quantity(
        type=float,
        description="Temperature at 50% mass loss (Td50)")
    steps = SubSection(
        sub_section=TgaStep, repeats=True,
        description="Individual mass loss steps")


def _build_procedure_preview_figure(segments):
    """Build a temperature-vs-time preview plot from the procedure segments,
    so the user can see the planned heating profile before any real
    measurement has been run.

    Ramp segments contribute a sloped line (duration = |end_temp - current| /
    rate); Isothermal segments contribute a flat line for duration_min.
    Mass Flow / Balance Flow segments don't affect temperature, so they're
    skipped here (they still get written to the .tprc file, just not shown
    on this particular plot). Starts from an assumed room-temperature
    ambient (25 degC) since the schema has no explicit starting-temperature
    field.
    """
    from instrument_data.processor import _to_unit

    times = [0.0]
    temps = [25.0]
    for seg in segments:
        t_now, temp_now = times[-1], temps[-1]
        if isinstance(seg, RampSegment):
            end_temp = _to_unit(getattr(seg, "end_temp", None), "degree_Celsius")
            rate = _to_unit(getattr(seg, "rate", None), "delta_degree_Celsius / minute")
            if end_temp is None or not rate:
                continue
            duration = abs(end_temp - temp_now) / abs(rate)
            times.append(t_now + duration)
            temps.append(end_temp)
        elif isinstance(seg, IsothermalSegment):
            duration = _to_unit(getattr(seg, "duration_min", None), "minute")
            if duration is None:
                continue
            times.append(t_now + duration)
            temps.append(temp_now)

    if len(times) < 2:
        return None

    fig = px.line(
        x=times, y=temps,
        labels={'x': 'Time (min)', 'y': 'Temperature (°C)'},
        title='Planned Temperature Profile',
    )
    return PlotlyFigure(label='Procedure preview', figure=fig.to_plotly_json())


class TgaMeasurement(PlotSection, EntryData):
    """TGA measurement with parsed signal data and computed results.

    Create this entry by importing a TRIOS-exported CSV/TXT file,
    or fill in the fields manually.
    """
    m_def = Section(
        label="TGA Measurement",
        categories=[ElnIntegrationCategory],
        a_eln=ELNAnnotation(overview=True))
    # ── Sample info ──
    sample = SubSection(sub_section=InstrumentSample)
    crucible_type = Quantity(
        # Lowercase variants are accepted alongside the canonical Title Case
        # values because entries written by scripts/imports rather than the
        # ELN dropdown can arrive in a different case and must not fail parsing
        # with "X is not a value of this enumeration". crucible_type is only
        # ever stored/displayed, never string-compared for branching logic,
        # so accepting extra casings here changes no downstream behavior.
        type=MEnum(["Alumina", "Platinum", "Aluminum", "alumina", "platinum", "aluminum"]),
        description="Crucible material",
        a_eln=ELNAnnotation(component="EnumEditQuantity"))
    pan_number = Quantity(
        type=str, description="Pan / crucible identifier",
        a_eln=ELNAnnotation(component="StringEditQuantity"))

    # ── Method ──
    procedure_name = Quantity(
        type=str,
        description="Name of the method/procedure used",
        a_eln=ELNAnnotation(component="StringEditQuantity"))
    procedure_segments = Quantity(
        type=str,
        description="Full method description (heating profile); derived from temperature_segments when set")
    temperature_segments = SubSection(
        sub_section=TemperatureSegmentBase,
        repeats=True,
        description="Ordered list of procedure segments (Ramp/Isothermal/Mass "
                     "Flow/Balance Flow), entered by the user. When adding a "
                     "new item, the ELN form asks which specific type to "
                     "create and then shows only that type's own fields.",
        a_eln=ELNAnnotation())
    comments = Quantity(
        type=str,
        description="Free-text comments / notes (not rendered into the .tprc)",
        a_eln=ELNAnnotation(component="RichTextEditQuantity"))
    gas_atmosphere = Quantity(
        type=MEnum(["N2", "Air", "Ar", "Synthetic Air", "O2"]),
        description="Purge gas atmosphere",
        a_eln=ELNAnnotation(component="EnumEditQuantity"))
    gas_flow_rate = Quantity(
        type=float, unit="mL/min",
        description="Sample purge gas flow rate",
        a_eln=ELNAnnotation(component="NumberEditQuantity"))
    balance_flow_rate = Quantity(
        type=float, unit="mL/min",
        description="Balance purge gas flow rate",
        a_eln=ELNAnnotation(component="NumberEditQuantity"))

    # ── Raw instrument metadata ──
    instrument_name = Quantity(type=str, description="Instrument serial/name")
    instrument_type = Quantity(type=str, description="e.g. TGA5500, TGA550")
    trios_version = Quantity(type=str, description="TRIOS software version")
    original_filename = Quantity(type=str, description="Original .tri file path")
    source_file = Quantity(
        type=str,
        description="Path to the exported CSV/TXT file")

    # ── Signal data (parsed curves) ──
    time_signal = Quantity(
        type=JSON,
        description="Time array [min]")
    temperature_signal = Quantity(
        type=JSON,
        description="Temperature array [°C]")
    weight_signal = Quantity(
        type=JSON,
        description="Weight array [mg]")
    weight_pct_signal = Quantity(
        type=JSON,
        description="Weight array [%, normalized]")
    dta_signal = Quantity(
        type=JSON,
        description="DTA / Temperature Difference array [°C]")
    dtg_signal = Quantity(
        type=JSON,
        description="DTG (derivative weight) array [%/°C]")

    # ── Computed results ──
    results = SubSection(sub_section=TgaResults)

    # ── elabFTW link ──
    elabftw_ref = SubSection(sub_section=ElabftwRef)

    # ── Plot ──
    summary_plot = Quantity(
        type=str,
        description="Base64-encoded SVG summary plot")

    # ── Generated .tprc (from ELN parameters, no upload needed) ──
    generated_tprc = Quantity(
        type=str,
        description="Base64-encoded .tprc procedure file generated from the entered parameters",
        a_eln=ELNAnnotation(component="StringEditQuantity"))
    tprc_filename = Quantity(
        type=str,
        description="Filename of the generated .tprc file",
        a_eln=ELNAnnotation(component="StringEditQuantity"))

    # ── Normalizer trigger ──
    source_upload_id = Quantity(
        type=str,
        description="NOMAD upload ID containing the raw CSV/TXT file",
        a_eln=ELNAnnotation(component="StringEditQuantity"))
    process_now = Quantity(
        type=bool,
        default=False,
        description="Toggle to True and save to trigger CSV processing",
        a_eln=ELNAnnotation(component="ActionEditQuantity"),
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        self.figures = []

        # A SubSection only renders as an editable card on the Overview page
        # once it actually exists in the archive (even empty). New entries
        # have no `sample` and no `temperature_segments` yet, so the user
        # has no visible way to start filling them in from Overview - they
        # end up needing the raw Data tab instead. Creating them here, once,
        # makes the cards appear immediately for a brand-new entry.
        if self.sample is None:
            self.sample = InstrumentSample()
        if not self.temperature_segments:
            # RampSegment as the default placeholder type - it's the most
            # common first step in a real procedure. The user can delete it
            # and/or add a different type via the ELN's own type-selection
            # dropdown for this list.
            self.temperature_segments.append(RampSegment())

        if self.process_now:
            self.process_now = False
            from instrument_data.processor import normalize_tga_entry
            normalize_tga_entry(self, archive, logger)

        # Preview of the planned heating profile, built from the segments
        # themselves - available even before any real measurement exists.
        preview_fig = _build_procedure_preview_figure(self.temperature_segments)
        if preview_fig is not None:
            self.figures.append(preview_fig)

        if self.temperature_signal and self.weight_signal and \
                len(self.temperature_signal) == len(self.weight_signal):
            fig = px.scatter(
                x=self.temperature_signal,
                y=self.weight_signal,
                labels={'x': 'Temperature (°C)', 'y': 'Mass (mg)'},
                title='TGA — Mass vs Temperature',
            )
            self.figures.append(PlotlyFigure(label='TGA curve', figure=fig.to_plotly_json()))


# ── DMA ──────────────────────────────────────────────────────────────────────

class DmaResults(MSection):
    """Computed results from DMA measurement."""
    tg_storage_modulus = Quantity(
        type=float,
        description="Tg from storage modulus onset")
    tg_loss_modulus = Quantity(
        type=float,
        description="Tg from loss modulus peak")
    tg_tan_delta = Quantity(
        type=float,
        description="Tg from tan delta peak")
    storage_modulus_glass = Quantity(
        type=float, unit="MPa",
        description="Storage modulus in glassy region")
    storage_modulus_rubber = Quantity(
        type=float, unit="MPa",
        description="Storage modulus in rubbery region")


class DmaMeasurement(EntryData):
    """DMA measurement with parsed signal data and computed results."""
    m_def = Section(
        label="DMA Measurement",
        categories=[ElnIntegrationCategory],
        a_eln=ELNAnnotation(overview=True))
    sample = SubSection(sub_section=InstrumentSample)
    sample_geometry = Quantity(
        type=str,
        description="Sample dimensions (L x W x T in mm)",
        a_eln=ELNAnnotation(component="StringEditQuantity"))
    clamp_type = Quantity(
        type=str,
        description="Tension | Dual Cantilever | 3-Point Bending | Compression")

    procedure_name = Quantity(type=str, description="Method name")
    procedure_segments = Quantity(type=str, description="Full method description")
    temperature_start = Quantity(type=float)
    temperature_end = Quantity(type=float)
    heating_rate = Quantity(type=float)
    frequency = Quantity(type=float, unit="Hz")
    strain_pct = Quantity(type=float, unit="%")
    force_N = Quantity(type=float, unit="N")

    instrument_name = Quantity(type=str)
    instrument_type = Quantity(type=str)
    source_file = Quantity(type=str)

    time_signal = Quantity(type=JSON)
    temperature_signal = Quantity(type=JSON)
    storage_modulus_signal = Quantity(type=JSON)
    loss_modulus_signal = Quantity(type=JSON)
    tan_delta_signal = Quantity(type=JSON)

    results = SubSection(sub_section=DmaResults)
    elabftw_ref = SubSection(sub_section=ElabftwRef)
    summary_plot = Quantity(type=str)


# ── FTIR ──────────────────────────────────────────────────────────────────────

class FtrResults(MSection):
    """Computed results from FTIR measurement."""
    peak_positions = Quantity(
        type=JSON,
        description="List of [wavenumber, absorbance] for detected peaks")
    library_matches = Quantity(
        type=JSON,
        description="Library matching results if available")


class FtrMeasurement(EntryData):
    """FTIR measurement with parsed spectrum."""
    m_def = Section(
        label="FTIR Measurement",
        categories=[ElnIntegrationCategory],
        a_eln=ELNAnnotation(overview=True))
    sample = SubSection(sub_section=InstrumentSample)
    sample_state = Quantity(
        type=str,
        description="Solid | Liquid | Gas | Film | Powder")
    spectral_range_start = Quantity(type=float)
    spectral_range_end = Quantity(type=float)
    scans = Quantity(type=int, description="Number of co-added scans")
    resolution = Quantity(type=float)
    background_file = Quantity(type=str)

    instrument_name = Quantity(type=str)
    source_file = Quantity(type=str)

    wavenumber_signal = Quantity(type=JSON, description="Wavenumber array [cm⁻¹]")
    absorbance_signal = Quantity(type=JSON, description="Absorbance array")

    results = SubSection(sub_section=FtrResults)
    elabftw_ref = SubSection(sub_section=ElabftwRef)
    summary_plot = Quantity(type=str)


# ── MS ────────────────────────────────────────────────────────────────────────

class MsResults(MSection):
    """Computed results from mass spectrometry."""
    base_peak = Quantity(
        type=JSON,
        description="Base peak as [m/z, intensity]")
    total_ion_count = Quantity(
        type=float,
        description="Total ion count (TIC)")
    identified_peaks = Quantity(
        type=JSON,
        description="List of [m/z, intensity, possible assignment]")


class MsMeasurement(EntryData):
    """Mass spectrometry measurement with parsed spectrum."""
    m_def = Section(
        label="MS Measurement",
        categories=[ElnIntegrationCategory],
        a_eln=ELNAnnotation(overview=True))
    sample = SubSection(sub_section=InstrumentSample)
    ionization_method = Quantity(
        type=str,
        description="EI | CI | ESI | MALDI | APCI")
    mass_range_start = Quantity(type=float)
    mass_range_end = Quantity(type=float)
    scan_rate = Quantity(type=float)
    source_temperature = Quantity(type=float)
    solvent = Quantity(type=str)

    instrument_name = Quantity(type=str)
    source_file = Quantity(type=str)

    mz_signal = Quantity(type=JSON, description="Mass-to-charge array [m/z]")
    intensity_signal = Quantity(type=JSON, description="Intensity array")

    results = SubSection(sub_section=MsResults)
    elabftw_ref = SubSection(sub_section=ElabftwRef)
    summary_plot = Quantity(type=str)


# ── Mock Instrument Run (for demo / testing) ────────────────────────────────

class MockRunConfig(MSection):
    """Configuration for a mock instrument run."""
    sample_name = Quantity(
        type=str, default="Polymer-X",
        description="Sample identifier",
        a_eln=ELNAnnotation(component="StringEditQuantity"),
    )
    sample_mass_mg = Quantity(
        type=float, default=12.5, unit="mg",
        description="Sample mass",
        a_eln=ELNAnnotation(component="NumberEditQuantity"),
    )
    crucible_type = Quantity(
        type=str, default="Alumina",
        description="Alumina | Platinum | Aluminum",
        a_eln=ELNAnnotation(component="StringEditQuantity"),
    )
    temperature_start = Quantity(
        type=float, default=30.0, unit="°C",
        description="Starting temperature",
        a_eln=ELNAnnotation(component="NumberEditQuantity"),
    )
    temperature_end = Quantity(
        type=float, default=1000.0, unit="°C",
        description="End temperature",
        a_eln=ELNAnnotation(component="NumberEditQuantity"),
    )
    heating_rate = Quantity(
        type=float, default=10.0, unit="K/min",
        description="Heating rate",
        a_eln=ELNAnnotation(component="NumberEditQuantity"),
    )
    gas_atmosphere = Quantity(
        type=str, default="N2",
        description="N2 | Air | Ar | Synthetic Air | O2",
        a_eln=ELNAnnotation(component="StringEditQuantity"),
    )
    gas_flow_rate = Quantity(
        type=float, default=50.0, unit="mL/min",
        description="Purge gas flow rate",
        a_eln=ELNAnnotation(component="NumberEditQuantity"),
    )
    operator = Quantity(
        type=str, default="Demo",
        description="Operator name",
        a_eln=ELNAnnotation(component="StringEditQuantity"),
    )


class MockRunResults(MSection):
    """Results from a mock instrument run."""
    run_status = Quantity(
        type=str,
        description="pending | running | completed | error",
    )
    run_message = Quantity(
        type=str,
        description="Status message or error details",
    )
    generated_file = Quantity(
        type=str,
        description="Path to the generated CSV/TXT file",
    )
    signal_points = Quantity(
        type=int,
        description="Number of data points generated",
    )
    channels = Quantity(
        type=str,
        description="Comma-separated list of signal channels",
    )
    computed_tg = Quantity(
        type=float, unit="°C",
        description="Tg from analysis",
    )
    computed_residue = Quantity(
        type=float, unit="%",
        description="Residue mass percentage",
    )
    computed_onset = Quantity(
        type=float, unit="°C",
        description="Onset temperature",
    )
    computed_steps = Quantity(
        type=JSON,
        description="Mass loss steps detected",
    )
    elabftw_experiment_id = Quantity(
        type=str,
        description="elabFTW experiment ID that was updated",
    )


class MockInstrumentRun(EntryData):
    """Mock instrument run for demo and testing.

    Fill in the parameters below, then set Run to True and save.
    The normalizer generates realistic TGA signal data, parses it,
    computes results, and populates this entry. No instrument needed.
    """
    m_def = Section(
        label="Mock Instrument Run",
        categories=[ElnIntegrationCategory],
        a_eln=ELNAnnotation(overview=True),
    )
    title = Quantity(
        type=str,
        description="Name for this mock run",
        a_eln=ELNAnnotation(component="StringEditQuantity", overview=True),
    )
    config = SubSection(
        sub_section=MockRunConfig,
        description="Measurement parameters",
    )
    run_now = Quantity(
        type=bool, default=False,
        description="Set to True and save to trigger a mock instrument run",
        a_eln=ELNAnnotation(component="BoolEditQuantity"),
    )
    results = SubSection(
        sub_section=MockRunResults,
        description="Results from the mock run",
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        if not self.run_now:
            return
        if not self.config:
            logger.info("Mock run: no config set, skipping")
            return

        # Import here to avoid circular imports
        from instrument_data.mock_normalizer import run_mock_instrument
        run_mock_instrument(self, archive, logger)


# ── Ingestion Pipeline Config (run as service, configure from GUI) ──────────

class PipelineConfigEntry(EntryData):
    """Configure the instrument data ingestion pipeline.

    The ingestion pipeline runs as a background service on the server,
    watching a folder for new instrument exports. This entry lets you
    view its status and trigger manual processing.
    """
    m_def = Section(
        label="Ingestion Pipeline",
        categories=[ElnIntegrationCategory],
        a_eln=ELNAnnotation(overview=True),
    )
    title = Quantity(
        type=str, default="Instrument Ingestion Pipeline",
        description="Pipeline configuration name",
        a_eln=ELNAnnotation(component="StringEditQuantity", overview=True),
    )
    watch_directory = Quantity(
        type=str, default="/home/debian/instrument-exports/",
        description="Directory the pipeline watches for new CSV/TXT files",
        a_eln=ELNAnnotation(component="StringEditQuantity"),
    )
    pipeline_status = Quantity(
        type=str, default="unknown",
        description="running | stopped | error",
    )
    last_checked = Quantity(
        type=str,
        description="Last time the watch directory was scanned",
    )
    last_file_processed = Quantity(
        type=str,
        description="Name of the most recently processed file",
    )
    files_processed_total = Quantity(
        type=int, default=0,
        description="Total files processed since startup",
    )
    errors_total = Quantity(
        type=int, default=0,
        description="Total processing errors",
    )
    trigger_scan = Quantity(
        type=bool, default=False,
        description="Set to True and save to trigger an immediate scan",
        a_eln=ELNAnnotation(component="BoolEditQuantity"),
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        if self.trigger_scan:
            logger.info("Pipeline: manual scan triggered")
            self.trigger_scan = False
            # Scan will be handled by the background service


# ── Polymorphism proof-of-concept (temporary, safe to remove later) ────────
# Question we're testing: when a repeating SubSection is typed to a common
# base class, does NOMAD's ELN GUI let the user pick a specific subclass when
# adding a new item, and does the resulting form then only show that
# subclass's own fields? This does not touch TgaMeasurement or any existing
# entry type - it's a fully separate, disposable entry type.

class TestStepBase(MSection):
    """Common base class - has no fields of its own."""
    m_def = Section(a_eln=ELNAnnotation())


class TestTypeA(TestStepBase):
    """Subtype A - only exists here, not on TestTypeB."""
    m_def = Section(a_eln=ELNAnnotation())
    value_a = Quantity(
        type=float,
        description="Only exists on TestTypeA",
        a_eln=ELNAnnotation(component="NumberEditQuantity"))


class TestTypeB(TestStepBase):
    """Subtype B - only exists here, not on TestTypeA."""
    m_def = Section(a_eln=ELNAnnotation())
    value_b = Quantity(
        type=str,
        description="Only exists on TestTypeB",
        a_eln=ELNAnnotation(component="StringEditQuantity"))


class PolymorphismTest(EntryData):
    """Temporary proof-of-concept entry, not part of the real TGA workflow."""
    m_def = Section(
        label="Polymorphism Test",
        categories=[ElnIntegrationCategory],
        a_eln=ELNAnnotation(overview=True))
    steps = SubSection(sub_section=TestStepBase, repeats=True, a_eln=ELNAnnotation())


m_package.init_metainfo()
