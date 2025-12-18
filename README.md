# MistCircuitStats

A Flask web application that displays Gateway WAN port statistics from all gateways in a Juniper Mist organization.

![License](https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg)
![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![Flask](https://img.shields.io/badge/flask-3.0+-green.svg)

## Features

- 📊 Real-time gateway WAN port statistics
- 🌐 Organization-wide gateway overview
- 📱 Responsive dark theme UI with T-Mobile magenta accents
- 🔍 Search and filter by site or gateway name
- 📈 Traffic statistics (RX/TX bytes, packets, errors)
- 🎯 Per-port detailed statistics
- 🐳 Multi-architecture Docker support (amd64/arm64)
- 🔄 Automatic CI/CD with GitHub Actions

## Screenshots

_Screenshots coming soon_

## Quick Start

### Using Docker Compose (Recommended)

1. **Clone the repository**
   ```bash
   git clone https://github.com/jmorrison-juniper/MistCircuitStats.git
   cd MistCircuitStats
   ```

2. **Create environment file**
   ```bash
   cp .env.example .env
   # Edit .env and add your Mist API token
   ```

3. **Run with Docker Compose**
   ```bash
   docker-compose up -d
   ```

4. **Access the application**
   Open your browser to http://localhost:5000

### Local Development

1. **Clone and setup**
   ```bash
   git clone https://github.com/jmorrison-juniper/MistCircuitStats.git
   cd MistCircuitStats
   ```

2. **Create virtual environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env and add your Mist API token
   ```

5. **Run the application**
   ```bash
   python app.py
   ```

6. **Access the application**
   Open your browser to http://localhost:5000

### Using Docker Compose for Development

```bash
docker-compose -f docker-compose.dev.yml up
```

This mounts your local code into the container for live reloading.

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MIST_APITOKEN` | Yes | - | Your Mist API token |
| `MIST_ORG_ID` | No | Auto-detect | Organization ID (auto-detected from token privileges) |
| `MIST_HOST` | No | `api.mist.com` | Mist API host |
| `PORT` | No | `5000` | Application port |
| `LOG_LEVEL` | No | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

### Getting a Mist API Token

1. Log in to your Mist dashboard
2. Navigate to **Organization > Settings > API Tokens**
3. Create a new token with at least **Read** privileges
4. Copy the token to your `.env` file

## API Endpoints

- `GET /` - Main dashboard UI
- `GET /health` - Health check endpoint
- `GET /api/organizations` - List organizations
- `GET /api/sites` - List sites in organization
- `GET /api/gateways` - Get all gateways with WAN port stats
- `GET /api/gateway/<id>/ports` - Get detailed port stats for a gateway

## Architecture

```
MistCircuitStats/
├── app.py                 # Flask routes and application
├── mist_connection.py     # Mist API wrapper using mistapi SDK
├── templates/
│   └── index.html         # Single-page UI
├── requirements.txt       # Python dependencies
├── Dockerfile             # Multi-arch container definition
├── docker-compose.yml     # Production deployment
├── docker-compose.dev.yml # Development with live reload
├── .github/workflows/
│   └── build-and-push.yml # CI/CD pipeline
├── .env.example           # Environment template
├── .gitignore
├── LICENSE
└── README.md
```

## Container Images

Images are automatically built and published to GitHub Container Registry:

```bash
# Pull latest
docker pull ghcr.io/jmorrison-juniper/mistcircuitstats:latest

# Pull specific version (YY.MM.DD.HH.MM format)
docker pull ghcr.io/jmorrison-juniper/mistcircuitstats:25.01.15.14.30
```

### Multi-Architecture Support

Images are built for:
- `linux/amd64` (x86_64)
- `linux/arm64` (ARM64/Apple Silicon)

## Development

### Project Structure

- **Flask Application** (`app.py`): Routes and API endpoints
- **Mist Connection** (`mist_connection.py`): Wrapper for mistapi SDK
- **Frontend** (`templates/index.html`): Bootstrap 5.3.2 with dark theme
- **Styling**: T-Mobile magenta accent (#E20074)
- **Layout**: Optimized for iPad landscape (3-column grid)

### Running Tests

```bash
# Install dev dependencies
pip install pytest pytest-flask

# Run tests (coming soon)
pytest
```

## License

This project is licensed under the **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International** (CC BY-NC-SA 4.0).

You are free to:
- Share — copy and redistribute the material
- Adapt — remix, transform, and build upon the material

Under the following terms:
- Attribution — Give appropriate credit
- NonCommercial — Not for commercial use
- ShareAlike — Distribute under the same license

See [LICENSE](LICENSE) for full details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## Troubleshooting

### "Import mist_connection could not be resolved"
This is a lint warning that appears before dependencies are installed. It will resolve after running `pip install -r requirements.txt`.

### API Connection Issues
- Verify your `MIST_APITOKEN` is correct
- Check that your token has appropriate permissions
- Ensure you can reach `api.mist.com` (or your custom `MIST_HOST`)

### No Gateways Showing
- Verify your organization has gateways deployed
- Check the browser console for JavaScript errors
- Review application logs with `LOG_LEVEL=DEBUG`

## Support

For issues, questions, or contributions:
- Open an issue on [GitHub](https://github.com/jmorrison-juniper/MistCircuitStats/issues)
- Review the [Mist API documentation](https://api.mist.com/api/v1/docs)

## Acknowledgments

- Built with [Flask](https://flask.palletsprojects.com/)
- Uses [mistapi SDK](https://pypi.org/project/mistapi/)
- Styled with [Bootstrap 5.3.2](https://getbootstrap.com/)
- Icons from [Bootstrap Icons](https://icons.getbootstrap.com/)

---

Made with ❤️ for the Juniper Mist community
