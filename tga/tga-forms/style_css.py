"""Design tokens + CSS for the TGA form (Linear-inspired)."""

CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {
    --tga-accent: #5e6ad2;
    --tga-accent-hover: #7170ff;
    --tga-green: #10b981;
    --tga-radius: 12px;
}
html, body { font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif; }
body { margin: 0; }
body.body--dark { background: #0d0e12 !important; }
body.body--light { background: #f4f5f7 !important; }

/* ── Header ── */
.tga-header {
    background: rgba(20, 21, 26, 0.9) !important;
    backdrop-filter: blur(10px);
    border-bottom: 1px solid rgba(255,255,255,0.07);
    color: #f2f3f5;
}
body.body--light .tga-header {
    background: rgba(255,255,255,0.92) !important;
    border-bottom: 1px solid #e5e7ec;
    color: #17181c;
}
.tga-brand { font-weight: 600; font-size: 1.02rem; letter-spacing: -0.01em; }
.tga-user { font-size: 0.9rem; color: #c6cad3; }
body.body--light .tga-user { color: #4b5563; }
.tga-darkbtn { color: #c6cad3; }

/* ── Login gate ── */
.tga-login-wrap { min-height: 75vh; justify-content: center; }
.tga-login-card {
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 16px;
    padding: 3.2rem 3.5rem;
    display: flex; flex-direction: column; align-items: center; gap: 0.7rem;
    max-width: 480px; text-align: center;
    box-shadow: 0 0 0 1px rgba(0,0,0,0.25), 0 24px 60px rgba(0,0,0,0.4);
}
body.body--light .tga-login-card {
    background: #ffffff;
    border: 1px solid #e5e7ec;
    box-shadow: 0 8px 30px rgba(15, 23, 42, 0.08);
}
.tga-login-title { font-size: 1.35rem; font-weight: 600; letter-spacing: -0.02em; color: #f2f3f5; }
body.body--light .tga-login-title { color: #17181c; }
.tga-login-sub { color: #8a8f98; font-size: 0.95rem; line-height: 1.55; }
body.body--light .tga-login-sub { color: #6b7280; }

/* ── Page ── */
.tga-page { max-width: 860px; margin: 0 auto; padding: 2rem 1.25rem 4rem; gap: 1.1rem; }
.tga-hero { width: 100%; padding: 0.4rem 0 0.6rem; }
.tga-hero-title { font-size: 1.7rem; font-weight: 600; letter-spacing: -0.03em; color: #f2f3f5; }
body.body--light .tga-hero-title { color: #17181c; }
.tga-hero-sub { color: #8a8f98; font-size: 0.98rem; line-height: 1.5; }
body.body--light .tga-hero-sub { color: #6b7280; }

/* ── Panels ── */
.tga-panel {
    width: 100%;
    box-sizing: border-box;
    background: rgba(255,255,255,0.025);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: var(--tga-radius);
    padding: 1.15rem 1.3rem;
    display: flex; flex-direction: column; gap: 0.55rem;
}
body.body--light .tga-panel {
    background: #ffffff;
    border: 1px solid #e5e7ec;
    box-shadow: 0 1px 2px rgba(15,23,42,0.03);
}
.tga-section-icon { font-size: 1.45rem; margin-top: 0.1rem; }
.tga-section-title { font-weight: 600; font-size: 1.02rem; letter-spacing: -0.01em; color: #f2f3f5; }
body.body--light .tga-section-title { color: #17181c; }
.tga-section-sub { font-size: 0.83rem; color: #8a8f98; }
body.body--light .tga-section-sub { color: #6b7280; }
.tga-label { font-size: 0.8rem; font-weight: 500; color: #a5abb6; }
body.body--light .tga-label { color: #4b5563; }

/* ── Segments ── */
.tga-seg {
    width: 100%;
    box-sizing: border-box;
    border: 1px solid rgba(255,255,255,0.07);
    background: rgba(255,255,255,0.02);
    border-radius: 10px;
    padding: 0.8rem 0.95rem;
    display: flex; flex-direction: column; gap: 0.55rem;
}
body.body--light .tga-seg {
    border-color: #e8eaef;
    background: #fafbfc;
}
.tga-seg-icon { color: var(--tga-accent-hover); font-size: 1.1rem; }
.tga-seg-title { font-weight: 600; font-size: 0.9rem; color: #e8eaef; }
body.body--light .tga-seg-title { color: #1f2430; }
.tga-addseg { color: var(--tga-accent-hover); }

/* ── CTA ── */
.tga-cta { background: var(--tga-accent) !important; color: #fff !important; border-radius: 8px; }
.tga-cta:hover { background: var(--tga-accent-hover) !important; }

/* ── Success ── */
.tga-success {
    display: flex; flex-direction: column; align-items: center; gap: 0.4rem;
    border: 1px solid rgba(16, 185, 129, 0.35);
    background: rgba(16, 185, 129, 0.08);
    border-radius: 12px;
    padding: 1.6rem 2rem;
    text-align: center;
    color: #d1d5db;
}
body.body--light .tga-success { color: #374151; }
.tga-success-title { font-size: 1.15rem; font-weight: 600; color: #f2f3f5; }
body.body--light .tga-success-title { color: #111827; }
.tga-mono { font-family: ui-monospace, 'JetBrains Mono', Menlo, monospace; font-size: 0.78rem; color: #8a8f98; }
/* link to the created upload in the NOMAD GUI (success box) */
.tga-nomad-link { color: var(--tga-accent) !important; text-decoration: underline !important; margin: 2px 0 2px; }

/* ── Quasar input harmonization ── */
body.body--dark .q-field--outlined .q-field__control { background: rgba(255,255,255,0.02); }
body.body--light .q-field__control { background: #fff; }

/* NiceGUI injects its own styles into .q-page; ensure no double scrollbars */
.q-page { padding: 0 !important; }
</style>
"""
