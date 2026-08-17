"""Pytest config for NiceGUI user fixture."""
import os

# Keep tests in browser mode (no native window) — inherited by the app subprocess.
os.environ['TGA_NATIVE'] = '0'

pytest_plugins = ['nicegui.testing.user_plugin']
