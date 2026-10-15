"""Build provenance: update this baseline only after integrating upstream code.

The upstream tree at f685a853 declares 1.0.2b8 in pyproject.toml and
octop/__init__.py. Yunmell's package version follows its own release sequence.
This metadata ships in wheels, containers and portable desktop packages.
"""

OFFICIAL_BASE_VERSION = "1.0.2b8"
OFFICIAL_BASE_COMMIT = "f685a85321aaa6f86328a356414091018342d68d"
OFFICIAL_REPOSITORY = "TencentCloud/Octop"
