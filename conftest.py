"""Configure pytest: mock file logging before any test modules load."""
import sys
from unittest.mock import MagicMock

mock_log = MagicMock()

def mock_get_logger(name):
    return mock_log

# Patch app_logging.get_logger so tasks.py picks it up at import time
import app_logging
app_logging.get_logger = mock_get_logger
# Also patch the submodule reference if already cached
if 'app_logging' in sys.modules:
    sys.modules['app_logging'].get_logger = mock_get_logger
