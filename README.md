```markdown
# Diabetes Treatment Recommender — Expert System

Short description
This repository contains the codebase and documentation for an expert-system-based diabetes treatment recommendation project. It is intended for research and development; NOT for clinical deployment without validation, approvals, and a clinical safety plan.

Quick start (local, development)
Prerequisites:
- Python 3.10+
- Git
- Docker (optional)

Setup:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
```

Project layout
- src/recommender: core expert-system code
- notebooks: exploratory analyses and examples (do not put PHI here)
- models: trained artifacts (store off-repo)
- data: raw/processed (do not commit PHI or raw data)

Important notes
- Do not commit patient data, PHI, or secrets into this repository.
- This software is research code and not verified for clinical use. See SECURITY.md and docs/ for privacy and governance guidance.

Contributing
Read CONTRIBUTING.md for how to contribute and the code of conduct.

License
This project is licensed under the MIT License — see LICENSE.
```
