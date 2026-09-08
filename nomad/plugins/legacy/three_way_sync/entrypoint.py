"""Entry point for NOMAD plugin registration."""
from nomad.config.models.plugins import SchemaPackageEntryPoint


class BridgeEntryPoint(SchemaPackageEntryPoint):
    def load(self):
        from three_way_sync.schema import m_package
        return m_package


bridge_schema = BridgeEntryPoint(
    name="elabftw-bridge",
    description="Bidirectional elabFTW NOMAD linking",
)
