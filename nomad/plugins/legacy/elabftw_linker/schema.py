"""elabFTW Dynamic Link Schema."""
from typing import Optional
from datetime import datetime, timezone
from nomad.datamodel.data import ArchiveSection, EntryData, ElnIntegrationCategory
from nomad.datamodel.metainfo.annotations import ELNAnnotation
from nomad.metainfo import JSON, Datetime, Quantity, Section, SubSection, MSection


class ElabftwExperimentRef(MSection):
    """A reference to an elabFTW experiment in a NOMAD entry."""
    elabftw_id = Quantity(type=str, description="elabFTW experiment ID", a_eln=ELNAnnotation(component="StringEditQuantity"))
    elabftw_url = Quantity(type=str, description="Full URL to elabFTW experiment", a_eln=ELNAnnotation(component="URLEditQuantity"))
    elabftw_title = Quantity(type=str, description="Title of the elabFTW experiment", a_eln=ELNAnnotation(component="StringEditQuantity"))
    sync_status = Quantity(type=str, description="sync status", a_eln=ELNAnnotation(component="StringEditQuantity"))
    last_synced = Quantity(type=Datetime, description="Last sync time")
    linked_nomad_entry_id = Quantity(type=str, shape=["*"], description="Linked NOMAD entry IDs")


class ElabftwDynamicLinkConfig(MSection):
    """elabFTW API connection config."""
    api_base_url = Quantity(type=str, description="elabFTW API base URL", a_eln=ELNAnnotation(component="StringEditQuantity"))
    api_key = Quantity(type=str, description="API key (cleared after sync)", a_eln=ELNAnnotation(component="StringEditQuantity", props=dict(type="password")))
    sync_all_references = Quantity(type=bool, default=False, description="Toggle to sync all refs", a_eln=ELNAnnotation(component="BoolEditQuantity"))
    auto_resolve_links = Quantity(type=bool, default=True, description="Auto-resolve cross-references", a_eln=ELNAnnotation(component="BoolEditQuantity"))


class ElabftwLinkedEntry(EntryData):
    """ELN entry that dynamically links to elabFTW experiments."""
    m_def = Section(label="elabFTW Dynamic Link", categories=[ElnIntegrationCategory], a_eln=ELNAnnotation(overview=True))
    title = Quantity(type=str, description="Title", a_eln=ELNAnnotation(component="StringEditQuantity", overview=True))
    description = Quantity(type=str, description="Description", a_eln=ELNAnnotation(component="RichTextEditQuantity", overview=True))
    config = SubSection(sub_section=ElabftwDynamicLinkConfig)
    experiments = SubSection(sub_section=ElabftwExperimentRef, repeats=True)

    def normalize(self, archive, logger):
        super().normalize(archive, logger)
        if self.config and self.config.sync_all_references:
            logger.info("elabFTW: syncing all references")
            self._sync_all(archive, logger)
            self.config.sync_all_references = False
        if self.config and self.config.auto_resolve_links:
            self._resolve_links(archive, logger)

    def _sync_all(self, archive, logger):
        if not self.config or not self.config.api_key:
            logger.warning("No API key configured")
            return
        for exp_ref in self.experiments:
            if not exp_ref.elabftw_id:
                continue
            try:
                self._sync_experiment(exp_ref, archive, logger)
            except Exception as e:
                logger.error("Sync failed for " + str(exp_ref.elabftw_id) + ": " + str(e))
                exp_ref.sync_status = "error"
        self.config.api_key = None

    def _sync_experiment(self, exp_ref, archive, logger):
        import requests
        api_base = self.config.api_base_url or (
            exp_ref.elabftw_url.rsplit("/experiments.php", 1)[0] + "/api/v2"
            if exp_ref.elabftw_url else None
        )
        if not api_base:
            logger.error("No API base URL")
            return
        headers = {"Authorization": str(self.config.api_key)}
        url = api_base + "/experiments/" + str(exp_ref.elabftw_id) + "?format=json&json=true"
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            exp_ref.elabftw_title = data.get("title", data.get("name", ""))
            exp_ref.sync_status = "synced"
            exp_ref.last_synced = datetime.now(timezone.utc)
            logger.info("Synced experiment " + str(exp_ref.elabftw_id) + ": " + str(exp_ref.elabftw_title))
        else:
            exp_ref.sync_status = "error"
            logger.error("API returned " + str(resp.status_code) + " for " + str(exp_ref.elabftw_id))

    def _resolve_links(self, archive, logger):
        try:
            from nomad.search import MetadataPagination, search
            for exp_ref in self.experiments:
                if not exp_ref.elabftw_id:
                    continue
                result = search(owner="all", query={"external_id": exp_ref.elabftw_id},
                                pagination=MetadataPagination(page_size=100),
                                user_id=archive.metadata.main_author.user_id if archive.metadata.main_author else None)
                linked = []
                if result.pagination.total > 0:
                    for entry in result.data:
                        eid = entry.get("entry_id")
                        uid = entry.get("upload_id")
                        if eid and eid != archive.metadata.entry_id:
                            linked.append("../uploads/" + str(uid) + "/archive/" + str(eid) + "#data")
                exp_ref.linked_nomad_entry_id = linked
                if linked:
                    logger.info("Found " + str(len(linked)) + " linked entries for " + str(exp_ref.elabftw_id))
        except Exception as e:
            logger.warning("Could not resolve links: " + str(e))


class ElabftwDynamicLink(ElabftwLinkedEntry):
    """Alias."""
    pass
