"""Small helpers for running VASP and Quantum ESPRESSO on Slurm clusters."""

__version__ = "0.1.0"

from .qe import parse_pw_output  # noqa: E402
from .vasp import parse_outcar  # noqa: E402

__all__ = ["parse_outcar", "parse_pw_output", "__version__"]
