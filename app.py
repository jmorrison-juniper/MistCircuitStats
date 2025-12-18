"""
MistCircuitStats - Flask application for displaying Gateway WAN port statistics
"""
import os
import logging
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, render_template, jsonify, request
from mist_connection import MistConnection

# Load environment variables from .env file
load_dotenv()

# Configure logging
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)

# Initialize Mist connection
mist = MistConnection(
    api_token=os.getenv('MIST_APITOKEN', ''),
    org_id=os.getenv('MIST_ORG_ID'),
    host=os.getenv('MIST_HOST', 'api.mist.com')
)


@app.route('/')
def index():
    """Render the main dashboard page"""
    return render_template('index.html')


@app.route('/health')
def health():
    """Health check endpoint for container orchestration"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.utcnow().isoformat()}), 200


@app.route('/api/organization')
def get_organization():
    """Get current organization information"""
    try:
        org_info = mist.get_organization_info()
        return jsonify({'success': True, 'data': org_info})
    except Exception as e:
        logger.error(f"Error fetching organization info: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/organizations')
def get_organizations():
    """Get list of organizations (if org_id not specified)"""
    try:
        orgs = mist.get_organizations()
        return jsonify({'success': True, 'data': orgs})
    except Exception as e:
        logger.error(f"Error fetching organizations: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/sites')
def get_sites():
    """Get list of sites in the organization"""
    try:
        sites = mist.get_sites()
        return jsonify({'success': True, 'data': sites})
    except Exception as e:
        logger.error(f"Error fetching sites: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/gateways')
def get_gateways():
    """Get all gateways with their WAN port statistics"""
    try:
        import time
        site_id = request.args.get('site_id')
        duration = request.args.get('duration', '7d')  # Default to 7 days
        
        # Calculate epoch timestamps based on duration
        end = int(time.time())
        duration_map = {
            '15m': 15 * 60,
            '1h': 60 * 60,
            '1d': 24 * 60 * 60,
            '7d': 7 * 24 * 60 * 60
        }
        seconds = duration_map.get(duration, 24 * 60 * 60)  # Default to 1 day
        start = end - seconds
        
        logger.info(f"Fetching gateway stats with timeframe: {duration} (start={start}, end={end})")
        gateways = mist.get_gateway_stats(site_id=site_id, start=start, end=end)
        return jsonify({'success': True, 'data': gateways})
    except Exception as e:
        logger.error(f"Error fetching gateway stats: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/gateway/<gateway_id>/ports')
def get_gateway_ports(gateway_id):
    """Get detailed WAN port statistics for a specific gateway"""
    try:
        port_stats = mist.get_gateway_port_stats(gateway_id)
        return jsonify({'success': True, 'data': port_stats})
    except Exception as e:
        logger.error(f"Error fetching gateway port stats: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/gateway/<gateway_id>/port/<path:port_id>/traffic')
def get_port_traffic(gateway_id, port_id):
    """Get time-series traffic data for a specific port"""
    try:
        import requests
        from urllib.parse import unquote
        
        # Decode the port_id in case it's URL encoded
        port_id = unquote(port_id)
        
        site_id = request.args.get('site_id')
        start = int(request.args.get('start', 0))
        end = int(request.args.get('end', 0))
        interval = int(request.args.get('interval', 600))
        
        if not site_id or start == 0 or end == 0:
            return jsonify({'success': False, 'error': 'site_id, start, and end are required'}), 400
        
        logger.info(f"Fetching traffic for gateway {gateway_id}, port {port_id}, interval {interval}")
        
        # Fetch from Mist insights API
        headers = {
            'Authorization': f'Token {mist.api_token}',
            'Content-Type': 'application/json'
        }
        
        url = f'https://{mist.host}/api/v1/sites/{site_id}/insights/gateway/{gateway_id}/stats'
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
            
            # Format response for frontend
            result = {
                'timestamps': [start + (i * interval) for i in range(len(data.get('rx_bps', [])))],
                'rx_bps': data.get('rx_bps', []),
                'tx_bps': data.get('tx_bps', [])
            }
            
            return jsonify({'success': True, 'data': result})
        else:
            logger.error(f"Insights API error: {response.status_code}")
            return jsonify({'success': False, 'error': f'API error: {response.status_code}'}), 500
            
    except Exception as e:
        logger.error(f"Error fetching port traffic: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/gateway/<gateway_id>/vpn_peers')
def get_vpn_peers(gateway_id):
    """Get VPN peer path statistics for a gateway"""
    try:
        site_id = request.args.get('site_id')
        device_mac = request.args.get('mac')
        
        if not site_id or not device_mac:
            return jsonify({'success': False, 'error': 'site_id and mac are required'}), 400
        
        logger.info(f"Fetching VPN peers for gateway {gateway_id} (MAC: {device_mac})")
        
        peer_stats = mist.get_vpn_peer_stats(site_id, device_mac)
        
        return jsonify(peer_stats)
            
    except Exception as e:
        logger.error(f"Error fetching VPN peers: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=(LOG_LEVEL == 'DEBUG'))
