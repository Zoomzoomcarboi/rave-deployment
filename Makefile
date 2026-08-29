.PHONY: install test lint doctor run setup-ui image

install:
	python3 -m pip install -e '.[dev,setup]'

test:
	pytest -q

lint:
	ruff check edge setup-ui tests

doctor:
	rave doctor --config config/rave.toml.example

run:
	rave-edge --config config/rave.toml.example --development-mock

setup-ui:
	uvicorn rave_web.app:app --app-dir setup-ui --host 127.0.0.1 --port 8080

image:
	./scripts/build-rave-os.sh
