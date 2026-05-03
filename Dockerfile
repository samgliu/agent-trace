FROM python:3.13-slim

WORKDIR /app

COPY README.md pyproject.toml ./
COPY agenttrace ./agenttrace
COPY examples ./examples
COPY tests ./tests

RUN python -m pip install --no-cache-dir -e .
RUN python -m unittest discover

ENTRYPOINT ["agenttrace"]
CMD ["--help"]
