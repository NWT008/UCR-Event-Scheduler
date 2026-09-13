.PHONY: generate-traces grade generate-description-traces grade-description test lint

generate-traces:
	uv run python tests/eval/generate_traces.py

grade:
	agents-cli eval grade --traces artifacts/traces/generated_traces.json --config tests/eval/eval_config.yaml

generate-description-traces:
	uv run python tests/eval/generate_description_traces.py

grade-description:
	agents-cli eval grade --traces artifacts/traces/description_traces.json --config tests/eval/description_eval_config.yaml

test:
	uv run pytest tests/

lint:
	agents-cli lint
