import sys
from pathlib import Path

# Add src/ so tests can import config, viewer, dlc_3d_bp.*
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
