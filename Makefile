.PHONY: setup data train eval optimize explain report render cv demo test lint format schema clean

setup:
	python -m pip install -e ".[dev,api,cv]"

data:
	python -m plant.generate --config config/facility.yaml --scenario S1 --seed 42

train:
	python -m analytics.train --input data/generated --output models/analytics.joblib --config config/facility.yaml

eval:
	python -m eval.run --input data/generated --output reports/analytics --config config/facility.yaml

optimize:
	python -m policies.optimize --input data/generated --output reports/optimizer/recommendations.json

explain:
	python -m genai.cli --input reports/optimizer/recommendations.json --output reports/optimizer/explanations.json

report:
	python -m genai.report reports/analytics/analytics_report.json --output reports/end_of_day.md

render:
	python -m renderer.generate

cv:
	python -m cv.ingest_clips --manifest data/clips/manifest.csv

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

