"""Headless MintPy entry point; retain numerical closure diagnostics.

MintPy 1.6.4 attempts a closure histogram even with mintpy.plot=no and fails
when all ambiguity counts are zero (histogram bins=0). Suppress only that
figure, not calculation or the persisted quality raster used by our gate.
"""
import sys
from unittest.mock import patch


def main():
    from mintpy.cli.smallbaselineApp import main as smallbaseline
    with patch('mintpy.utils.plot.plot_num_triplet_with_nonzero_integer_ambiguity', return_value=None):
        smallbaseline(sys.argv[1:])


if __name__ == '__main__':
    main()
