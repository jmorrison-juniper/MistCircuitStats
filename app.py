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
        site_id = request.args.get('site_id')
        gateways = mist.get_gateway_stats(site_id=site_id)
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


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=(LOG_LEVEL == 'DEBUG'))
