"""Launch the VTuber Engine backend."""
import sys
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent))

from core.main import main

if __name__ == "__main__":
    main()
