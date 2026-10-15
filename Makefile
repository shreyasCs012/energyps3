.PHONY: setup data train eval demo test lint format schema clean

setup:
	python -m pip install -e ".[dev,api]"

data:
	python -m plant.generate --config config/facility.yaml --scenario S1 --seed 42

train:
	python -m analytics.train --input data/generated --output models/analytics.joblib --config config/facility.yaml

eval:
	python -m eval.run --input data/generated --output reports/analytics --config config/facility.yaml

demo:
	python -m api.app

test:
	python -m pytest

lint:
	python -m ruff check .

format:
	python -m ruff format .

schema:
	python -m contracts.export_schema

clean:
	python -c "from pathlib import Path; import shutil; [shutil.rmtree(p) for p in (Path('.pytest_cache'), Path('.ruff_cache'), Path('demo_cache')) if p.exists()]"

