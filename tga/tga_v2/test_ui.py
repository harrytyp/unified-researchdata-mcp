"""NiceGUI UI test — drives the real app (separate process) via the User API."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ['HOME'] = _tmp
os.environ['USERPROFILE'] = _tmp
os.environ['TGA_FAKE_CLIENT'] = '1'
sys.path.insert(0, str(Path(__file__).parent))

import pytest
from nicegui.testing import User


@pytest.mark.anyio
async def test_full_app_flow(user: User):
    await user.open('/')
    await asyncio.sleep(1.5)

    # 1. Header + tabs render
    await user.should_see('TGA Operator')
    await user.should_see('Board')
    await user.should_see('List')
    await user.should_see('Settings')
    await user.should_see('Log')
    print('1. PAGE + TABS OK')

    # 2. Fake client populated the board: sample cards visible
    await user.should_see('Probe A')
    await user.should_see('Probe B')
    await user.should_see('Probe C')
    print('2. BOARD CARDS OK (Probe A/B/C)')

    # 3. Tab switching works
    user.find('List').click()
    await asyncio.sleep(0.6)
    user.find('Board').click()
    await asyncio.sleep(0.5)
    await user.should_see('Probe A')
    print('3. TAB SWITCH OK')

    print('\nALLE UI-TESTS BESTANDEN')
