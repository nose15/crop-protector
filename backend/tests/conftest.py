import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
FIXTURES = Path(__file__).parent / "fixtures"
# testy nigdy nie piszą do backend/cache/
os.environ.setdefault("KOWR_CACHE_DIR", tempfile.mkdtemp(prefix="kowr-cache-test-"))
