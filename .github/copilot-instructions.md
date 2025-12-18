# MistCircuitStats - Copilot Instructions

## Project Overview
Flask web application for displaying Juniper Mist Gateway WAN port statistics using the mistapi SDK.

## Key Architecture Patterns
- Flask with application factory pattern
- mistapi SDK for Mist API integration
- Bootstrap 5.3.2 dark theme with T-Mobile magenta accent (#E20074)
- Single-page application with vanilla JavaScript
- Multi-architecture Docker containers (amd64/arm64)

## Environment Variables
- MIST_APITOKEN (required): Mist API token
- MIST_ORG_ID (optional): Auto-detected from token
- MIST_HOST (default: api.mist.com)
- PORT (default: 5000)
- LOG_LEVEL (default: INFO)

## Development Guidelines
- Non-root container user for security
- OCI labels with YY.MM.DD.HH.MM version format
- Health check endpoint at /health
- Responsive design optimized for iPad landscape (3-column grid)
- Toast notifications for user feedback
- Search/filter functionality for gateways

## Code Quality Guidelines
- Always check for linter issues before committing
- Run Pylance compile checks on all Python files before committing:
  - Check for syntax errors using Pylance file syntax checks
  - Verify all imports are resolved
  - Ensure no type checking errors remain
  - Use `typeCheckingMode: standard` for balanced strictness
- Use type hints for function parameters and return values
- Handle Optional types properly (provide defaults or validate)
- Verify mistapi SDK method names and signatures against documentation
- Use proper error handling with specific error messages
- Validate environment variables before use (provide defaults or raise clear errors)

## mistapi SDK Usage
- API responses have `.status_code` and `.data` attributes
- Check status_code == 200 for successful responses
- Key endpoints:
  - `mistapi.api.v1.self.self.getSelf()` - Get user info and org privileges
  - `mistapi.api.v1.orgs.sites.listOrgSites()` - List sites in org
  - `mistapi.api.v1.orgs.stats.listOrgStats()` - Get org statistics
  - `mistapi.api.v1.orgs.devices.searchOrgDevices()` - Search devices
- Always validate org_id before making API calls

## Container Development Guidelines
- Always test container builds locally before pushing
- Use Podman or Docker to verify successful compilation
- Build command: `podman build --build-arg BUILD_DATE=$(date -u +'%y.%m.%d.%H.%M') --build-arg VERSION=local-test -t mistcircuitstats:local-test .`
- Verify dependencies resolve correctly (watch for version conflicts)
- Check final image size (should be ~160-200 MB)
- Test container runs before committing: `podman run -p 5000:5000 --env-file .env mistcircuitstats:local-test`

## Dependency Management
- `mistapi` requires `python-dotenv>=0.15.0,<0.17` (not 1.0+)
- Always check for dependency conflicts when updating packages
- Use pip's dependency resolver output to identify version constraints
- Keep requirements.txt version ranges compatible with all dependencies

## CI/CD
- GitHub Actions builds on push to main and v* tags
- Publishes to ghcr.io/jmorrison-juniper/mistcircuitstats
- Multi-arch builds: linux/amd64, linux/arm64
- Local builds validate before CI/CD runs
