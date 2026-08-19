"""The three non-entry pages.

This file exists for packaging, not for importing: setuptools' find_packages
skips a directory without __init__.py, so without it the page scripts would be
absent from an installed wheel and `dra` would start a navigation whose links
lead nowhere. Streamlit's own page discovery excludes __init__.py by name, so
it never shows up as a page.
"""
