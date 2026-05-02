FROM python:3.13-slim

WORKDIR /app

COPY README.md pyproject.toml ./
COPY agenttrace ./agenttrace
COPY examples ./examples
COPY tests ./tests

RUN python -m unittest discover

ENTRYPOINT ["python", "-m", "agenttrace.cli"]
CMD ["--help"]
