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
                logger.info("TGA parsing: " + str(mainfile))
                from instrument_data.schema import TgaMeasurement, InstrumentSample

                if str(mainfile).endswith(".tri"):
                    # .tri is TRIOS' binary format, not the text-based
                    # CSV/TXT export -- must go through tri_binary, not
                    # parse_file(). Only header metadata is available
                    # today; time/temperature/weight signals are not
                    # yet decoded for this format (see tri_format package).
                    from instrument_data.tri_binary import extract_key_fields
                    from instrument_data.parser import parse_datetime
                    fields = extract_key_fields(mainfile)
                    archive.data = TgaMeasurement(
                        sample=InstrumentSample(
                            sample_name=fields.get("sample_name"),
                            operator=fields.get("operator"),
                            run_date=parse_datetime(fields.get("run_date") or ""),
                        ),
                        instrument_name=fields.get("instrument_name"),
                        instrument_type=fields.get("instrument_type"),
                        procedure_name=fields.get("procedure_name"),
                        procedure_segments=fields.get("procedure_segments"),
                        crucible_type=fields.get("crucible_type"),
                        pan_number=fields.get("pan_number"),
                        original_filename=str(mainfile),
                    )
                    return

                from instrument_data.parser import parse_file
                data = parse_file(mainfile)
                if data:
                    archive.data = TgaMeasurement(**data)

            def is_mainfile(self, filename, mime, buffer, decoded_buffer, compression=None):
                return filename.endswith((".tri", ".xlsx", ".txt", ".csv"))

        return TgaParser()


tga_parser_entry_point = TgaParserEntryPoint(
    name="tga_parser",
    description="Parse TGA/TRIOS instrument data (.tri, .xlsx, .txt, .csv)",
)
