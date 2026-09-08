"""ELN schemas for elabFTW ↔ NOMAD bidirectional linking."""

from nomad.metainfo.metainfo import SchemaPackage

m_package = SchemaPackage(
    aliases=[
        "three_way_sync.schema:ElabftwLinkedEntry",
        "three_way_sync.schema:ElabftwMachineUpload",
        "three_way_sync.schema:ElabftwSettings",
    ]
)

from nomad.datamodel.data import EntryData, ElnIntegrationCategory
from nomad.datamodel.metainfo.annotations import ELNAnnotation
from nomad.metainfo import Datetime, Quantity, Section, SubSection, MSection
from three_way_sync.normalizer import ElabftwBridge


class ElabftwExpRef(MSection):
    """Reference to a single elabFTW experiment/item."""
    elabftw_id = Quantity(type=str, description="elabFTW entity ID", a_eln=ELNAnnotation(component="StringEditQuantity"))
    elabftw_url = Quantity(type=str, description="Full URL", a_eln=ELNAnnotation(component="URLEditQuantity"))
    elabftw_title = Quantity(type=str, description="Title (auto-fetched)")
    sync_status = Quantity(type=str, description="pending/synced/error")
    last_synced = Quantity(type=Datetime, description="Last sync timestamp")


class ElabftwSyncConfig(MSection):
    """Configuration for elabFTW sync."""
    entity_type = Quantity(
        type=str, default="experiment",
        description="experiment (default) or item (database resource)",
        a_eln=ELNAnnotation(component="StringEditQuantity"),
    )
    api_base_url = Quantity(type=str, description="elabFTW API URL", a_eln=ELNAnnotation(component="StringEditQuantity"))
    api_key = Quantity(type=str, description="API key (cleared after sync)", a_eln=ELNAnnotation(component="StringEditQuantity", props=dict(type="password")))
    sync_now = Quantity(type=bool, default=False, description="Toggle to sync now", a_eln=ELNAnnotation(component="BoolEditQuantity"))
    create_elabftw_experiment = Quantity(type=bool, default=False, description="Create elabFTW entity from this entry", a_eln=ELNAnnotation(component="BoolEditQuantity"))
    write_link_back = Quantity(type=bool, default=True, description="Write NOMAD URL back", a_eln=ELNAnnotation(component="BoolEditQuantity"))


class ElabftwLinkedEntry(EntryData):
    """ELN entry that auto-links to elabFTW.

    Fill in config → save → normalizer links bidirectionally.
    API key is read from your ElabftwSettings entry if available.
    """
    m_def = Section(label="elabFTW Linked Entry", categories=[ElnIntegrationCategory], a_eln=ELNAnnotation(overview=True))
    title = Quantity(type=str, description="Entry title", a_eln=ELNAnnotation(component="StringEditQuantity", overview=True))
    description = Quantity(type=str, description="Description", a_eln=ELNAnnotation(component="RichTextEditQuantity", overview=True))
    config = SubSection(sub_section=ElabftwSyncConfig)
    experiments = SubSection(sub_section=ElabftwExpRef, repeats=True)

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        bridge = ElabftwBridge(archive, logger)
        if not bridge.api_base or not bridge.api_key:
            return
        metadata = archive.metadata
        entry_id = metadata.entry_id if metadata else None
        upload_id = metadata.upload_id if metadata else None
        nomad_url = (
            f"https://researchmcp.duckdns.org/nomad-oasis/gui/user/uploads/entry/{upload_id}/{entry_id}"
            if upload_id and entry_id else None
        )
        entity_type = self.config.entity_type if self.config else "experiment"

        if self.config and self.config.sync_now:
            for exp_ref in self.experiments:
                if not exp_ref.elabftw_id:
                    continue
                entity = bridge.fetch_entity(exp_ref.elabftw_id, entity_type)
                if entity:
                    exp_ref.elabftw_title = entity.get("title", entity.get("name", ""))
                    exp_ref.sync_status = "synced"
                    from datetime import datetime, timezone
                    exp_ref.last_synced = datetime.now(timezone.utc)
                    if self.config.write_link_back and nomad_url:
                        bridge.add_nomad_link_to_elabftw(exp_ref.elabftw_id, nomad_url, entity_type)
                else:
                    exp_ref.sync_status = "error"
            self.config.sync_now = False

        if self.config and self.config.create_elabftw_experiment:
            title = (metadata.entry_name if metadata else None) or self.title or "NOMAD Entry"
            eid = bridge.create_entity(title=title, entity_type=entity_type)
            if eid:
                if metadata:
                    metadata.external_id = eid
                ref = ElabftwExpRef(elabftw_id=eid, elabftw_title=title, sync_status="created")
                self.experiments.append(ref)
                if self.config.write_link_back and nomad_url:
                    bridge.add_nomad_link_to_elabftw(eid, nomad_url, entity_type)
            self.config.create_elabftw_experiment = False

        # Clear entry-level API key if user has settings
        if self.config and self.config.api_key:
            if bridge._from_settings('api_key'):
                self.config.api_key = None


class ElabftwMachineUpload(ElabftwLinkedEntry):
    """For automated machine uploads."""
    pass


class ElabftwSettings(EntryData):
    """Personal elabFTW connection settings.

    Create ONE entry with this schema, fill in your API key once.
    Name it 'elabFTW Settings' so the normalizer finds it.
    Only you can see your own settings.
    """
    m_def = Section(label="elabFTW Settings", categories=[ElnIntegrationCategory], a_eln=ELNAnnotation(overview=True))
    title = Quantity(type=str, default="elabFTW Settings", description="Must be 'elabFTW Settings'", a_eln=ELNAnnotation(component="StringEditQuantity", overview=True))
    api_base_url = Quantity(type=str, default="https://elntest.ub.tum.de/api/v2", description="elabFTW API base URL", a_eln=ELNAnnotation(component="StringEditQuantity"))
    api_key = Quantity(type=str, description="Your personal elabFTW API token", a_eln=ELNAnnotation(component="StringEditQuantity", props=dict(type="password")))


m_package.init_metainfo()
