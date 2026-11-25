# Multi-AI Dashboard — build, run, test
PY      ?= python3
UVICORN ?= $(PY) -m uvicorn
ROOT    := $(shell pwd)

.PHONY: all build run dev stop test clean install

all: build run

build: ## Build the C++ layer (hwmon + sandbox_exec)
	cmake -S cpp -B cpp/build -DCMAKE_BUILD_TYPE=Release
	cmake --build cpp/build -j"$$(nproc)"

install: ## Install Python dependencies
	$(PY) -m pip install -r backend/requirements.txt

run: build ## Production server (single worker, reload off)
	cd backend && $(UVICORN) app.main:app --host 127.0.0.1 --port 8000

dev: build ## Dev server with auto-reload
	cd backend && $(UVICORN) app.main:app --host 0.0.0.0 --port 8000 --reload

stop: ## Stop a running server on :8000
	-pkill -f "uvicorn app.main:app" || true

test: ## Smoke-test the API
	@curl -sf localhost:8000/api/health | python3 -m json.tool
	@curl -sf localhost:8000/api/status | python3 -c "import json,sys; d=json.load(sys.stdin); print('ollama:', d['ollama']['running'], '| online:', d['online'])"

clean: ## Remove build artifacts (keeps data/workspace)
	rm -rf cpp/build
	find backend -type d -name __pycache__ -exec rm -rf {} +
