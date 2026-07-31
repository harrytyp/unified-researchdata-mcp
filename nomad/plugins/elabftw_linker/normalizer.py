"""elabFTW dynamic link normalizer hook.

Runs during NOMAD normalization to resolve elabFTW cross-references.
"""
from typing import Optional
from nomad.datamodel import EntryArchive


def elabftw_link_normalizer(archive: EntryArchive, logger) -> Optional[bool]:
    """Normalizer hook that resolves elabFTW links across entries.

    Scans entries with the ElabftwLinkedEntry schema and ensures
    their elabFTW cross-references are up-to-date.

    Args:
        archive: The NOMAD entry archive being normalized.
        logger: Logger instance.

    Returns:
        True if any links were resolved, None otherwise.
    """
    try:
        from elabftw_linker.schema import ElabftwLinkedEntry

        data = archive.data
        if isinstance(data, ElabftwLinkedEntry):
            if data.config and data.config.auto_resolve_links:
                data._resolve_links(archive, logger)
                return True
    except Exception as e:
        logger.warning("elabFTW normalizer error: " + str(e))
    return None
