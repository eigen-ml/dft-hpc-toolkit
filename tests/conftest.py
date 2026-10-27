import shutil
from pathlib import Path

import pytest

DATA = Path(__file__).parent / "data"


@pytest.fixture
def vasp_template(tmp_path):
    """tests/data/vasp_template plus a fake POTCAR (real POTCARs are licensed and not in the repo)."""
    template = tmp_path / "template"
    shutil.copytree(str(DATA / "vasp_template"), str(template))
    (template / "POTCAR").write_text("  PAW_PBE C 08Apr2002\n   TITEL  = PAW_PBE C 08Apr2002\n")
    return template
