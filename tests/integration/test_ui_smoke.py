from streamlit.testing.v1 import AppTest
from pathlib import Path
import os
import pytest
import time

@pytest.mark.asyncio
async def test_ui_smoke():
    # Setup AppTest
    app_path = Path(__file__).parent.parent.parent / "policyfuzz" / "ui" / "app.py"
    
    # We set memory db to avoid conflicting with actual data
    os.environ["POLICYFUZZ_DB_PATH"] = ":memory:"
    os.environ["POLICYFUZZ_PROVIDER"] = "scripted"
    
    at = AppTest.from_file(str(app_path))
    at.run(timeout=15)
    
    # Verify title
    assert not at.exception
    
    # We will test that we can load the demo policy
    load_btn = [b for b in at.sidebar.button if b.label == "Load Demo Policy"]
    if load_btn:
        load_btn[0].click().run(timeout=15)
        
    start_btn = [b for b in at.sidebar.button if b.label in ("Start Run", "Start Audit")]
    if start_btn:
        start_btn[0].click().run(timeout=15)
        
    assert not at.exception
