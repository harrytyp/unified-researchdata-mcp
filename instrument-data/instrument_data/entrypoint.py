"""Entry point for NOMAD plugin registration."""
from nomad.config.models.plugins import SchemaPackageEntryPoint


class InstrumentDataEntryPoint(SchemaPackageEntryPoint):
    def load(self):
        from instrument_data.schema import m_package
        return m_package


instrument_schema = InstrumentDataEntryPoint(
    name="instrument-data",
    description="Instrument measurement schemas (TGA, DMA, FTIR, MS)",
)
