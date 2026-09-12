"""Application layer for the Womier DUO87 display pad.

The pad driver and protocol live in ../duo87.py; this package is everything
above it: pages, rendering and the OS adapters they need.
"""
__all__ = ['core', 'render', 'osapi', 'pages']
