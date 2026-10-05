"""Offline tests that keep the test Compose override free of host ports and fixed names."""

from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
PRODUCTION_FILE = REPOSITORY_ROOT / "docker-compose.yml"
TEST_OVERRIDE_FILE = REPOSITORY_ROOT / "compose.test.yml"
SERVICE_NAME = "mistcircuitstats"
YAML_NULLS = frozenset({"", "~", "null", "Null", "NULL"})


@dataclass(frozen=True)
class ComposeTag:
    """Hold a Compose merge tag, such as !reset or !override, and the value that it carries."""

    tag: str
    value: object


class ComposeLoader(yaml.SafeLoader):
    """Read Compose YAML safely and keep the Compose merge tags that SafeLoader rejects."""

    @staticmethod
    def construct_tag(loader: yaml.SafeLoader, node: yaml.Node) -> ComposeTag:
        """Keep the tag name and the plain value of a tagged node.

        Args:
            loader: The loader that reads the document.
            node: The tagged YAML node.

        Returns:
            The tag name and the value of the node.

        Raises:
            ConstructorError: The node is not a sequence, a mapping, or a scalar.
        """
        if isinstance(node, yaml.SequenceNode):  # A list value, such as "ports: !reset []".
            return ComposeTag(node.tag, loader.construct_sequence(node, deep=True))
        if isinstance(node, yaml.MappingNode):  # A mapping value, such as an !override block.
            return ComposeTag(node.tag, loader.construct_mapping(node, deep=True))
        if not isinstance(node, yaml.ScalarNode):  # YAML has no fourth node kind.
            raise yaml.constructor.ConstructorError(None, None, "unknown node", node.start_mark)
        scalar = loader.construct_scalar(node)  # The tag hides the scalar type, so read text.
        return ComposeTag(node.tag, None if scalar in YAML_NULLS else scalar)


for compose_tag in ("!reset", "!override"):  # Compose defines these two merge tags.
    ComposeLoader.add_constructor(compose_tag, ComposeLoader.construct_tag)


class ComposeService:
    """Read one service from a Compose file and merge an override into it as Compose does."""

    def __init__(self, path: Path, name: str = SERVICE_NAME) -> None:
        """Read the service definition from a Compose file.

        Args:
            path: The Compose file to read.
            name: The service to read from the file.
        """
        loader = ComposeLoader(path.read_text(encoding="utf-8"))  # A SafeLoader subclass.
        try:
            document = loader.get_single_data()  # Each Compose file holds one document.
        finally:
            loader.dispose()  # Release the parser state.
        self.settings: dict = document["services"][name]  # Each test reads one service.

    def merged_with(self, override: "ComposeService") -> dict:
        """Merge an override into this service with the !reset and !override rules of Compose.

        Args:
            override: The service settings from the override file.

        Returns:
            The merged service settings.
        """
        merged = dict(self.settings)  # Copy, so the base settings do not change.
        for key, value in override.settings.items():
            if isinstance(value, ComposeTag) and value.tag == "!reset":
                merged.pop(key, None)  # Compose removes a reset key from the result.
            elif isinstance(value, ComposeTag):
                merged[key] = value.value  # Compose replaces an !override value.
            elif isinstance(value, list):
                merged[key] = [*merged.get(key, []), *value]  # Compose appends list values.
            else:
                merged[key] = value  # Compose replaces a scalar or mapping value here.
        return merged


def find_host_exposure(settings: dict) -> list[str]:
    """List each service setting that publishes a host port or fixes the container name.

    Args:
        settings: The merged service settings.

    Returns:
        The names of the settings that break the test stack rules.
    """
    findings = []  # Collect each finding, so the test message lists all of them.
    if settings.get("ports"):
        findings.append("ports")  # A published port collides with other stacks.
    if settings.get("container_name"):
        findings.append("container_name")  # A fixed name collides with other stacks.
    if settings.get("network_mode") == "host":
        findings.append("network_mode")  # Host networking shares the host ports.
    return findings


@pytest.fixture(name="production")
def fixture_production() -> ComposeService:
    """Read the production service from docker-compose.yml.

    Returns:
        The production service.
    """
    return ComposeService(PRODUCTION_FILE)


@pytest.fixture(name="test_override")
def fixture_test_override() -> ComposeService:
    """Read the test override service from compose.test.yml.

    Returns:
        The test override service.
    """
    return ComposeService(TEST_OVERRIDE_FILE)


def test_production_file_publishes_port_and_fixed_name(production: ComposeService) -> None:
    """Prove that the guard finds both settings in the production file that the override removes."""
    assert find_host_exposure(production.settings) == ["ports", "container_name"]


def test_test_override_resets_port_and_name(test_override: ComposeService) -> None:
    """Reset ports and container_name, because an omitted key keeps the production value."""
    assert test_override.settings["ports"] == ComposeTag("!reset", [])
    assert test_override.settings["container_name"] == ComposeTag("!reset", None)


def test_merged_test_stack_publishes_no_port(production: ComposeService, test_override: ComposeService) -> None:
    """Publish no host port and set no fixed container name in the merged test stack."""
    merged = production.merged_with(test_override)

    assert find_host_exposure(merged) == []
    assert merged["image"] == "mistcircuitstats:local-test"
    assert merged["restart"] == "no"
    assert "healthcheck" in merged


def test_merged_test_stack_does_not_require_env_file(production: ComposeService, test_override: ComposeService) -> None:
    """Let the config command run without .env, so an operator can check the file first."""
    merged = production.merged_with(test_override)

    assert merged["env_file"] == [{"path": ".env", "required": False}]


def test_guard_fails_when_override_omits_reset(production: ComposeService, tmp_path: Path) -> None:
    """Report the port and the name when an override leaves out the !reset tags."""
    unsafe_override = tmp_path / "compose.unsafe.yml"
    unsafe_override.write_text(
        f"services:\n  {SERVICE_NAME}:\n    image: mistcircuitstats:local-test\n",
        encoding="utf-8",
    )

    merged = production.merged_with(ComposeService(unsafe_override))

    assert find_host_exposure(merged) == ["ports", "container_name"]
