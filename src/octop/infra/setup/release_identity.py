"""Build provenance: update this baseline only after integrating upstream code.

The upstream tree at 38c79c8a declares 1.0.2b6 in pyproject.toml and
octop/__init__.py. Yunmell's package version follows its own release sequence.
This metadata ships in wheels, containers and portable desktop packages.
"""

OFFICIAL_BASE_VERSION = "1.0.2b6"
OFFICIAL_BASE_COMMIT = "38c79c8a"
OFFICIAL_REPOSITORY = "TencentCloud/Octop"
