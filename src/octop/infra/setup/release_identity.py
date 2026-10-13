"""Build provenance: update this baseline only after integrating upstream code.

The upstream tree at 664c1fb3 declares 1.0.2b7 in pyproject.toml and
octop/__init__.py. Yunmell's package version follows its own release sequence.
This metadata ships in wheels, containers and portable desktop packages.
"""

OFFICIAL_BASE_VERSION = "1.0.2b7"
OFFICIAL_BASE_COMMIT = "664c1fb38e354ea987041aa14b151e20d15ce71f"
OFFICIAL_REPOSITORY = "TencentCloud/Octop"
