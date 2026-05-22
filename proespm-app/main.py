"""Proespm Web — Streamlit interface for proespm-py3 scientific data processing."""

import sys
import shutil
import tempfile
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile

import streamlit as st
from proespm.config import Config as ProespmConfig
from proespm.processing import (
    create_html,
    create_measurement_objs,
    process_loop,
)

st.set_page_config(
    page_title="Proespm — Scientific Data Reports",
    page_icon="🔬",
    layout="centered",
)

st.title("🔬 Proespm Web")
st.markdown(
    "Upload scientific data files and generate interactive HTML reports. "
    "Supports **SPM**, **XPS**, **AES**, **TPD**, **RGA**, **QCMB**, and more."
)

# ── Sidebar config ──
st.sidebar.header("Options")
colormap = st.sidebar.selectbox(
    "Colormap",
    ["viridis", "plasma", "inferno", "magma", "cividis", "gray", "hot", "jet"],
    index=0,
)
color_start = st.sidebar.slider("Color range start (%)", 0, 100, 0)
color_end = st.sidebar.slider("Color range end (%)", 0, 100, 100)

# ── File upload ──
st.markdown("### Upload data files")
uploaded_files = st.file_uploader(
    "Select files from your computer",
    accept_multiple_files=True,
)

if uploaded_files and st.button("Generate Report", type="primary"):
    with st.spinner("Processing data files..."):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()

            # Save uploaded files to temp directory
            for f in uploaded_files:
                dest = data_dir / f.name
                dest.write_bytes(f.getvalue())

            try:
                report_path = data_dir.parent / "report.html"

                config = ProespmConfig(
                    colormap=colormap,
                    colorrange=(color_start / 100, color_end / 100),
                )

                measurement_objs = create_measurement_objs(
                    str(data_dir), lambda msg: None
                )

                if not measurement_objs:
                    st.error(
                        "No supported data files found. "
                        "Supported formats: .mul, .flm, .mtrx, .sm4, .sxm, "
                        ".nid, .h5, .txt, .vms, .dat, .csv, .pssession, "
                        ".log, .png, .jpg"
                    )
                    st.stop()

                process_loop(measurement_objs, config, lambda msg: None)
                create_html(measurement_objs, str(report_path), "proespm_report")

                if not report_path.exists():
                    st.error("Report generation failed.")
                    st.stop()

                # Read the generated report
                html_content = report_path.read_text()

                # Offer download
                st.download_button(
                    label="📥 Download HTML Report",
                    data=html_content,
                    file_name="proespm_report.html",
                    mime="text/html",
                )

                # Also offer a ZIP with source data + report
                zip_buf = BytesIO()
                with ZipFile(zip_buf, "w") as zf:
                    zf.writestr("report.html", html_content)
                    for f in data_dir.iterdir():
                        if f.is_file():
                            zf.writestr(f"data/{f.name}", f.read_bytes())
                st.download_button(
                    label="📦 Download Report + Source Data (ZIP)",
                    data=zip_buf.getvalue(),
                    file_name="proespm_report.zip",
                    mime="application/zip",
                )

                # Show preview inline
                st.markdown("### Report Preview")
                st.components.v1.html(html_content, height=600, scrolling=True)

            except Exception as e:
                st.error(f"Processing error: {e}")
else:
    st.info(
        "Upload files above and click **Generate Report**. "
        "You can upload individual data files or a ZIP archive."
    )

    # Show supported formats
    with st.expander("Supported file formats"):
        st.markdown("""
        - **SPM**: .mul, .flm, .mtrx, .sm4, .sxm, .nid, .h5
        - **XPS**: .txt (Omicron EIS)
        - **AES**: .vms, .dat (STAIB WinSpectro)
        - **EC**: .csv, .pssession (PalmSens), EC4 (Nordic)
        - **TPD**: .txt (LabView)
        - **RGA**: Analog Scan, Pressure vs Time
        - **QCMB**: .log (Inficon STM2)
        - **Images**: .png, .jpg (LEED, etc.)
        """)

st.markdown("---")
st.caption(
    "Powered by [proespm-py3](https://github.com/matkrin/proespm-py3) · "
    "Part of Unified Research Data MCP"
)
