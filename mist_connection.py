"""
Mist API Connection Wrapper
Handles all interactions with the Juniper Mist API using mistapi SDK
"""

import logging
import time
from datetime import UTC, datetime

import mistapi

logger = logging.getLogger(__name__)

# WAN Insights feature — module-level helpers (T005/T006)
RETENTION_DAYS = 14
RETENTION_SECONDS = RETENTION_DAYS * 86400
HOUR_INTERVAL = 3600

_DURATION_MAP = {
    "1h": 3600,
    "6h": 6 * 3600,
    "24h": 24 * 3600,
    "3d": 3 * 86400,
    "7d": 7 * 86400,
}

# Sub-hourly for 1h view so the chart has enough buckets; hourly otherwise.
_INTERVAL_MAP = {
    "1h": ("10m", 600),
}


def duration_to_seconds(duration: str) -> int:
    """Map an allow-listed duration token to seconds. Raises ValueError otherwise."""
    if duration not in _DURATION_MAP:
        raise ValueError(f"duration must be one of: {', '.join(_DURATION_MAP.keys())}")
    return _DURATION_MAP[duration]


def interval_for_duration(duration: str) -> tuple[str, int]:
    """Return (api_param, seconds) for the sample interval to use for a duration."""
    return _INTERVAL_MAP.get(duration, ("1h", HOUR_INTERVAL))


