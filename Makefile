# claude_and_goose / claude_and_ollama — Makefile
#
# Local-host workflow for the direct-Ollama runner. No Docker here; the
# runner executes on the host against bazzite.local + the gh CLI.
# Run `make help` to list available targets.

.PHONY: help install-dev \
        format format-check lint check \
        test test-verbose test-file test-name test-cov \
        ci clean

VENV_BIN := runner/.venv/bin

# Terminal colors
BLUE   := \033[0;34m
GREEN  := \033[0;32m
YELLOW := \033[0;33m
RED    := \033[0;31m
NC     := \033[0m

help: ## Show this help message
	@echo "$(BLUE)claude_and_goose$(NC)"
	@echo "================"
	@echo ""
	@echo "$(GREEN)Available commands:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-18s$(NC) %s\n", $$1, $$2}'
	@echo ""

# =============================================================================
# Environment
# =============================================================================

install-dev: ## Create runner/.venv and install runtime + dev dependencies
	@echo "$(BLUE)Creating runner/.venv...$(NC)"
	python3 -m venv runner/.venv
	$(VENV_BIN)/pip install --quiet --upgrade pip
	$(VENV_BIN)/pip install --quiet -r requirements-dev.txt
	@echo "$(GREEN)Dev tools ready — run make check then make test$(NC)"

# =============================================================================
# Code Quality
# =============================================================================

format: ## Apply isort then black to runner/ and tests/
	@test -f $(VENV_BIN)/isort || (echo "$(RED)Run make install-dev first$(NC)" && exit 1)
	@echo "$(BLUE)Formatting with isort...$(NC)"
	$(VENV_BIN)/isort runner tests
	@echo "$(BLUE)Formatting with black...$(NC)"
	$(VENV_BIN)/black runner tests
	@echo "$(GREEN)Formatting complete$(NC)"

format-check: ## Check formatting without modifying files (isort + black --check)
	@test -f $(VENV_BIN)/isort || (echo "$(RED)Run make install-dev first$(NC)" && exit 1)
	@echo "$(BLUE)Checking isort...$(NC)"
	$(VENV_BIN)/isort --check-only runner tests
	@echo "$(BLUE)Checking black...$(NC)"
	$(VENV_BIN)/black --check runner tests
	@echo "$(GREEN)Format check passed$(NC)"

lint: ## Lint runner/ and tests/ with flake8
	@test -f $(VENV_BIN)/flake8 || (echo "$(RED)Run make install-dev first$(NC)" && exit 1)
	@echo "$(BLUE)Running flake8...$(NC)"
	$(VENV_BIN)/flake8 runner tests
	@echo "$(GREEN)Lint complete$(NC)"

check: format-check lint ## Read-only check: format-check + lint (safe for CI / pre-commit)
	@echo "$(GREEN)All checks passed$(NC)"

# =============================================================================
# Tests
# =============================================================================

test: ## Run the test suite
	@test -f $(VENV_BIN)/pytest || (echo "$(RED)Run make install-dev first$(NC)" && exit 1)
	@echo "$(BLUE)Running tests...$(NC)"
	$(VENV_BIN)/pytest
	@echo "$(GREEN)Tests complete$(NC)"

test-verbose: ## Run the test suite with extra verbosity
	@test -f $(VENV_BIN)/pytest || (echo "$(RED)Run make install-dev first$(NC)" && exit 1)
	$(VENV_BIN)/pytest -vv --tb=long

test-file: ## Run a single test file (usage: make test-file FILE=tests/test_run_recipe.py)
ifndef FILE
	@echo "$(RED)Error: FILE not specified$(NC)"
	@echo "Usage: make test-file FILE=tests/test_run_recipe.py"
	@exit 1
endif
	$(VENV_BIN)/pytest $(FILE)

test-name: ## Run a single test by name (usage: make test-name TEST=tests/test_run_recipe.py::test_cap_passes_small_content)
ifndef TEST
	@echo "$(RED)Error: TEST not specified$(NC)"
	@echo "Usage: make test-name TEST=tests/test_run_recipe.py::test_cap_passes_small_content"
	@exit 1
endif
	$(VENV_BIN)/pytest $(TEST)

test-cov: ## Run tests with coverage; HTML report under htmlcov/
	@test -f $(VENV_BIN)/pytest || (echo "$(RED)Run make install-dev first$(NC)" && exit 1)
	@echo "$(BLUE)Running tests with coverage...$(NC)"
	$(VENV_BIN)/pytest --cov --cov-report=term-missing --cov-report=html
	@echo "$(GREEN)Coverage report written to htmlcov/index.html$(NC)"

# =============================================================================
# Full pipeline
# =============================================================================

ci: check test ## Full pre-commit / CI pipeline: check + test
	@echo "$(GREEN)CI passed$(NC)"

# =============================================================================
# Cleanup
# =============================================================================

clean: ## Remove Python caches, .pytest_cache, htmlcov, .coverage
	@echo "$(BLUE)Cleaning up...$(NC)"
	find . -path ./runner/.venv -prune -o -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -path ./runner/.venv -prune -o -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache htmlcov .coverage
	@echo "$(GREEN)Cleanup complete$(NC)"
