# Assumptions and implementation decisions

- The GitHub repository was empty at project start; Phase 0 establishes the package and directory structure from scratch.
- The supplied machine, tariff, weather, and emissions values are treated as configurable synthetic placeholders, not validated industrial measurements or cited live tariffs.
- Python 3.11 is the project baseline. Frontend and optional model dependencies will be introduced in the phases that use them.
- Generated datasets and local secrets are excluded from version control. Reproducible seeds and artifact manifests will be added with data generation.
- Phase checkpoints are applied in the order requested by the master spec. The current checkpoint is Phase 0.