def clip_to_retention_window(start: int, end: int, retention_days: int = RETENTION_DAYS) -> tuple[int, bool, str]:
    """Clip requested start to (end - retention). Returns (clamped_start, clipped_flag, notice)."""
    retention = retention_days * 86400
    earliest = end - retention
    if start < earliest:
        clamped_start = earliest
        clipped = True
        start_iso = datetime.fromtimestamp(clamped_start, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_iso = datetime.fromtimestamp(end, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        notice = (
            f"Data range clipped to the API's {retention_days}-day 1h-interval retention window "
            f"(from {start_iso} to {end_iso})."
        )
        return clamped_start, clipped, notice
    return start, False, ""


def hour_iso(ts: int, interval_s: int = HOUR_INTERVAL) -> str:
    """Render a UTC epoch second as a bucket-ISO string.

    Uses hour precision (`YYYY-MM-DDTHH:00:00Z`) for hourly or coarser
    intervals; falls back to minute precision when the interval is sub-hourly.
    """
    if interval_s and interval_s < HOUR_INTERVAL:
        return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:00Z")
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:00:00Z")


class MistConnection:
    """Wrapper class for Mist API operations"""

    # Class-level caches to reduce API calls across requests
    _sites_cache: list[dict] | None = None
    _sites_cache_time: float = 0
    _device_profile_cache: dict[str, dict] = {}
    _gateway_template_cache: dict[str, dict] = {}

    # Rate limiting tracking (per-token)
    _rate_limited_tokens: dict[str, float] = {}  # token -> reset time
    RATE_LIMIT_BACKOFF = 60  # seconds to wait before retrying after 429

    # Token rotation tracking
    _all_tokens: list[str] = []
    _current_token_index: int = 0

    # Cache TTLs (in seconds)
    SITES_CACHE_TTL = 300  # 5 minutes
    PROFILE_CACHE_TTL = 600  # 10 minutes

    def __init__(self, api_token: str, org_id: str | None = None, host: str = "api.mist.com"):
        """
        Initialize Mist API connection with support for multiple tokens

        Args:
            api_token: Mist API token(s) - can be comma-separated for multiple tokens
            org_id: Organization ID (optional, will auto-detect if not provided)
            host: Mist API host (default: api.mist.com)
        """
        if not api_token:
            raise ValueError("MIST_APITOKEN environment variable is required")

        # Parse multiple tokens (comma-separated)
        MistConnection._all_tokens = [t.strip() for t in api_token.split(",") if t.strip()]
        if not MistConnection._all_tokens:
            raise ValueError("No valid API tokens provided")

        logger.info(f"Initialized with {len(MistConnection._all_tokens)} API token(s)")

        self.host = host
        self.org_id = org_id

        # Initialize with the first available (non-rate-limited) token
        self._init_api_session()

        # Auto-detect org_id if not provided
        if not self.org_id:
            self._auto_detect_org()

        logger.info(f"Initialized Mist connection to {self.host} for org {self.org_id}")

    def _init_api_session(self):
        """Initialize or reinitialize the API session with the current token"""
        self.api_token = self._get_available_token()
        self.apisession = mistapi.APISession(
            host=self.host,
            apitoken=self.api_token,
            console_log_level=30,  # WARNING - reduce console noise
            logging_log_level=20,  # INFO - reasonable file logging
        )

    def _get_available_token(self) -> str:
        """Get the next available (non-rate-limited) token"""
        current_time = time.time()

        # Clean up expired rate limits
        expired_tokens = [
            t for t, reset_time in MistConnection._rate_limited_tokens.items() if current_time >= reset_time
        ]
        for token in expired_tokens:
            del MistConnection._rate_limited_tokens[token]
            logger.info("Token rate limit expired, token available again")

        # Try to find a non-rate-limited token
        for i in range(len(MistConnection._all_tokens)):
            idx = (MistConnection._current_token_index + i) % len(MistConnection._all_tokens)
            token = MistConnection._all_tokens[idx]
            if token not in MistConnection._rate_limited_tokens:
                MistConnection._current_token_index = idx
                return token

        # All tokens are rate limited, return the one with the soonest reset
        if MistConnection._rate_limited_tokens:
            soonest_token = min(MistConnection._rate_limited_tokens.items(), key=lambda x: x[1])[0]
            wait_time = MistConnection._rate_limited_tokens[soonest_token] - current_time
            logger.warning(f"All tokens rate limited. Soonest available in {int(wait_time)}s")
            return soonest_token

        # Fallback to current token
        return MistConnection._all_tokens[MistConnection._current_token_index]

    def _mark_token_rate_limited(self, token: str = None):
        """Mark the current token as rate limited and try to switch to another"""
        token = token or self.api_token
        reset_time = time.time() + MistConnection.RATE_LIMIT_BACKOFF
        MistConnection._rate_limited_tokens[token] = reset_time

        token_num = MistConnection._all_tokens.index(token) + 1 if token in MistConnection._all_tokens else "?"
        logger.warning(f"Token {token_num}/{len(MistConnection._all_tokens)} rate limited until {int(reset_time)}")

        # Try to switch to another token
        if len(MistConnection._all_tokens) > 1:
            old_token = self.api_token
            new_token = self._get_available_token()
            if new_token != old_token and new_token not in MistConnection._rate_limited_tokens:
                new_token_num = MistConnection._all_tokens.index(new_token) + 1
                logger.info(f"Switching to token {new_token_num}/{len(MistConnection._all_tokens)}")
                self.api_token = new_token
                self.apisession = mistapi.APISession(
                    host=self.host, apitoken=self.api_token, console_log_level=30, logging_log_level=20
                )
                return True  # Successfully switched
        return False  # No other token available

    def _is_rate_limited(self) -> bool:
        """Check if current token is rate limited"""
        current_time = time.time()
        if self.api_token in MistConnection._rate_limited_tokens:
            if current_time < MistConnection._rate_limited_tokens[self.api_token]:
                return True
            else:
                # Rate limit expired
                del MistConnection._rate_limited_tokens[self.api_token]
        return False

    def _handle_rate_limit_response(self, response: object) -> bool:
        """
        Check response for 429 rate limit and handle token rotation.

        Args:
            response: mistapi/requests response object whose status_code we inspect.

        Returns:
            True if rate limited (caller should handle), False if OK to proceed
        """
        if response.status_code == 429:
            switched = self._mark_token_rate_limited()
            if switched:
                logger.info("Switched to new token after 429")
            else:
                logger.warning("All tokens rate limited")
            return True
        return False

    def _auto_detect_org(self):
        """Auto-detect organization ID from user privileges"""
        try:
            response = mistapi.api.v1.self.self.getSelf(self.apisession)
            if self._handle_rate_limit_response(response):
                # Retry with new token
                response = mistapi.api.v1.self.self.getSelf(self.apisession)
            if response.status_code == 200:
                data = response.data
                # Get first org from privileges
                if "privileges" in data and len(data["privileges"]) > 0:
                    self.org_id = data["privileges"][0].get("org_id")
                    logger.info(f"Auto-detected org_id: {self.org_id}")
                else:
                    raise ValueError("No organizations found in user privileges")
            else:
                raise Exception(f"Failed to get self info: {response.status_code}")
        except Exception as e:
            logger.error(f"Error auto-detecting org_id: {str(e)}")
            raise

    def get_organization_info(self) -> dict:
        """Get current organization information"""
        try:
            if not self.org_id:
                raise ValueError("Organization ID is required")
            response = mistapi.api.v1.orgs.orgs.getOrg(self.apisession, self.org_id)
            if self._handle_rate_limit_response(response):
                response = mistapi.api.v1.orgs.orgs.getOrg(self.apisession, self.org_id)
            if response.status_code == 200:
                data = response.data
                return {
                    "org_id": data.get("id"),
                    "org_name": data.get("name", "Unknown Organization"),
                    "created_time": data.get("created_time", 0),
                    "updated_time": data.get("updated_time", 0),
                }
            else:
                raise Exception(f"API error: {response.status_code}")
        except Exception as e:
            logger.error(f"Error getting organization info: {str(e)}")
            raise

    def get_organizations(self) -> list[dict]:
        """Get list of organizations the user has access to"""
        try:
            response = mistapi.api.v1.self.self.getSelf(self.apisession)
            if self._handle_rate_limit_response(response):
                response = mistapi.api.v1.self.self.getSelf(self.apisession)
            if response.status_code == 200:
                data = response.data
                orgs = []
                if "privileges" in data:
                    for priv in data["privileges"]:
                        if "org_id" in priv and "org_name" in priv:
                            orgs.append(
                                {
                                    "org_id": priv["org_id"],
                                    "org_name": priv["org_name"],
                                    "role": priv.get("role", "unknown"),
                                }
                            )
                return orgs
            else:
                raise Exception(f"API error: {response.status_code}")
        except Exception as e:
            logger.error(f"Error getting organizations: {str(e)}")
            raise

    def get_sites(self) -> list[dict]:
        """Get list of sites in the organization (cached with pagination)"""
        try:
            if not self.org_id:
                raise ValueError("Organization ID is required")

            # Check class-level cache
            current_time = time.time()
            if (
                MistConnection._sites_cache is not None
                and current_time - MistConnection._sites_cache_time < self.SITES_CACHE_TTL
            ):
                logger.debug("Using cached sites data")
                return MistConnection._sites_cache

            # Fetch all sites with automatic pagination
            response = mistapi.api.v1.orgs.sites.listOrgSites(self.apisession, self.org_id, limit=1000)
            if self._handle_rate_limit_response(response):
                response = mistapi.api.v1.orgs.sites.listOrgSites(self.apisession, self.org_id, limit=1000)
            if response.status_code == 200:
                # Use get_all to handle pagination automatically
                sites = mistapi.get_all(self.apisession, response)
                result = [
                    {
                        "id": site.get("id"),
                        "name": site.get("name"),
                        "address": site.get("address", ""),
                        "timezone": site.get("timezone", "UTC"),
                        "num_devices": site.get("num_devices", 0),
                    }
                    for site in sites
                ]

                # Update cache
                MistConnection._sites_cache = result
                MistConnection._sites_cache_time = current_time
                logger.debug(f"Cached {len(result)} sites")

                return result
            else:
                raise Exception(f"API error: {response.status_code}")
        except Exception as e:
            logger.error(f"Error getting sites: {str(e)}")
            raise

    def _batch_fetch_inventory(self, gateway_macs: set) -> dict[str, dict]:
        """
        Batch fetch device inventory data (device profile IDs, site IDs) using org-level inventory.
        This provides profile/template IDs without per-device API calls.

        Args:
            gateway_macs: Set of gateway MAC addresses

        Returns:
            Dictionary keyed by MAC with inventory data (deviceprofile_id, site_id, etc.)
        """
        inventory_data = {}

        try:
            # Use org-level inventory to get device profile IDs for all gateways (with pagination)
            response = mistapi.api.v1.orgs.inventory.getOrgInventory(
                self.apisession, self.org_id, type="gateway", limit=1000
            )

            if self._handle_rate_limit_response(response):
                response = mistapi.api.v1.orgs.inventory.getOrgInventory(
                    self.apisession, self.org_id, type="gateway", limit=1000
                )

            if response.status_code == 200:
                # Use get_all to handle pagination automatically
                results = mistapi.get_all(self.apisession, response)

                for device in results:
                    mac = device.get("mac", "")
                    if mac not in gateway_macs:
                        continue

                    # Extract inventory data
                    inventory_data[mac] = {
                        "device_id": device.get("id"),
                        "site_id": device.get("site_id"),
                        "deviceprofile_id": device.get("deviceprofile_id"),
                        "name": device.get("name", ""),
                    }

                logger.debug(f"Batch fetched inventory for {len(inventory_data)} gateways")
            else:
                logger.warning(f"Org inventory returned {response.status_code}")

        except Exception as e:
            logger.warning(f"Error in batch inventory fetch: {str(e)}")

        return inventory_data

    def _get_device_profile(self, deviceprofile_id: str) -> dict:
        """
        Get device profile configuration (for Hub devices), using class-level cache

        Args:
            deviceprofile_id: Device profile ID

        Returns:
            Device profile data dictionary
        """
        cache_key = f"profile:{deviceprofile_id}"
        if cache_key in MistConnection._device_profile_cache:
            logger.debug(f"Using cached device profile {deviceprofile_id}")
            return MistConnection._device_profile_cache[cache_key]

        try:
            response = mistapi.api.v1.orgs.deviceprofiles.getOrgDeviceProfile(
                self.apisession, self.org_id, deviceprofile_id
            )
            if self._handle_rate_limit_response(response):
                response = mistapi.api.v1.orgs.deviceprofiles.getOrgDeviceProfile(
                    self.apisession, self.org_id, deviceprofile_id
                )
            if response.status_code == 200:
                MistConnection._device_profile_cache[cache_key] = response.data
                logger.debug(
                    f"Fetched and cached device profile {deviceprofile_id}: " f"{response.data.get('name', 'unknown')}"
                )
                return response.data
            else:
                logger.warning(f"Could not fetch device profile {deviceprofile_id}: {response.status_code}")
        except Exception as e:
            logger.warning(f"Error fetching device profile {deviceprofile_id}: {str(e)}")

        MistConnection._device_profile_cache[cache_key] = {}
        return {}

    def _get_gateway_template(self, gatewaytemplate_id: str) -> dict:
        """
        Get gateway template configuration (for Spoke/Branch devices), using class-level cache

        Args:
            gatewaytemplate_id: Gateway template ID

        Returns:
            Gateway template data dictionary
        """
        cache_key = f"template:{gatewaytemplate_id}"
        if cache_key in MistConnection._gateway_template_cache:
            logger.debug(f"Using cached gateway template {gatewaytemplate_id}")
            return MistConnection._gateway_template_cache[cache_key]

        try:
            response = mistapi.api.v1.orgs.gatewaytemplates.getOrgGatewayTemplate(
                self.apisession, self.org_id, gatewaytemplate_id
            )
            if self._handle_rate_limit_response(response):
                response = mistapi.api.v1.orgs.gatewaytemplates.getOrgGatewayTemplate(
                    self.apisession, self.org_id, gatewaytemplate_id
                )
            if response.status_code == 200:
                MistConnection._gateway_template_cache[cache_key] = response.data
                logger.debug(
                    f"Fetched and cached gateway template {gatewaytemplate_id}: "
                    f"{response.data.get('name', 'unknown')}"
                )
                return response.data
            else:
                logger.warning(f"Could not fetch gateway template {gatewaytemplate_id}: {response.status_code}")
        except Exception as e:
            logger.warning(f"Error fetching gateway template {gatewaytemplate_id}: {str(e)}")

        MistConnection._gateway_template_cache[cache_key] = {}
        return {}

    @staticmethod
    def _cidr_to_dotted_netmask(cidr_int: int) -> str:
        """Convert an integer CIDR prefix length to dotted-quad netmask string."""
        mask = (0xFFFFFFFF >> (32 - cidr_int)) << (32 - cidr_int)
        return f"{(mask >> 24) & 0xff}.{(mask >> 16) & 0xff}.{(mask >> 8) & 0xff}.{mask & 0xff}"

    @staticmethod
    def _dotted_netmask_to_cidr(netmask_str: str) -> str:
        """Convert a dotted-quad netmask string to CIDR prefix length (as string)."""
        if not netmask_str or "." not in netmask_str:
            return netmask_str
        parts = netmask_str.split(".")
        binary = "".join([bin(int(x) + 256)[3:] for x in parts])
        return str(binary.count("1"))

    def _fetch_gateway_device_list(self) -> list:
        """Fetch all gateway device stats rows for the org (paginated, rate-limit aware)."""
        device_response = mistapi.api.v1.orgs.stats.listOrgDevicesStats(
            self.apisession, self.org_id, type="gateway", limit=1000
        )
        if self._handle_rate_limit_response(device_response):
            device_response = mistapi.api.v1.orgs.stats.listOrgDevicesStats(
                self.apisession, self.org_id, type="gateway", limit=1000
            )
        if device_response.status_code != 200:
            raise Exception(f"API error getting device stats: {device_response.status_code}")
        return mistapi.get_all(self.apisession, device_response)

    def _fetch_org_port_stats_by_gateway(self, gateway_macs: set) -> tuple[dict, dict]:
        """Return (wan_ports_by_device, all_ports_by_device) keyed by gateway MAC."""
        wan_ports_by_device: dict = {}
        all_ports_by_device: dict = {}
        port_response = mistapi.api.v1.orgs.stats.searchOrgSwOrGwPorts(self.apisession, self.org_id, limit=1000)
        if self._handle_rate_limit_response(port_response):
            port_response = mistapi.api.v1.orgs.stats.searchOrgSwOrGwPorts(self.apisession, self.org_id, limit=1000)
        if port_response.status_code != 200:
            return wan_ports_by_device, all_ports_by_device

        for port in mistapi.get_all(self.apisession, port_response):
            device_mac = port.get("mac")
            if device_mac not in gateway_macs:
                continue
            port_id = port.get("port_id", "")
            all_ports_by_device.setdefault(device_mac, {})[port_id] = port
            if port.get("port_usage") == "wan":
                wan_ports_by_device.setdefault(device_mac, []).append(port)
        return wan_ports_by_device, all_ports_by_device

    def _fetch_device_config(self, gw_site_id: str, gw_id: str) -> dict:
        """Fetch per-device site config (port_config, template refs); {} on 429/error."""
        if not (gw_site_id and gw_id) or self._is_rate_limited():
            return {}
        response = mistapi.api.v1.sites.devices.getSiteDevice(self.apisession, gw_site_id, gw_id)
        if response.status_code == 429:
            if not self._mark_token_rate_limited():
                logger.warning("All tokens rate limited - returning partial data")
            return {}
        if response.status_code == 200:
            return response.data
        return {}

    def _build_merged_port_config(self, gw_id: str, deviceprofile_id: str | None, device_config: dict) -> dict:
        """Merge template/profile port_config with device-level overrides (device wins)."""
        merged: dict = {}
        gatewaytemplate_id = None if deviceprofile_id else device_config.get("gatewaytemplate_id")

        if deviceprofile_id:
            profile_data = self._get_device_profile(deviceprofile_id)
            if profile_data and "port_config" in profile_data:
                merged = dict(profile_data.get("port_config", {}))
                logger.debug(
                    f"Gateway {gw_id} (Hub) using device profile " f"{deviceprofile_id} with {len(merged)} ports"
                )
        elif gatewaytemplate_id:
            template_data = self._get_gateway_template(gatewaytemplate_id)
            if template_data and "port_config" in template_data:
                merged = dict(template_data.get("port_config", {}))
                logger.debug(
                    f"Gateway {gw_id} (Branch) using gateway template " f"{gatewaytemplate_id} with {len(merged)} ports"
                )

        for port_name, port_cfg in device_config.get("port_config", {}).items():
            if port_name in merged:
                merged[port_name].update(port_cfg)
            else:
                merged[port_name] = port_cfg
        return merged

    @staticmethod
    def _extract_wan_port_configs(merged_port_config: dict) -> dict:
        """Filter merged port_config down to WAN-usage entries with normalized fields."""
        wan_cfg: dict = {}
        for port_name, port_cfg in merged_port_config.items():
            if port_cfg.get("usage") != "wan":
                continue
            ip_cfg = port_cfg.get("ip_config", {})
            vlan_id = port_cfg.get("vlan_id", "")
            wan_cfg[port_name] = {
                "name": port_cfg.get("name", ""),
                "description": port_cfg.get("description", "").strip(),
                "ip": ip_cfg.get("ip", ""),
                "netmask": ip_cfg.get("netmask", ""),
                "gateway": ip_cfg.get("gateway", ""),
                "type": ip_cfg.get("type", "dhcp"),
                "vlan_id": str(vlan_id) if vlan_id else "",
                "override": "yes" if port_cfg.get("override", False) else "no",
                "disabled": port_cfg.get("disabled", False),
            }
        return wan_cfg

    def _fetch_runtime_ips(self, gw_site_id: str, gw_mac: str) -> dict:
        """Fetch live DHCP-assigned IPs per WAN port_id from site device stats."""
        runtime: dict = {}
        if not gw_site_id or self._is_rate_limited():
            return runtime
        response = mistapi.api.v1.sites.devices.searchSiteDevices(
            self.apisession, gw_site_id, type="gateway", mac=gw_mac, stats=True
        )
        if response.status_code == 429:
            if not self._mark_token_rate_limited():
                logger.warning("All tokens rate limited - returning partial data")
            return runtime
        if response.status_code != 200:
            return runtime

        results = response.data.get("results", [])
        if not results or "if_stat" not in results[0]:
            return runtime
        for _if_name, if_data in results[0]["if_stat"].items():
            if if_data.get("port_usage") != "wan":
                continue
            ips = if_data.get("ips", [])
            if not ips or "/" not in ips[0]:
                continue
            ip, cidr = ips[0].split("/")
            runtime[if_data.get("port_id", "")] = {
                "ip": ip,
                "netmask": self._cidr_to_dotted_netmask(int(cidr)),
                "address_mode": if_data.get("address_mode", "Unknown"),
            }
        return runtime

    @staticmethod
    def _match_wan_config_for_port(port_id: str, port_desc: str, wan_cfg_by_name: dict) -> dict:
        """Resolve a WAN config entry for a port by exact name, sub-interface prefix, or description."""
        cfg = wan_cfg_by_name.get(port_id, {})
        if cfg:
            return cfg
        for cfg_name, c in wan_cfg_by_name.items():
            if cfg_name.startswith(port_id + "."):
                return c
        if port_desc:
            for _cfg_name, c in wan_cfg_by_name.items():
                if c.get("description") == port_desc:
                    return c
        return {}

    def _resolve_ip_and_netmask(self, port_config: dict, runtime_ip_data: dict) -> tuple[str, str]:
        """Prefer runtime DHCP-assigned IP/netmask when the port is DHCP; else use configured values."""
        if runtime_ip_data and port_config.get("type") == "dhcp":
            return (
                runtime_ip_data.get("ip", ""),
                self._dotted_netmask_to_cidr(runtime_ip_data.get("netmask", "")),
            )
        ip_addr = port_config.get("ip", "").strip()
        netmask = port_config.get("netmask", "").strip()
        if netmask.startswith("/"):
            netmask = netmask[1:]
        return ip_addr, netmask

    @staticmethod
    def _build_wan_port_from_stats(port: dict, port_config: dict, ip_addr: str, netmask: str) -> dict:
        """Compose the WAN port dict from live port-stats plus resolved config/IP fields."""
        return {
            "name": port.get("port_id"),
            "wan_name": port_config.get("name", ""),
            "description": port_config.get("description", port.get("port_desc", "")),
            "enabled": port.get("up", False) and not port_config.get("disabled", False),
            "usage": "wan",
            "ip": ip_addr,
            "netmask": netmask,
            "gateway": port_config.get("gateway", ""),
            "type": port_config.get("type", "unknown"),
            "vlan_id": port_config.get("vlan_id", ""),
            "override": port_config.get("override", "no"),
            "up": port.get("up", False),
            "rx_bytes": port.get("rx_bytes", 0),
            "tx_bytes": port.get("tx_bytes", 0),
            "rx_pkts": port.get("rx_pkts", 0),
            "tx_pkts": port.get("tx_pkts", 0),
            "rx_errors": port.get("rx_errors", 0),
            "tx_errors": port.get("tx_errors", 0),
            "speed": port.get("speed", 0),
            "mac": port.get("port_mac", ""),
        }

    @staticmethod
    def _build_wan_port_from_config(
        base_port_name: str, cfg: dict, ip_addr: str, netmask: str, port_stats: dict
    ) -> dict:
        """Compose the WAN port dict from config alone (no live per-port stats entry)."""
        physical_up = port_stats.get("up", False)
        return {
            "name": base_port_name,
            "wan_name": cfg.get("name", ""),
            "description": cfg.get("description", ""),
            "enabled": physical_up and not cfg.get("disabled", False),
            "usage": "wan",
            "ip": ip_addr,
            "netmask": netmask,
            "gateway": cfg.get("gateway", ""),
            "type": cfg.get("type", "unknown"),
            "vlan_id": cfg.get("vlan_id", ""),
            "override": cfg.get("override", "no"),
            "up": physical_up,
            "rx_bytes": port_stats.get("rx_bytes", 0),
            "tx_bytes": port_stats.get("tx_bytes", 0),
            "rx_pkts": port_stats.get("rx_pkts", 0),
            "tx_pkts": port_stats.get("tx_pkts", 0),
            "rx_errors": port_stats.get("rx_errors", 0),
            "tx_errors": port_stats.get("tx_errors", 0),
            "speed": port_stats.get("speed", 0),
            "mac": port_stats.get("port_mac", ""),
        }

    def _build_ports_from_live_stats(self, wan_ports: list, wan_cfg_by_name: dict, runtime_ips_by_port: dict) -> list:
        """Build WAN port dicts for every port that has live stats, applying config overlays."""
        default_cfg = {
            "name": "",
            "description": "",
            "ip": "",
            "netmask": "",
            "gateway": "",
            "type": "dhcp",
            "vlan_id": "",
            "override": "no",
            "disabled": False,
        }
        results = []
        for port in wan_ports:
            port_id = port.get("port_id")
            port_desc = port.get("port_desc", "").strip()
            port_config = self._match_wan_config_for_port(port_id, port_desc, wan_cfg_by_name)
            if not port_config:
                port_config = {**default_cfg, "description": port_desc}
            ip_addr, netmask = self._resolve_ip_and_netmask(port_config, runtime_ips_by_port.get(port_id, {}))
            results.append(self._build_wan_port_from_stats(port, port_config, ip_addr, netmask))
        return results

    def _build_ports_from_config_only(
        self,
        wan_cfg_by_name: dict,
        runtime_ips_by_port: dict,
        device_port_stats: dict,
        ports_with_stats: set,
    ) -> list:
        """Build WAN port dicts from configuration for ports without any live stats row."""
        results = []
        for cfg_port_name, cfg in wan_cfg_by_name.items():
            if "{{" in cfg_port_name or "}}" in cfg_port_name:
                continue
            base_port_name = cfg_port_name.split(".")[0] if "." in cfg_port_name else cfg_port_name
            if cfg_port_name in ports_with_stats or base_port_name in ports_with_stats:
                continue
            ip_addr, netmask = self._resolve_ip_and_netmask(cfg, runtime_ips_by_port.get(base_port_name, {}))
            port_stats = device_port_stats.get(base_port_name, {})
            results.append(self._build_wan_port_from_config(base_port_name, cfg, ip_addr, netmask, port_stats))
        return results

    @staticmethod
    def _ports_with_stats_set(port_configs: list) -> set:
        """Return set of port names (both full and base) already produced from live stats."""
        s: set = set()
        for pc in port_configs:
            name = pc.get("name", "")
            s.add(name)
            if "." in name:
                s.add(name.split(".")[0])
        return s

    def _process_gateway(
        self,
        gw: dict,
        wan_ports_by_device: dict,
        all_ports_by_device: dict,
        inventory_map: dict,
        site_map: dict,
    ) -> dict:
        """Assemble a single gateway summary dict (site, ports, status) from cached lookups."""
        gw_site_id = gw.get("site_id")
        gw_id = gw.get("id")
        gw_mac = gw.get("mac")
        gw_site_name = site_map.get(gw_site_id, "")
        if not gw_site_name and gw_site_id:
            logger.warning(f"Site {gw_site_id} not found in cached site map")

        wan_ports = wan_ports_by_device.get(gw_mac, [])
        device_port_stats = all_ports_by_device.get(gw_mac, {})

        port_configs: list = []
        try:
            deviceprofile_id = inventory_map.get(gw_mac, {}).get("deviceprofile_id")
            device_config = self._fetch_device_config(gw_site_id, gw_id)
            merged_port_config = self._build_merged_port_config(gw_id, deviceprofile_id, device_config)
            wan_cfg_by_name = self._extract_wan_port_configs(merged_port_config)
            runtime_ips_by_port = self._fetch_runtime_ips(gw_site_id, gw_mac)

            port_configs = self._build_ports_from_live_stats(wan_ports, wan_cfg_by_name, runtime_ips_by_port)
            port_configs.extend(
                self._build_ports_from_config_only(
                    wan_cfg_by_name,
                    runtime_ips_by_port,
                    device_port_stats,
                    self._ports_with_stats_set(port_configs),
                )
            )
        except Exception as e:
            logger.warning(f"Could not process config for gateway {gw_id}: {str(e)}")

        port_configs.sort(key=lambda p: p.get("name", ""))
        return {
            "id": gw_id,
            "name": gw.get("name", "Unknown"),
            "site_id": gw_site_id,
            "site_name": gw_site_name,
            "model": gw.get("model", ""),
            "version": gw.get("version", ""),
            "status": gw.get("status", "unknown"),
            "uptime": gw.get("uptime", 0),
            "ip": gw.get("ip", ""),
            "mac": gw_mac,
            "ports": port_configs,
            "num_ports": len(port_configs),
        }

    def get_gateway_stats(
        self,
        site_id: str | None = None,
        start: int | None = None,  # noqa: ARG002 - preserved for API compat; snapshot uses cumulative counters
        end: int | None = None,  # noqa: ARG002 - preserved for API compat
    ) -> list[dict]:
        """
        Get gateway statistics including WAN port information.

        Orchestrates the fan-out; see helper methods for per-step work.
        """
        try:
            if not self.org_id:
                raise ValueError("Organization ID is required")

            sites = self.get_sites()
            site_map = {s["id"]: s["name"] for s in sites}
            gateways = self._fetch_gateway_device_list()
            gateway_macs = {gw.get("mac") for gw in gateways if gw.get("mac")}
            wan_ports_by_device, all_ports_by_device = self._fetch_org_port_stats_by_gateway(gateway_macs)
            inventory_map = self._batch_fetch_inventory(gateway_macs)

            return [
                self._process_gateway(gw, wan_ports_by_device, all_ports_by_device, inventory_map, site_map)
                for gw in gateways
                if not site_id or gw.get("site_id") == site_id
            ]
        except Exception as e:
            logger.error(f"Error getting gateway stats: {str(e)}")
            raise

    def _resolve_gateway_by_id(self, gateway_id: str) -> dict:
        """Resolve gateway id → device stats dict via listOrgDevicesStats."""
        mac_filter = gateway_id.replace("-", "")[-12:] if gateway_id else gateway_id
        response = mistapi.api.v1.orgs.stats.listOrgDevicesStats(
            self.apisession,
            self.org_id,
            type="gateway",
            mac=mac_filter,
        )
        if self._handle_rate_limit_response(response):
            response = mistapi.api.v1.orgs.stats.listOrgDevicesStats(
                self.apisession,
                self.org_id,
                type="gateway",
                mac=mac_filter,
            )
        if response.status_code != 200:
            raise Exception(f"API error: {response.status_code}")
        results = response.data if isinstance(response.data, list) else []
        return results[0] if results else {}

    @staticmethod
    def _extract_port_stats_from_device(dev: dict) -> dict:
        """Extract per-port stats dict from a site-device stats payload."""
        raw_ports = dev.get("port_stat") or dev.get("if_stat") or {}
        port_stats: dict = {}
        for port_name, port_data in raw_ports.items():
            if not isinstance(port_data, dict):
                continue
            port_stats[port_name] = {
                "up": port_data.get("up", False),
                "rx_bytes": port_data.get("rx_bytes", 0),
                "tx_bytes": port_data.get("tx_bytes", 0),
                "rx_pkts": port_data.get("rx_pkts", 0),
                "tx_pkts": port_data.get("tx_pkts", 0),
                "rx_errors": port_data.get("rx_errors", 0),
                "tx_errors": port_data.get("tx_errors", 0),
                "rx_bps": port_data.get("rx_bps", 0),
                "tx_bps": port_data.get("tx_bps", 0),
                "speed": port_data.get("speed", 0),
                "mac": port_data.get("mac", ""),
                "full_duplex": port_data.get("full_duplex", True),
            }
        return port_stats

    def _fetch_site_device_port_stats(self, site_id: str, device_id: str) -> tuple[dict, int]:
        """Fetch port stats + last-seen timestamp from site-scoped device stats."""
        if not (site_id and device_id):
            return {}, 0
        port_resp = mistapi.api.v1.sites.stats.getSiteDeviceStats(self.apisession, site_id, device_id)
        if self._handle_rate_limit_response(port_resp):
            port_resp = mistapi.api.v1.sites.stats.getSiteDeviceStats(self.apisession, site_id, device_id)
        if port_resp.status_code != 200 or not isinstance(port_resp.data, dict):
            return {}, 0
        dev = port_resp.data
        return self._extract_port_stats_from_device(dev), dev.get("last_seen", 0) or 0

    def get_gateway_port_stats(self, gateway_id: str) -> dict:
        """Get detailed port statistics for a specific gateway."""
        try:
            if not self.org_id:
                raise ValueError("Organization ID is required")
            gw = self._resolve_gateway_by_id(gateway_id)
            gateway_name = gw.get("name") or gw.get("hostname") or "Unknown"
            resolved_id = gw.get("id") or gateway_id
            port_stats, timestamp = self._fetch_site_device_port_stats(gw.get("site_id"), resolved_id)
            return {
                "gateway_id": resolved_id,
                "gateway_name": gateway_name,
                "ports": port_stats,
                "timestamp": timestamp,
            }
        except Exception as e:
            logger.error(f"Error getting gateway port stats: {str(e)}")
            raise

    def get_vpn_peer_stats(self, site_id: str, device_mac: str) -> dict:
        """Get VPN peer path statistics for a gateway.

        Why: closes the last direct-REST call in this module by routing the
        `POST/GET /orgs/{org_id}/stats/vpn_peers/search` call through the
        `mistapi.api.v1.orgs.stats.searchOrgPeerPathStats` SDK function, so it
        inherits the shared multi-token 60-second per-token 429 rotation from
        `_handle_rate_limit_response`.

        Args:
            site_id: Mist site UUID scoping the peer-path search.
            device_mac: 12-char gateway MAC address (no separators).

        Returns:
            On 200: ``{"success": True, "peers_by_port": {port_id: [peer, ...]},
            "total_peers": int}``. On all-tokens-cooling-down or other non-200:
            the same shape with ``success`` False, ``peers_by_port`` empty, and
            ``total_peers`` zero, plus ``rate_limited`` True for the cooldown
            case (byte-identical to the pre-migration envelope).
        """
        try:
            if not self.org_id:
                raise ValueError("Organization ID is required")

            # Check if we're currently rate limited on all tokens
            if self._is_rate_limited():
                logger.debug("Skipping VPN peer stats - all tokens rate limited")
                return {"success": False, "rate_limited": True, "peers_by_port": {}, "total_peers": 0}

            response = mistapi.api.v1.orgs.stats.searchOrgPeerPathStats(
                self.apisession, self.org_id, mac=device_mac, site_id=site_id
            )
            if self._handle_rate_limit_response(response):
                # _mark_token_rate_limited already rotated self.apisession
                response = mistapi.api.v1.orgs.stats.searchOrgPeerPathStats(
                    self.apisession, self.org_id, mac=device_mac, site_id=site_id
                )
                if response.status_code != 200:
                    return {"success": False, "rate_limited": True, "peers_by_port": {}, "total_peers": 0}

            if response.status_code == 200:
                data = response.data or {}
                results = data.get("results", [])

                # Group peer paths by port_id
                peers_by_port: dict = {}
                for peer in results:
                    port_id = peer.get("port_id", "")
                    if port_id not in peers_by_port:
                        peers_by_port[port_id] = []
                    peers_by_port[port_id].append(
                        {
                            "vpn_name": peer.get("vpn_name", ""),
                            "peer_router_name": peer.get("peer_router_name", ""),
                            "peer_port_id": peer.get("peer_port_id", ""),
                            "up": peer.get("up", False),
                            "is_active": peer.get("is_active", False),
                            "latency": peer.get("latency", 0),
                            "loss": peer.get("loss", 0),
                            "jitter": peer.get("jitter", 0),
                            "mos": peer.get("mos", 0),
                            "uptime": peer.get("uptime", 0),
                            "mtu": peer.get("mtu", 0),
                            "type": peer.get("type", ""),
                            "hop_count": peer.get("hop_count", 0),
                        }
                    )

                return {"success": True, "peers_by_port": peers_by_port, "total_peers": len(results)}
            else:
                logger.warning(f"VPN peer stats API error {response.status_code} for device {device_mac}")
                return {"success": False, "peers_by_port": {}, "total_peers": 0}
        except Exception as e:
            logger.warning(f"Error fetching VPN peer stats for device {device_mac}: {str(e)}")
            return {"success": False, "peers_by_port": {}, "total_peers": 0}

    def get_gateway_port_traffic_series(
        self,
        site_id: str,
        gateway_id: str,
        port_id: str,
        start: int,
        end: int,
        interval: int = 600,
    ) -> dict:
        """Fetch a rx_bps/tx_bps time series for one gateway port (chart-modal source).

        Why: replaces the inline ``requests.get`` in ``app.py::get_port_traffic``
        (the legacy chart-modal route) with a single SDK-backed wrapper so the
        call inherits the shared multi-token 60-second per-token 429 rotation
        from ``_handle_rate_limit_response``. Uses the same
        ``mistapi.api.v1.sites.insights.getSiteInsightMetricsForGateway`` path
        as ``_insights_gateway_stats`` but with an integer interval (seconds)
        and a fixed ``metrics="rx_bps,tx_bps"`` argument, matching what the
        pre-migration route sent to Mist.

        The returned envelope is ``{"success": bool, "data": {"timestamps":
        [...], "rx_bps": [...], "tx_bps": [...]}}`` — byte-identical to the
        pre-migration route body so ``templates/index.html`` reads it unchanged.

        Args:
            site_id: Mist site UUID.
            gateway_id: Gateway device UUID.
            port_id: WAN port identifier (e.g. "ge-0/0/0").
            start: Epoch seconds, inclusive.
            end: Epoch seconds, exclusive.
            interval: Bucket size in seconds (default 600 = 10-minute buckets).

        Returns:
            On 200: ``{"success": True, "data": {"timestamps": list[int],
            "rx_bps": list, "tx_bps": list}}``. On all-tokens-cooling-down
            or other non-200: ``{"success": False, "error": str}``.
        """
        if self._is_rate_limited():
            return {"success": False, "error": "Rate limited on all tokens"}

        try:
            response = mistapi.api.v1.sites.insights.getSiteInsightMetricsForGateway(
                self.apisession,
                site_id,
                gateway_id,
                "rx_bps,tx_bps",
                port_id=port_id,
                interval=interval,
                start=start,
                end=end,
            )
            if self._handle_rate_limit_response(response):
                # _mark_token_rate_limited already rotated self.apisession
                response = mistapi.api.v1.sites.insights.getSiteInsightMetricsForGateway(
                    self.apisession,
                    site_id,
                    gateway_id,
                    "rx_bps,tx_bps",
                    port_id=port_id,
                    interval=interval,
                    start=start,
                    end=end,
                )
                if response.status_code != 200:
                    return {"success": False, "error": "Rate limited after retry"}

            if response.status_code == 200:
                data = response.data or {}
                rx = data.get("rx_bps", []) or []
                tx = data.get("tx_bps", []) or []
                # Rebuild timestamps at requested interval; frontend expects list-of-int seconds
                result = {
                    "timestamps": [start + (i * interval) for i in range(len(rx))],
                    "rx_bps": rx,
                    "tx_bps": tx,
                }
                return {"success": True, "data": result}

            logger.warning(f"port traffic series API error {response.status_code} gateway={gateway_id} port={port_id}")
            return {"success": False, "error": f"API error: {response.status_code}"}
        except Exception as e:
            logger.warning(f"port traffic series error gateway={gateway_id} port={port_id}: {e}")
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------
    # WAN Insights feature — hourly bandwidth, wan_link_health, App Health SLE
    # ------------------------------------------------------------------

    def _insights_gateway_stats(
        self,
        site_id: str,
        device_id: str,
        port_id: str,
        start: int,
        end: int,
        metrics: str,
        interval_param: str = "1h",
    ) -> dict:
        """Fetch gateway insight metrics for one WAN port via the mistapi SDK.

        Why: routes ``GET /sites/{site_id}/insights/gateway/{device_id}/stats``
        through ``mistapi.api.v1.sites.insights.getSiteInsightMetricsForGateway``
        so the call inherits the shared multi-token 60-second per-token 429
        rotation from ``_handle_rate_limit_response``. Preserves the 14-day
        1h-interval retention window enforced upstream by the Mist API.

        Args:
            site_id: Mist site UUID.
            device_id: Gateway device UUID.
            port_id: WAN port identifier (e.g. "ge-0/0/0").
            start: Epoch seconds, inclusive.
            end: Epoch seconds, exclusive.
            metrics: Comma-separated Mist metric names (e.g. "tx_bps,rx_bps").
            interval_param: Interval string for bucket size (e.g. "1h", "10m").

        Returns:
            On 200: ``{"success": True, "rate_limited": False, "data": dict}``.
            On all-tokens-cooling-down: ``{"success": False, "rate_limited":
            True, "data": None}``. On other non-200 or transport error:
            ``{"success": False, "rate_limited": False, "data": None}``.
        """
        if self._is_rate_limited():
            return {"success": False, "rate_limited": True, "data": None}

        try:
            response = mistapi.api.v1.sites.insights.getSiteInsightMetricsForGateway(
                self.apisession,
                site_id,
                device_id,
                metrics,
                port_id=port_id,
                interval=interval_param,
                start=start,
                end=end,
            )
            if self._handle_rate_limit_response(response):
                # _mark_token_rate_limited already rotated self.apisession
                response = mistapi.api.v1.sites.insights.getSiteInsightMetricsForGateway(
                    self.apisession,
                    site_id,
                    device_id,
                    metrics,
                    port_id=port_id,
                    interval=interval_param,
                    start=start,
                    end=end,
                )
                if response.status_code != 200:
                    return {"success": False, "rate_limited": True, "data": None}

            if response.status_code == 200:
                return {"success": True, "rate_limited": False, "data": response.data}

            logger.warning(f"insights/gateway stats {response.status_code} metrics={metrics} port={port_id}")
            return {"success": False, "rate_limited": False, "data": None}
        except Exception as e:
            logger.warning(f"insights/gateway stats error metrics={metrics} port={port_id}: {e}")
            return {"success": False, "rate_limited": False, "data": None}

    def _insights_device_wan_link_health(
        self,
        site_id: str,
        device_id: str,
        port_id: str,
        start: int,
        end: int,
        interval_param: str = "1h",
    ) -> dict:
        """Fetch WAN link health samples for one gateway port via the mistapi SDK.

        Why: routes ``GET /sites/{site_id}/insights/device/{mac}/wan_link_health``
        through ``mistapi.api.v1.sites.insights.getSiteInsightMetricsForDevice``
        with ``metric="wan_link_health"`` so it inherits the shared multi-token
        60-second per-token 429 rotation from ``_handle_rate_limit_response``.

        Scope quirk: ``wan_link_health`` is a *device*-scoped metric — the
        identifier in the URL path is the 12-char MAC (no separators), NOT the
        gateway device UUID. This method targets ``getSiteInsightMetricsForDevice``
        (not the ``ForGateway`` variant), and derives the MAC from ``device_id``
        via ``device_id.replace("-", "")[-12:]``. Retention: 14 days at 1h.

        Args:
            site_id: Mist site UUID.
            device_id: Gateway device UUID; the trailing 12 hex chars become the MAC.
            port_id: WAN port identifier (e.g. "ge-0/0/0").
            start: Epoch seconds, inclusive.
            end: Epoch seconds, exclusive.
            interval_param: Interval string for bucket size (e.g. "1h", "10m").

        Returns:
            On 200: ``{"success": True, "rate_limited": False, "data": dict}``.
            On all-tokens-cooling-down: ``{"success": False, "rate_limited":
            True, "data": None}``. On other non-200 or transport error:
            ``{"success": False, "rate_limited": False, "data": None}``.
        """
        if self._is_rate_limited():
            return {"success": False, "rate_limited": True, "data": None}

        mac = device_id.replace("-", "")[-12:]

        try:
            response = mistapi.api.v1.sites.insights.getSiteInsightMetricsForDevice(
                self.apisession,
                site_id,
                "wan_link_health",
                mac,
                port_id=port_id,
                interval=interval_param,
                start=start,
                end=end,
            )
            if self._handle_rate_limit_response(response):
                # _mark_token_rate_limited already rotated self.apisession
                response = mistapi.api.v1.sites.insights.getSiteInsightMetricsForDevice(
                    self.apisession,
                    site_id,
                    "wan_link_health",
                    mac,
                    port_id=port_id,
                    interval=interval_param,
                    start=start,
                    end=end,
                )
                if response.status_code != 200:
                    return {"success": False, "rate_limited": True, "data": None}

            if response.status_code == 200:
                return {"success": True, "rate_limited": False, "data": response.data}

            logger.warning(f"insights/device wan_link_health {response.status_code} mac={mac} port={port_id}")
            return {"success": False, "rate_limited": False, "data": None}
        except Exception as e:
            logger.warning(f"insights/device wan_link_health error mac={mac} port={port_id}: {e}")
            return {"success": False, "rate_limited": False, "data": None}

    def get_gateway_hourly_bandwidth(
        self,
        site_id: str,
        device_id: str,
        port_id: str,
        start: int,
        end: int,
        interval_param: str = "1h",
        interval_seconds: int = HOUR_INTERVAL,
    ) -> dict:
        """
        Return per-bucket Rx/Tx bandwidth for one WAN port.

        Wraps GET /insights/gateway/{device_id}/stats?metrics=tx_bps,rx_bps,max_tx_bps,max_rx_bps

        Args:
            site_id: Mist site UUID.
            device_id: Gateway device UUID.
            port_id: WAN port identifier (e.g. "ge-0/0/0").
            start: Epoch seconds, inclusive.
            end: Epoch seconds, exclusive.
            interval_param: Interval string sent to the Insights API (e.g. "1h", "10m").
            interval_seconds: Fallback bucket size in seconds when the API omits `interval` in the response.

        Returns:
            {
              'success': bool,
              'rate_limited': bool,
              'samples': [
                {'timestamp': int, 'hour_iso': str,
                 'tx_bps': float|None, 'rx_bps': float|None,
                 'max_tx_bps': float|None, 'max_rx_bps': float|None},
                ...
              ]
            }
        """
        result = self._insights_gateway_stats(
            site_id,
            device_id,
            port_id,
            start,
            end,
            metrics="tx_bps,rx_bps,max_tx_bps,max_rx_bps",
            interval_param=interval_param,
        )
        if not result["success"]:
            return {"success": False, "rate_limited": result["rate_limited"], "samples": []}

        data = result["data"] or {}
        interval = data.get("interval", interval_seconds) or interval_seconds
        env_start = data.get("start", start)
        tx = data.get("tx_bps", []) or []
        rx = data.get("rx_bps", []) or []
        max_tx = data.get("max_tx_bps", []) or []
        max_rx = data.get("max_rx_bps", []) or []
        n = max(len(tx), len(rx), len(max_tx), len(max_rx))

        samples = []
        for i in range(n):
            ts = int(env_start + i * interval)
            samples.append(
                {
                    "timestamp": ts,
                    "hour_iso": hour_iso(ts, interval),
                    "tx_bps": tx[i] if i < len(tx) else None,
                    "rx_bps": rx[i] if i < len(rx) else None,
                    "max_tx_bps": max_tx[i] if i < len(max_tx) else None,
                    "max_rx_bps": max_rx[i] if i < len(max_rx) else None,
                }
            )

        return {"success": True, "rate_limited": False, "samples": samples}

    @staticmethod
    def _wlh_from_list(wlh: list) -> tuple[list, list, list]:
        """Extract per-index (latency, jitter, loss) arrays from a list-shaped wan_link_health payload."""
        latency_arr, jitter_arr, loss_arr = [], [], []
        for entry in wlh:
            if isinstance(entry, dict):
                latency_arr.append(entry.get("latency") or entry.get("avg_latency"))
                jitter_arr.append(entry.get("jitter") or entry.get("avg_jitter"))
                loss_arr.append(entry.get("loss") or entry.get("avg_loss"))
            else:
                latency_arr.append(None)
                jitter_arr.append(None)
                loss_arr.append(None)
        return latency_arr, jitter_arr, loss_arr

    @staticmethod
    def _wlh_from_dict(wlh: dict) -> tuple[list, list, list]:
        """Extract (latency, jitter, loss) arrays from a dict-shaped wan_link_health payload."""
        return (
            wlh.get("latency", wlh.get("avg_latency", [])) or [],
            wlh.get("jitter", wlh.get("avg_jitter", [])) or [],
            wlh.get("loss", wlh.get("avg_loss", [])) or [],
        )

    @classmethod
    def _parse_wan_link_health_arrays(cls, data: dict) -> tuple[list, list, list]:
        """Normalize wan_link_health payload shapes to (latency, jitter, loss) arrays.

        The device-scoped endpoint returns top-level keys `avg_latency`, `avg_jitter`,
        `avg_loss` (each an array). Older gateway-scoped shapes are also tolerated.
        """
        if any(k in data for k in ("avg_latency", "avg_jitter", "avg_loss")):
            return (
                data.get("avg_latency", []) or [],
                data.get("avg_jitter", []) or [],
                data.get("avg_loss", []) or [],
            )
        wlh = data.get("wan_link_health")
        if isinstance(wlh, list):
            return cls._wlh_from_list(wlh)
        if isinstance(wlh, dict):
            return cls._wlh_from_dict(wlh)
        return (
            data.get("latency", []) or [],
            data.get("jitter", []) or [],
            data.get("loss", []) or [],
        )

    def get_gateway_hourly_wan_link_health(
        self,
        site_id: str,
        device_id: str,
        port_id: str,
        start: int,
        end: int,
        interval_param: str = "1h",
        interval_seconds: int = HOUR_INTERVAL,
    ) -> dict:
        """
        Return per-bucket jitter/latency/loss for one WAN port via the native
        wan_link_health insight metric (device-scoped endpoint).

        Args:
            site_id: Mist site UUID.
            device_id: Gateway device UUID.
            port_id: WAN port identifier (e.g. "ge-0/0/0").
            start: Epoch seconds, inclusive.
            end: Epoch seconds, exclusive.
            interval_param: Interval string sent to the Insights API (e.g. "1h", "10m").
            interval_seconds: Fallback bucket size in seconds when the API omits `interval` in the response.

        Returns:
            {
              'success': bool,
              'rate_limited': bool,
              'samples': [
                {'timestamp': int, 'hour_iso': str,
                 'avg_latency_ms': float|None,
                 'avg_jitter_ms': float|None,
                 'avg_loss_pct': float|None},
                ...
              ]
            }
        """
        result = self._insights_device_wan_link_health(
            site_id, device_id, port_id, start, end, interval_param=interval_param
        )
        if not result["success"]:
            return {"success": False, "rate_limited": result["rate_limited"], "samples": []}

        data = result["data"] or {}
        interval = data.get("interval", interval_seconds) or interval_seconds
        env_start = data.get("start", start)

        latency_arr, jitter_arr, loss_arr = self._parse_wan_link_health_arrays(data)

        n = max(len(latency_arr), len(jitter_arr), len(loss_arr))
        samples = []
        for i in range(n):
            ts = int(env_start + i * interval)
            samples.append(
                {
                    "timestamp": ts,
                    "hour_iso": hour_iso(ts, interval),
                    "avg_latency_ms": latency_arr[i] if i < len(latency_arr) else None,
                    "avg_jitter_ms": jitter_arr[i] if i < len(jitter_arr) else None,
                    "avg_loss_pct": loss_arr[i] if i < len(loss_arr) else None,
                }
            )

        return {"success": True, "rate_limited": False, "samples": samples}

    def _sle_app_health_get(self, site_id: str, sub_path: str, params: dict | None = None) -> dict:
        """Fetch one of three Application Health SLE endpoints via the mistapi SDK.

        Why: routes the three ``/sites/{site_id}/sle/site/{site_id}/metric/
        application-health/{sub_path}`` calls (``summary-trend``,
        ``impacted-interfaces``, ``threshold``) through the SDK so they inherit
        the shared multi-token 60-second per-token 429 rotation from
        ``_handle_rate_limit_response``. Dispatches on ``sub_path``:

        * ``summary-trend`` → ``getSiteSleSummaryTrend``. Used **instead of**
          ``/summary`` because ``getSiteSleSummary`` returns HTTP 400 on the
          target org for the ``application-health`` metric. The SDK function
          does NOT accept ``interval`` (verified via ``inspect.signature``);
          the previously-passed ``interval=3600`` was Mist's API default so
          bucket cadence is unchanged.
        * ``impacted-interfaces`` → ``listSiteSleImpactedInterfaces``.
        * ``threshold`` → ``getSiteSleThreshold``.

        Args:
            site_id: Mist site UUID. Used both as the site scope and as the
                ``scope_id`` (site-scoped SLE).
            sub_path: One of ``"summary-trend"``, ``"impacted-interfaces"``,
                ``"threshold"``.
            params: Optional dict of query params; only ``start`` and ``end``
                are forwarded to the SDK (``interval`` is dropped for
                ``summary-trend`` as noted above). ``threshold`` ignores params.

        Returns:
            On 200: ``{"success": True, "rate_limited": False, "data": dict|list}``.
            On all-tokens-cooling-down: ``{"success": False, "rate_limited":
            True, "data": None}``. On other non-200 or transport error:
            ``{"success": False, "rate_limited": False, "data": None}``.
        """
        if self._is_rate_limited():
            return {"success": False, "rate_limited": True, "data": None}

        params = params or {}
        start = params.get("start")
        end = params.get("end")

        def _call() -> object:
            """Invoke the correct SDK function based on ``sub_path`` (closure captures locals)."""
            if sub_path == "summary-trend":
                # getSiteSleSummaryTrend does not accept `interval` — drop it (was API default 3600 anyway)
                return mistapi.api.v1.sites.sle.getSiteSleSummaryTrend(
                    self.apisession, site_id, "site", site_id, "application-health", start=start, end=end
                )
            if sub_path == "impacted-interfaces":
                return mistapi.api.v1.sites.sle.listSiteSleImpactedInterfaces(
                    self.apisession, site_id, "site", site_id, "application-health", start=start, end=end
                )
            if sub_path == "threshold":
                return mistapi.api.v1.sites.sle.getSiteSleThreshold(
                    self.apisession, site_id, "site", site_id, "application-health"
                )
            raise ValueError(f"Unsupported App Health SLE sub_path: {sub_path}")

        try:
            response = _call()
            if self._handle_rate_limit_response(response):
                # _mark_token_rate_limited already rotated self.apisession
                response = _call()
                if response.status_code != 200:
                    return {"success": False, "rate_limited": True, "data": None}

            if response.status_code == 200:
                return {"success": True, "rate_limited": False, "data": response.data}

            # 400 or other = unavailable, treat as no-data (spec: return HTTP 200 unavailable case)
            logger.info(f"App Health SLE {sub_path} returned {response.status_code} for site {site_id}")
            return {"success": False, "rate_limited": False, "data": None}
        except Exception as e:
            logger.warning(f"App Health SLE {sub_path} error site {site_id}: {e}")
            return {"success": False, "rate_limited": False, "data": None}

    @staticmethod
    def _pct_from_good_total(good, total) -> float | None:
        """Return good/total as a percentage rounded to 2 decimals, or None if total is falsy."""
        tot = total or 0
        g = good or 0
        return round(100.0 * g / tot, 2) if tot else None

    def _fetch_app_health_summary_trend(
        self, site_id: str, start: int, end: int, interval_seconds: int = HOUR_INTERVAL
    ) -> dict:
        """
        Single fetch of /summary-trend that both summary_pct and trend derive from.
        The /summary endpoint returns 400 "unknown" for application-health, but
        /summary-trend returns 200 with sle.samples.{total,degraded,value} arrays.
        """
        return self._sle_app_health_get(
            site_id,
            "summary-trend",
            params={"interval": interval_seconds, "start": start, "end": end},
        )

    @staticmethod
    def _extract_sle_samples(data: dict) -> tuple[list, list, list, int, int]:
        """Return (totals, degradeds, values, env_start, interval) from a summary-trend payload."""
        sle = data.get("sle") if isinstance(data, dict) else None
        samples = sle.get("samples", {}) if isinstance(sle, dict) else {}
        totals = samples.get("total", []) or []
        degradeds = samples.get("degraded", []) or []
        values = samples.get("value", []) or []
        env_start = int(data.get("start") or sle.get("start") if isinstance(sle, dict) else 0) or int(
            data.get("start", 0)
        )
        interval = int(data.get("interval") or HOUR_INTERVAL)
        return totals, degradeds, values, env_start, interval

    def _parse_app_health_summary_from_trend(self, trend_result: dict) -> tuple[float | None, bool]:
        """Derive summary_pct = 100 * (sum(total) - sum(degraded)) / sum(total)."""
        if not (trend_result["success"] and isinstance(trend_result["data"], dict)):
            return None, trend_result["rate_limited"]
        totals, degradeds, _values, _es, _iv = self._extract_sle_samples(trend_result["data"])
        tot = sum(t or 0 for t in totals)
        if not tot:
            return None, trend_result["rate_limited"]
        deg = sum(d or 0 for d in degradeds)
        return round(100.0 * (tot - deg) / tot, 2), trend_result["rate_limited"]

    def _parse_app_health_trend_from_trend(self, trend_result: dict, start: int) -> tuple[list, bool]:
        """Build per-bucket [{timestamp, pct}] from a summary-trend payload."""
        if not (trend_result["success"] and isinstance(trend_result["data"], dict)):
            return [], trend_result["rate_limited"]
        totals, degradeds, values, env_start, interval = self._extract_sle_samples(trend_result["data"])
        env_start = env_start or start
        n = max(len(totals), len(degradeds), len(values))
        trend = []
        for i in range(n):
            ts = int(env_start + i * interval)
            total = totals[i] if i < len(totals) else 0
            degraded = degradeds[i] if i < len(degradeds) else 0
            if total:
                pct = round(100.0 * (total - degraded) / total, 2)
            elif i < len(values) and values[i] is not None:
                pct = values[i]
            else:
                pct = None
            trend.append({"timestamp": ts, "pct": pct})
        return trend, trend_result["rate_limited"]

    def _parse_app_health_impacted(self, site_id: str, start: int, end: int) -> tuple[list, bool]:
        """Fetch and normalize the impacted-interfaces list from the App Health SLE."""
        ii = self._sle_app_health_get(site_id, "impacted-interfaces", params={"start": start, "end": end})
        if not ii["success"]:
            return [], ii["rate_limited"]
        payload = ii["data"]
        entries = payload.get("results", []) if isinstance(payload, dict) else (payload or [])
        impacted = [
            {
                "interface_name": row.get("interface") or row.get("port_id") or row.get("name") or "",
                "gateway_hostname": row.get("hostname") or row.get("gateway_hostname") or "",
                "gateway_mac": row.get("mac") or row.get("gateway_mac") or "",
                "duration": row.get("duration", 0),
                "degraded": row.get("degraded", 0),
                "total": row.get("total", 0),
            }
            for row in entries
            if isinstance(row, dict)
        ]
        return impacted, ii["rate_limited"]

    def _parse_app_health_threshold(self, site_id: str) -> tuple[float | None, bool]:
        """Fetch the App Health SLE threshold value (site-configured degraded cutoff)."""
        th = self._sle_app_health_get(site_id, "threshold")
        if not (th["success"] and isinstance(th["data"], dict)):
            return None, th["rate_limited"]
        return th["data"].get("threshold") or th["data"].get("sle"), th["rate_limited"]

    def get_site_application_health(
        self, site_id: str, start: int, end: int, interval_seconds: int = HOUR_INTERVAL
    ) -> dict:
        """Fetch native Mist Application Health SLE (summary/trend/impacted/threshold).

        summary_pct and trend both derive from a single /summary-trend call
        because the /summary endpoint returns HTTP 400 for application-health.
        """
        trend_result = self._fetch_app_health_summary_trend(site_id, start, end, interval_seconds)
        summary_pct, rl1 = self._parse_app_health_summary_from_trend(trend_result)
        trend, rl2 = self._parse_app_health_trend_from_trend(trend_result, start)
        impacted_interfaces, rl3 = self._parse_app_health_impacted(site_id, start, end)
        threshold_pct, rl4 = self._parse_app_health_threshold(site_id)

        return {
            "success": True,
            "rate_limited": rl1 or rl2 or rl3 or rl4,
            "site_id": site_id,
            "summary_pct": summary_pct,
            "threshold_pct": threshold_pct,
            "trend": trend,
            "impacted_interfaces": impacted_interfaces,
        }
