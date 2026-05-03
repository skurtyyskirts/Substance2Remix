import os
import sys

# When running unit tests, standard modules are imported from the root.
# Therefore, make sure that relative imports inside those modules work.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
