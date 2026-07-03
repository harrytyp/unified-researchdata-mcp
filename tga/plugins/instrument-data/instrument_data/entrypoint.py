"""
Entry point for NOMAD plugin registration.
"""
from nomad.config.models.plugins import SchemaPackageEntryPoint, ParserEntryPoint


class InstrumentDataEntryPoint(SchemaPackageEntryPoint):
    def load(self):
        from instrument_data.schema import m_package
        return m_package


instrument_schema = InstrumentDataEntryPoint(
    name="instrument-data",
    description="Instrument measurement schemas (TGA, DMA, FTIR, MS)",
)


class TgaParserEntryPoint(ParserEntryPoint):
    """Entry point for TGA parser plugin."""

    def load(self):
        from nomad.parsing import Parser

        class TgaParser(Parser):
            name = "tga_parser"
            code = "tga-parser"
            description = "Parse TGA/TRIOS instrument data"

            def parse(self, mainfile, archive, logger):
                from instrument_data.parser import parse_file
                logger.info("TGA parsing: " + str(mainfile))
                data = parse_file(mainfile)
                if data:
                    from instrument_data.schema import TgaMeasurement
                    archive.data = TgaMeasurement(**data)

            def is_mainfile(self, filename, logger):
                return filename.endswith((".tri", ".xlsx", ".txt", ".csv"))

        return TgaParser()


tga_parser_entry_point = TgaParserEntryPoint(
    name="tga_parser",
    description="Parse TGA/TRIOS instrument data (.tri, .xlsx, .txt, .csv)",
)
