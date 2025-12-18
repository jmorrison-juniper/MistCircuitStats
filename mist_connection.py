"""
Mist API Connection Wrapper
Handles all interactions with the Juniper Mist API using mistapi SDK
"""
import logging
from typing import List, Dict, Optional
import mistapi

logger = logging.getLogger(__name__)


class MistConnection:
    """Wrapper class for Mist API operations"""
    
    def __init__(self, api_token: str, org_id: Optional[str] = None, host: str = 'api.mist.com'):
        """
        Initialize Mist API connection
        
        Args:
            api_token: Mist API token for authentication
            org_id: Organization ID (optional, will auto-detect if not provided)
            host: Mist API host (default: api.mist.com)
        """
        if not api_token:
            raise ValueError("MIST_APITOKEN environment variable is required")
        
        self.api_token = api_token
        self.host = host
        self.org_id = org_id
        
        # Initialize mistapi session
        self.apisession = mistapi.APISession(
            host=self.host,
            apitoken=self.api_token
        )
        
        # Auto-detect org_id if not provided
        if not self.org_id:
            self._auto_detect_org()
        
        logger.info(f"Initialized Mist connection to {self.host} for org {self.org_id}")
    
    def _auto_detect_org(self):
        """Auto-detect organization ID from user privileges"""
        try:
            response = mistapi.api.v1.self.self.getSelf(self.apisession)
            if response.status_code == 200:
                data = response.data
                # Get first org from privileges
                if 'privileges' in data and len(data['privileges']) > 0:
                    self.org_id = data['privileges'][0].get('org_id')
                    logger.info(f"Auto-detected org_id: {self.org_id}")
                else:
                    raise ValueError("No organizations found in user privileges")
            else:
                raise Exception(f"Failed to get self info: {response.status_code}")
        except Exception as e:
            logger.error(f"Error auto-detecting org_id: {str(e)}")
            raise
    
    def get_organization_info(self) -> Dict:
        """Get current organization information"""
        try:
            if not self.org_id:
                raise ValueError("Organization ID is required")
            response = mistapi.api.v1.orgs.orgs.getOrg(self.apisession, self.org_id)
            if response.status_code == 200:
                data = response.data
                return {
                    'org_id': data.get('id'),
                    'org_name': data.get('name', 'Unknown Organization'),
                    'created_time': data.get('created_time', 0),
                    'updated_time': data.get('updated_time', 0)
                }
            else:
                raise Exception(f"API error: {response.status_code}")
        except Exception as e:
            logger.error(f"Error getting organization info: {str(e)}")
            raise
    
    def get_organizations(self) -> List[Dict]:
        """Get list of organizations the user has access to"""
        try:
            response = mistapi.api.v1.self.self.getSelf(self.apisession)
            if response.status_code == 200:
                data = response.data
                orgs = []
                if 'privileges' in data:
                    for priv in data['privileges']:
                        if 'org_id' in priv and 'org_name' in priv:
                            orgs.append({
                                'org_id': priv['org_id'],
                                'org_name': priv['org_name'],
                                'role': priv.get('role', 'unknown')
                            })
                return orgs
            else:
                raise Exception(f"API error: {response.status_code}")
        except Exception as e:
            logger.error(f"Error getting organizations: {str(e)}")
            raise
    
    def get_sites(self) -> List[Dict]:
        """Get list of sites in the organization"""
        try:
            if not self.org_id:
                raise ValueError("Organization ID is required")
            response = mistapi.api.v1.orgs.sites.listOrgSites(
                self.apisession,
                self.org_id
            )
            if response.status_code == 200:
                sites = response.data
                return [{
                    'id': site.get('id'),
                    'name': site.get('name'),
                    'address': site.get('address', ''),
                    'timezone': site.get('timezone', 'UTC'),
                    'num_devices': site.get('num_devices', 0)
                } for site in sites]
            else:
                raise Exception(f"API error: {response.status_code}")
        except Exception as e:
            logger.error(f"Error getting sites: {str(e)}")
            raise
    
    def _get_port_windowed_traffic(self, gw_site_id: str, device_id: str, port_id: str, start: int, end: int) -> Dict:
        """
        Get port-specific windowed traffic statistics from gateway insights API
        
        Args:
            gw_site_id: Site ID
            device_id: Gateway device ID (UUID format)
            port_id: Port ID (e.g., 'ge-0/0/1')
            start: Start time as Unix epoch timestamp
            end: End time as Unix epoch timestamp
            
        Returns:
            Dictionary with rx_bytes and tx_bytes for the time window
        """
        import requests
        
        # Calculate appropriate interval based on time window
        duration = end - start
        if duration <= 15 * 60:  # 15 minutes
            interval = 60  # 1 minute
        elif duration <= 60 * 60:  # 1 hour
            interval = 300  # 5 minutes
        elif duration <= 24 * 60 * 60:  # 1 day
            interval = 600  # 10 minutes
        else:  # 7 days or more
            interval = 3600  # 1 hour
        
        result = {'rx_bytes': 0, 'tx_bytes': 0}
        
        try:
            headers = {
                'Authorization': f'Token {self.api_token}',
                'Content-Type': 'application/json'
            }
            
            url = f'https://{self.host}/api/v1/sites/{gw_site_id}/insights/gateway/{device_id}/stats'
            params = {
                'interval': interval,
                'start': start,
                'end': end,
                'port_id': port_id,
                'metrics': 'rx_bps,tx_bps'
            }
            
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                
                # Calculate total bytes from time-series data
                rx_bps_values = data.get('rx_bps', [])
                tx_bps_values = data.get('tx_bps', [])
                
                # Sum up bytes for each interval (bps * interval_seconds / 8 bits per byte)
                for rx_bps in rx_bps_values:
                    if rx_bps is not None and rx_bps > 0:
                        result['rx_bytes'] += int((rx_bps * interval) / 8)
                
                for tx_bps in tx_bps_values:
                    if tx_bps is not None and tx_bps > 0:
                        result['tx_bytes'] += int((tx_bps * interval) / 8)
            else:
                logger.warning(f"Insights API error {response.status_code} for port {port_id}")
        
        except Exception as e:
            logger.warning(f"Error fetching insights data for port {port_id}: {str(e)}")
        
        return result
    
    def get_gateway_stats(self, site_id: Optional[str] = None, start: Optional[int] = None, end: Optional[int] = None) -> List[Dict]:
        """
        Get gateway statistics including WAN port information
        
        Args:
            site_id: Optional site ID to filter gateways
            start: Start time as Unix epoch timestamp
            end: End time as Unix epoch timestamp
            
        Returns:
            List of gateways with their WAN port statistics and configuration
        """
        try:
            if not self.org_id:
                raise ValueError("Organization ID is required")
            
            # Get site names mapping
            sites = self.get_sites()
            site_map = {s['id']: s['name'] for s in sites}
            
            # Get gateway device stats for basic info
            device_response = mistapi.api.v1.orgs.stats.listOrgDevicesStats(
                self.apisession,
                self.org_id,
                type='gateway'
            )
            
            if device_response.status_code != 200:
                raise Exception(f"API error getting device stats: {device_response.status_code}")
            
            gateways = device_response.data
            
            # Build a map of site_id -> site gateways for efficient port queries
            gateways_by_site = {}
            for gw in gateways:
                gw_site_id = gw.get('site_id')
                if gw_site_id:
                    if gw_site_id not in gateways_by_site:
                        gateways_by_site[gw_site_id] = []
                    gateways_by_site[gw_site_id].append(gw)
            
            # Get WAN port statistics per site using site-level endpoint
            wan_ports_by_device = {}
            for site_id_key, site_gateways in gateways_by_site.items():
                # Build API parameters
                params = {}
                if start is not None:
                    params['start'] = start
                if end is not None:
                    params['end'] = end
                
                port_response = mistapi.api.v1.sites.stats.searchSiteSwOrGwPorts(
                    self.apisession,
                    site_id_key,
                    **params
                )
                
                if port_response.status_code == 200:
                    for port in port_response.data.get('results', []):
                        if port.get('device_type') == 'gateway' and port.get('port_usage') == 'wan':
                            device_mac = port.get('mac')
                            if device_mac not in wan_ports_by_device:
                                wan_ports_by_device[device_mac] = []
                            wan_ports_by_device[device_mac].append(port)
            
            gateway_stats = []
            
            for gw in gateways:
                # Filter by site if specified
                if site_id and gw.get('site_id') != site_id:
                    continue
                
                gw_site_id = gw.get('site_id')
                gw_id = gw.get('id')
                gw_mac = gw.get('mac')
                
                # Get site name - fallback to API call if not in map (pagination issue)
                gw_site_name = site_map.get(gw_site_id, '')
                if not gw_site_name and gw_site_id:
                    try:
                        site_response = mistapi.api.v1.sites.sites.getSiteInfo(self.apisession, gw_site_id)
                        if site_response.status_code == 200:
                            gw_site_name = site_response.data.get('name', '')
                    except Exception as e:
                        logger.warning(f"Could not fetch site name for {gw_site_id}: {str(e)}")
                
                # Get WAN ports for this gateway
                wan_ports = wan_ports_by_device.get(gw_mac, [])
                
                # Get device configuration for IP details AND actual DHCP IPs
                port_configs = []
                ip_config_by_desc = {}  # Map by description for matching
                runtime_ips_by_port = {}  # Map of port_id -> actual runtime IP/netmask from if_stat
                
                if gw_site_id and gw_id:
                    try:
                        # Get device configuration for static IP configs
                        config_response = mistapi.api.v1.sites.devices.getSiteDevice(
                            self.apisession,
                            gw_site_id,
                            gw_id
                        )
                        if config_response.status_code == 200:
                            config_data = config_response.data
                            
                            # Extract IP configurations from port_config
                            if 'port_config' in config_data:
                                for port_name, port_cfg in config_data['port_config'].items():
                                    if port_cfg.get('usage') == 'wan':
                                        ip_cfg = port_cfg.get('ip_config', {})
                                        wan_cfg = port_cfg.get('wan_config', {})
                                        description = port_cfg.get('description', '').strip()
                                        
                                        # Store IP config by description for matching with runtime ports
                                        if description:
                                            ip_config_by_desc[description] = {
                                                'description': description,
                                                'ip': ip_cfg.get('ip', ''),
                                                'netmask': ip_cfg.get('netmask', ''),
                                                'gateway': ip_cfg.get('gateway', ''),
                                                'type': ip_cfg.get('type', 'dhcp'),
                                                'override': 'yes' if port_cfg.get('override', False) else 'no',
                                                'disabled': port_cfg.get('disabled', False)
                                            }
                        
                        # Get actual runtime IP addresses (including DHCP) from if_stat
                        device_search_response = mistapi.api.v1.sites.devices.searchSiteDevices(
                            self.apisession,
                            gw_site_id,
                            type='gateway',
                            mac=gw_mac,
                            stats=True
                        )
                        
                        if device_search_response.status_code == 200:
                            search_results = device_search_response.data.get('results', [])
                            if search_results and 'if_stat' in search_results[0]:
                                if_stat = search_results[0]['if_stat']
                                
                                # Extract runtime IPs for WAN interfaces
                                for if_name, if_data in if_stat.items():
                                    if if_data.get('port_usage') == 'wan':
                                        port_id = if_data.get('port_id', '')
                                        ips = if_data.get('ips', [])
                                        
                                        # Parse IP/CIDR notation (e.g., "192.168.20.2/24")
                                        if ips and len(ips) > 0 and '/' in ips[0]:
                                            ip_cidr = ips[0]
                                            ip, cidr = ip_cidr.split('/')
                                            
                                            # Convert CIDR to netmask
                                            cidr_int = int(cidr)
                                            mask = (0xffffffff >> (32 - cidr_int)) << (32 - cidr_int)
                                            netmask = f"{(mask >> 24) & 0xff}.{(mask >> 16) & 0xff}.{(mask >> 8) & 0xff}.{mask & 0xff}"
                                            
                                            runtime_ips_by_port[port_id] = {
                                                'ip': ip,
                                                'netmask': netmask,
                                                'address_mode': if_data.get('address_mode', 'Unknown')
                                            }
                    except Exception as e:
                        logger.warning(f"Could not fetch config for gateway {gw_id}: {str(e)}")
                
                # Combine WAN port stats with IP configuration
                for port in wan_ports:
                    port_id = port.get('port_id')
                    port_desc = port.get('port_desc', '').strip()
                    
                    # Match by description to get IP configuration
                    ip_config = ip_config_by_desc.get(port_desc, {})
                    
                    # If no match found in config, assume DHCP (most WAN ports use DHCP)
                    if not ip_config:
                        ip_config = {
                            'description': port_desc,
                            'ip': '',
                            'netmask': '',
                            'gateway': '',
                            'type': 'dhcp',  # Default to DHCP for unconfigured ports
                            'override': 'no',
                            'disabled': False
                        }
                    
                    # Get actual runtime IP (prioritize runtime IP for DHCP ports)
                    runtime_ip_data = runtime_ips_by_port.get(port_id, {})
                    
                    # Use runtime IP if available (for DHCP ports)
                    if runtime_ip_data and ip_config.get('type') == 'dhcp':
                        ip_addr = runtime_ip_data.get('ip', '')
                        netmask_str = runtime_ip_data.get('netmask', '')
                        # Convert dotted-decimal netmask to CIDR
                        if netmask_str and '.' in netmask_str:
                            parts = netmask_str.split('.')
                            binary = ''.join([bin(int(x)+256)[3:] for x in parts])
                            netmask = str(binary.count('1'))
                        else:
                            netmask = netmask_str
                    else:
                        # Use configured static IP
                        ip_addr = ip_config.get('ip', '').strip()
                        netmask = ip_config.get('netmask', '').strip()
                        
                        # Remove leading slash from netmask if present (CIDR notation)
                        if netmask.startswith('/'):
                            netmask = netmask[1:]
                    
                    # Get windowed traffic statistics from insights API if time range provided
                    if start is not None and end is not None and gw_site_id and gw_id:
                        windowed_stats = self._get_port_windowed_traffic(
                            gw_site_id, gw_id, port_id, start, end
                        )
                        rx_bytes = windowed_stats.get('rx_bytes', 0)
                        tx_bytes = windowed_stats.get('tx_bytes', 0)
                    else:
                        # Fallback to cumulative stats
                        rx_bytes = port.get('rx_bytes', 0)
                        tx_bytes = port.get('tx_bytes', 0)
                    
                    port_configs.append({
                        'name': port_id,
                        'description': ip_config.get('description', port.get('port_desc', '')),
                        'enabled': port.get('up', False) and not ip_config.get('disabled', False),
                        'usage': 'wan',
                        # IP Configuration (runtime for DHCP, configured for static)
                        'ip': ip_addr,
                        'netmask': netmask,
                        'gateway': ip_config.get('gateway', ''),
                        'type': ip_config.get('type', 'unknown'),
                        'override': ip_config.get('override', 'no'),
                        # Statistics - windowed if time range provided, otherwise cumulative
                        'up': port.get('up', False),
                        'rx_bytes': rx_bytes,
                        'tx_bytes': tx_bytes,
                        'rx_pkts': port.get('rx_pkts', 0),
                        'tx_pkts': port.get('tx_pkts', 0),
                        'rx_errors': port.get('rx_errors', 0),
                        'tx_errors': port.get('tx_errors', 0),
                        'speed': port.get('speed', 0),
                        'mac': port.get('port_mac', '')
                    })
                
                gateway_stats.append({
                    'id': gw_id,
                    'name': gw.get('name', 'Unknown'),
                    'site_id': gw_site_id,
                    'site_name': gw_site_name,
                    'model': gw.get('model', ''),
                    'version': gw.get('version', ''),
                    'status': gw.get('status', 'unknown'),
                    'uptime': gw.get('uptime', 0),
                    'ip': gw.get('ip', ''),
                    'mac': gw_mac,
                    'ports': port_configs,
                    'num_ports': len(port_configs)
                })
            
            return gateway_stats
        except Exception as e:
            logger.error(f"Error getting gateway stats: {str(e)}")
            raise
    
    def get_gateway_port_stats(self, gateway_id: str) -> Dict:
        """
        Get detailed port statistics for a specific gateway
        
        Args:
            gateway_id: Gateway device ID
            
        Returns:
            Detailed port statistics
        """
        try:
            # Get gateway stats using search devices endpoint
            if not self.org_id:
                raise ValueError("Organization ID is required")
            response = mistapi.api.v1.orgs.devices.searchOrgDevices(
                self.apisession,
                self.org_id,
                type='gateway',
                mac=gateway_id
            )
            
            if response.status_code == 200:
                gw = response.data
                port_stats = {}
                
                if 'port_stat' in gw:
                    for port_name, port_data in gw['port_stat'].items():
                        port_stats[port_name] = {
                            'up': port_data.get('up', False),
                            'rx_bytes': port_data.get('rx_bytes', 0),
                            'tx_bytes': port_data.get('tx_bytes', 0),
                            'rx_pkts': port_data.get('rx_pkts', 0),
                            'tx_pkts': port_data.get('tx_pkts', 0),
                            'rx_errors': port_data.get('rx_errors', 0),
                            'tx_errors': port_data.get('tx_errors', 0),
                            'rx_bps': port_data.get('rx_bps', 0),
                            'tx_bps': port_data.get('tx_bps', 0),
                            'speed': port_data.get('speed', 0),
                            'mac': port_data.get('mac', ''),
                            'full_duplex': port_data.get('full_duplex', True)
                        }
                
                return {
                    'gateway_id': gw.get('id'),
                    'gateway_name': gw.get('name', 'Unknown'),
                    'ports': port_stats,
                    'timestamp': gw.get('last_seen', 0)
                }
            else:
                raise Exception(f"API error: {response.status_code}")
        except Exception as e:
            logger.error(f"Error getting gateway port stats: {str(e)}")
            raise
