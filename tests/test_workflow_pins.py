"""Contract tests for the misthelper-devtools pins in workflows and requirements.

Each shared workflow and the development requirement must use one commit and one
release comment, so the CI tools and the local tools stay at the same release.
"""

import re  # The pins are plain text, so a pattern reads them without a YAML parser.
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # The repository root holds the pinned files.
EXPECTED_COMMIT = "da02d4c6a2163d1882f2ad25fce80b8ba38304d1"  # The commit of release v0.6.2.
EXPECTED_RELEASE = "v0.6.2"  # The release comment that names the commit for a human.
WORKFLOW_PIN = re.compile(r"misthelper-devtools/\S+@(\S+)\s+#\s+(\S+)")  # Capture the ref and comment.
REQUIREMENT_PIN = re.compile(r"misthelper-devtools @ \S+@(\S+)\s+#\s+(\S+)")  # Capture the commit and comment.
EXPECTED_WORKFLOW_PINS = 8  # Seven caller files hold eight reusable workflow jobs.


class TestDevtoolsPins:
    """Check that each misthelper-devtools pin names the same release."""

    def test_workflow_pins_use_the_release_commit(self) -> None:
        """Each reusable workflow call pins the release commit and its comment."""
        workflow_paths = sorted((ROOT / ".github" / "workflows").glob("*.yml"))  # Read each caller.
        pins = [  # Collect each ref and comment pair so the count proves the test read the files.
            match.groups()
            for workflow_path in workflow_paths
            for match in WORKFLOW_PIN.finditer(workflow_path.read_text(encoding="utf-8"))
        ]
        assert len(pins) == EXPECTED_WORKFLOW_PINS, pins  # A missed pin must fail, not pass silently.
        assert set(pins) == {(EXPECTED_COMMIT, EXPECTED_RELEASE)}, pins  # One commit and one comment.

    def test_requirement_pin_matches_the_workflow_commit(self) -> None:
        """The development requirement installs the same commit as the workflows."""
        requirement_text = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")  # Read the pin.
        match = REQUIREMENT_PIN.search(requirement_text)  # Find the one devtools requirement line.
        assert match is not None  # The file must keep the devtools requirement.
        assert match.groups() == (EXPECTED_COMMIT, EXPECTED_RELEASE)  # Match the workflow release.
