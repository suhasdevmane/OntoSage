# OntoSage 2.0 Documentation

Welcome to the documentation for **OntoSage 2.0**, an Agentic AI system for Intelligent Buildings.

## 📚 Documentation Index

- **[Project Structure](PROJECT_STRUCTURE.md)**: Detailed breakdown of folders and files.
- **[Architecture](ARCHITECTURE.md)**: High-level system design, components, and data flow.
- **[Service Catalog](SERVICES.md)**: Responsibilities, ports, dependencies, and interactions.
- **[Configuration](CONFIGURATION.md)**: Environment variables and defaults.
- **[Building Onboarding](BUILDING_ONBOARDING.md)**: Load your own `.ttl` and start chatting.
- **[Deployment Guide](DEPLOYMENT.md)**: Install and run the system.
- **[Operations Runbook](RUNBOOK.md)**: Start/stop, logs, backups, monitoring.
- **[Developer Guide](DEVELOPER_GUIDE.md)**: Extend agents, debug, and test.
- **[User Guide](USER_GUIDE.md)**: Personas, examples, voice, visualization.
- **[Security](SECURITY.md)**: Isolation, secrets, and network guidance.

## 🚀 Quick Links

- **[Root README](../README.md)**: Project overview and quick start.
- **[API Documentation](http://localhost:8000/docs)**: Swagger UI (when running).

## 🛠 Development

For developers contributing to the project:

1.  **Python Setup**: Ensure Python 3.11+ is installed.
2.  **Dependencies**: Each service has its own `requirements.txt` or `pyproject.toml`.
3.  **Testing**: Run tests using `pytest` in the `tests/` directory.
4.  **Compose**: Use `docker-compose -f docker-compose.agentic.yml up -d` for a full stack.

## 🤝 Support

For issues or questions, please check the existing documentation or open an issue in the repository.
