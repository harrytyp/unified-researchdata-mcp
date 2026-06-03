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
    ]
)

from nomad.datamodel.data import EntryData, ElnIntegrationCategory
from nomad.datamodel.metainfo.annotations import ELNAnnotation
from nomad.metainfo import JSON, Datetime, Quantity, Section, SubSection, MSection


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
        description="Name of the person who ran the measurement")
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


class TgaMeasurement(EntryData):
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
        type=str,
        description="Alumina | Platinum | Aluminum",
        a_eln=ELNAnnotation(component="StringEditQuantity"))
    pan_number = Quantity(type=str, description="Pan / crucible identifier")

    # ── Method ──
    procedure_name = Quantity(
        type=str,
        description="Name of the method/procedure used",
        a_eln=ELNAnnotation(component="StringEditQuantity"))
    procedure_segments = Quantity(
        type=str,
        description="Full method description (heating profile)",
        a_eln=ELNAnnotation(component="RichTextEditQuantity"))
    gas_atmosphere = Quantity(
        type=str,
        description="N2 | Air | Ar | Synthetic Air | O2")
    gas_flow_rate = Quantity(
        type=float, unit="mL/min",
        description="Sample purge gas flow rate")
    balance_flow_rate = Quantity(
        type=float, unit="mL/min",
        description="Balance purge gas flow rate")

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

    # ── Normalizer trigger ──
    source_upload_id = Quantity(
        type=str,
        description="NOMAD upload ID containing the raw CSV/TXT file",
        a_eln=ELNAnnotation(component="StringEditQuantity"))
    process_now = Quantity(
        type=bool,
        default=False,
        description="Toggle to True and save to trigger CSV processing",
        a_eln=ELNAnnotation(component="ButtonEditQuantity"),
    )

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        if not self.process_now:
            return
        self.process_now = False
        from instrument_data.processor import normalize_tga_entry
        normalize_tga_entry(self, archive, logger)


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


m_package.init_metainfo()
