"""Sphinx configuration for the pysftp-ng documentation, built on Read the Docs."""

import importlib.metadata

project = "pysftp-ng"
author = "pysftp-ng contributors"
copyright = (
    "2014, Dundee Media & Technology, Inc; 2026, Abdul Hakim Aremeyaw and pysftp-ng contributors"
)
release = importlib.metadata.version("pysftp-ng")
version = ".".join(release.split(".")[:2])

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
    "myst_parser",
    "sphinx_copybutton",
]
source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
exclude_patterns = ["_build"]

html_theme = "furo"
html_title = f"pysftp-ng {release}"
# Keep quotes and "..." as typed: the troubleshooting titles must match error messages exactly.
smartquotes = False

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "paramiko": ("https://docs.paramiko.org/en/stable", None),
}

autodoc_member_order = "bysource"
myst_heading_anchors = 3
