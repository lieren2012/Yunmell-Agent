"""Build provenance: update this baseline only after integrating upstream code.

The upstream tree at 4f443bab declares 1.0.2b9 in pyproject.toml and
octop/__init__.py. Yunmell's package version follows its own release sequence.
This metadata ships in wheels, containers and portable desktop packages.
"""

OFFICIAL_BASE_VERSION = "1.0.2b9"
OFFICIAL_BASE_COMMIT = "4f443babdc1e3742e4ffdce4965c4ef32dc9f5e6"
OFFICIAL_REPOSITORY = "TencentCloud/Octop"
