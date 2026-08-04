.PHONY: install test lint doctor run setup-ui package image

install:
	python3 -m pip install -e '.[dev,setup]'

test:
	pytest -q

lint:
	ruff check edge tests

doctor:
	rave doctor --config config/rave.toml.example

run:
	rave-edge --config config/rave.toml.example

setup-ui:
	uvicorn setup_ui.app:app --app-dir setup-ui --host 0.0.0.0 --port 8080

package:
	@echo "TODO: invoke Debian package build"

image:
	@echo "TODO: invoke pinned rpi-image-gen container/toolchain"
