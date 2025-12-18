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
    
    def get_gateway_stats(self, site_id: Optional[str] = None) -> List[Dict]:
        """
        Get gateway statistics with WAN port information
        
        Args:
            site_id: Optional site ID to filter gateways
            
        Returns:
            List of gateways with their WAN port statistics and configuration
        """
        try:
            if not self.org_id:
                raise ValueError("Organization ID is required")
            
            # Get site names mapping
            sites = self.get_sites()
            site_map = {s['id']: s['name'] for s in sites}
            
            # Use the correct API endpoint for gateway stats
            response = mistapi.api.v1.orgs.stats.listOrgDevicesStats(
                self.apisession,
                self.org_id,
                type='gateway'
            )
            
            if response.status_code == 200:
                gateways = response.data
                gateway_stats = []
                
                for gw in gateways:
                    # Filter by site if specified
                    if site_id and gw.get('site_id') != site_id:
                        continue
                    
                    gw_site_id = gw.get('site_id')
                    gw_id = gw.get('id')
                    
                    # Get detailed gateway configuration for port details
                    port_configs = []
                    if gw_site_id and gw_id:
                        try:
                            config_response = mistapi.api.v1.sites.devices.getSiteDevice(
                                self.apisession,
                                gw_site_id,
                                gw_id
                            )
                            if config_response.status_code == 200:
                                config_data = config_response.data
                                
                                # Extract WAN port configurations
                                if 'port_config' in config_data:
                                    for port_name, port_cfg in config_data['port_config'].items():
                                        # Get corresponding stats
                                        port_stat = {}
                                        if 'port_stat' in gw and port_name in gw['port_stat']:
                                            port_stat = gw['port_stat'][port_name]
                                        
                                        # Get WAN config if this is a WAN port
                                        wan_cfg = port_cfg.get('wan_config', {})
                                        ip_config = port_cfg.get('ip_config', {})
                                        
                                        port_configs.append({
                                            'name': port_name,
                                            'description': port_cfg.get('description', ''),
                                            'enabled': not port_cfg.get('disabled', False),
                                            'usage': port_cfg.get('usage', 'unknown'),
                                            # IP Configuration
                                            'ip': ip_config.get('ip', ''),
                                            'netmask': ip_config.get('netmask', ''),
                                            'gateway': ip_config.get('gateway', ''),
                                            'type': ip_config.get('type', 'dhcp'),
                                            # WAN Configuration  
                                            'wan_type': wan_cfg.get('type', ''),
                                            'wan_source_nat': wan_cfg.get('nat_mode', ''),
                                            'override': 'yes' if port_cfg.get('override', False) else 'no',
                                            # Statistics
                                            'up': port_stat.get('up', False),
                                            'rx_bytes': port_stat.get('rx_bytes', 0),
                                            'tx_bytes': port_stat.get('tx_bytes', 0),
                                            'rx_pkts': port_stat.get('rx_pkts', 0),
                                            'tx_pkts': port_stat.get('tx_pkts', 0),
                                            'rx_errors': port_stat.get('rx_errors', 0),
                                            'tx_errors': port_stat.get('tx_errors', 0),
                                            'speed': port_stat.get('speed', 0),
                                            'mac': port_stat.get('mac', '')
                                        })
                        except Exception as e:
                            logger.warning(f"Could not fetch config for gateway {gw_id}: {str(e)}")
                    
                    gateway_stats.append({
                        'id': gw_id,
                        'name': gw.get('name', 'Unknown'),
                        'site_id': gw_site_id,
                        'site_name': site_map.get(gw_site_id, gw.get('site_name', '')),
                        'model': gw.get('model', ''),
                        'version': gw.get('version', ''),
                        'status': gw.get('status', 'unknown'),
                        'uptime': gw.get('uptime', 0),
                        'ip': gw.get('ip', ''),
                        'mac': gw.get('mac', ''),
                        'ports': port_configs,
                        'num_ports': len(port_configs)
                    })
                
                return gateway_stats
            else:
                raise Exception(f"API error: {response.status_code}")
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
