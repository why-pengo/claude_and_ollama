# claude_and_ollama — Makefile
#
# Local-host workflow for the direct-Ollama runner. No Docker here; the
# runner executes on the host against bazzite.local + the gh CLI.
# Run `make help` to list available targets.

.PHONY: help install-dev \
        format format-check lint typecheck check audit \
        test test-verbose test-file test-name test-cov \
        ci clean

VENV_BIN := runner/.venv/bin

# Terminal colors — emitted via printf so escape sequences render
# deterministically regardless of /bin/sh's echo flavour.
BLUE   := \033[0;34m
GREEN  := \033[0;32m
YELLOW := \033[0;33m
RED    := \033[0;31m
NC     := \033[0m

# Reused guard for targets that require the dev venv. Uses printf so the
# error renders in red on any shell.
VENV_CHECK = @test -f $(VENV_BIN)/pytest || \
    (printf "$(RED)Run make install-dev first$(NC)\n" && exit 1)

help: ## Show this help message
	@printf "$(BLUE)claude_and_ollama$(NC)\n"
	@printf "================\n\n"
	@printf "$(GREEN)Available commands:$(NC)\n"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  $(YELLOW)%-18s$(NC) %s\n", $$1, $$2}'
	@printf "\n"

# =============================================================================
# Environment
# =============================================================================

install-dev: ## Create runner/.venv and install runtime + dev dependencies
	@printf "$(BLUE)Creating runner/.venv...$(NC)\n"
	python3 -m venv runner/.venv
	$(VENV_BIN)/pip install --quiet --upgrade pip
	$(VENV_BIN)/pip install --quiet -r requirements-dev.txt
	@printf "$(GREEN)Dev tools ready — run make check then make test$(NC)\n"

# =============================================================================
# Code Quality
# =============================================================================

format: ## Apply isort then black to runner/ and tests/
	$(VENV_CHECK)
	@printf "$(BLUE)Formatting with isort...$(NC)\n"
	$(VENV_BIN)/isort runner tests
	@printf "$(BLUE)Formatting with black...$(NC)\n"
	$(VENV_BIN)/black runner tests
	@printf "$(GREEN)Formatting complete$(NC)\n"

format-check: ## Check formatting without modifying files (isort + black --check)
	$(VENV_CHECK)
	@printf "$(BLUE)Checking isort...$(NC)\n"
	$(VENV_BIN)/isort --check-only runner tests
	@printf "$(BLUE)Checking black...$(NC)\n"
	$(VENV_BIN)/black --check runner tests
	@printf "$(GREEN)Format check passed$(NC)\n"

lint: ## Lint runner/ and tests/ with flake8
	$(VENV_CHECK)
	@printf "$(BLUE)Running flake8...$(NC)\n"
	$(VENV_BIN)/flake8 runner tests
	@printf "$(GREEN)Lint complete$(NC)\n"

typecheck: ## Static type check with mypy (runner/ and tests/ per pyproject config)
	$(VENV_CHECK)
	@printf "$(BLUE)Running mypy...$(NC)\n"
	$(VENV_BIN)/mypy
	@printf "$(GREEN)Typecheck complete$(NC)\n"

check: format-check lint typecheck ## Read-only check: format-check + lint + typecheck (safe for CI / pre-commit)
	@printf "$(GREEN)All checks passed$(NC)\n"

audit: ## Audit installed dependencies for known CVEs (needs network; CI runs it after make ci)
	$(VENV_CHECK)
	@printf "$(BLUE)Running pip-audit...$(NC)\n"
	$(VENV_BIN)/pip-audit
	@printf "$(GREEN)No known vulnerabilities$(NC)\n"

# =============================================================================
# Tests
# =============================================================================

test: ## Run the test suite
	$(VENV_CHECK)
	@printf "$(BLUE)Running tests...$(NC)\n"
	$(VENV_BIN)/pytest
	@printf "$(GREEN)Tests complete$(NC)\n"

test-verbose: ## Run the test suite with extra verbosity
	$(VENV_CHECK)
	$(VENV_BIN)/pytest -vv --tb=long

test-file: ## Run a single test file (usage: make test-file FILE=tests/test_run_recipe.py)
ifndef FILE
	@printf "$(RED)Error: FILE not specified$(NC)\n"
	@printf "Usage: make test-file FILE=tests/test_run_recipe.py\n"
	@exit 1
endif
	$(VENV_CHECK)
	$(VENV_BIN)/pytest $(FILE)

test-name: ## Run a single test by name (usage: make test-name TEST=tests/test_run_recipe.py::test_cap_passes_small_content)
ifndef TEST
	@printf "$(RED)Error: TEST not specified$(NC)\n"
	@printf "Usage: make test-name TEST=tests/test_run_recipe.py::test_cap_passes_small_content\n"
	@exit 1
endif
	$(VENV_CHECK)
	$(VENV_BIN)/pytest $(TEST)

test-cov: ## Run tests with coverage; HTML report under htmlcov/
	$(VENV_CHECK)
	@printf "$(BLUE)Running tests with coverage...$(NC)\n"
	$(VENV_BIN)/pytest --cov --cov-report=term-missing --cov-report=html
	@printf "$(GREEN)Coverage report written to htmlcov/index.html$(NC)\n"

# =============================================================================
# Full pipeline
# =============================================================================

ci: check test ## Full pre-commit / CI pipeline: check + test
	@printf "$(GREEN)CI passed$(NC)\n"

# =============================================================================
# Cleanup
# =============================================================================

clean: ## Remove Python caches, .pytest_cache, htmlcov, .coverage
	@printf "$(BLUE)Cleaning up...$(NC)\n"
	find . -path ./runner/.venv -prune -o -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -path ./runner/.venv -prune -o -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache htmlcov .coverage
	@printf "$(GREEN)Cleanup complete$(NC)\n"
