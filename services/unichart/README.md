# UniChart service

Reads a chart image into a text data table with [UniChart](https://github.com/vis-nlp/UniChart)
(MIT licence; weights `ahmed-masry/unichart-base-960`). The backend calls it when
`UNICHART_URL` is set; with it unset the backend falls back to the AI model, which needs the
person's agreement.

## Why it is separate
UniChart needs `transformers==4.28.1` and torch, and runs best on its own Python 3.10. Keeping it
out of the Flask backend keeps those pins out of the backend's environment.

## Run locally
```bash
python3.10 -m venv .venv-unichart && . .venv-unichart/bin/activate
pip install -r requirements.txt
UNICHART_ALLOW_NO_TOKEN=1 python app.py        # http://127.0.0.1:5060
```
Then in the backend `.env`: `UNICHART_URL=http://127.0.0.1:5060`.

## Run as a container
```bash
docker build -t unichart-service .
docker run -p 8080:8080 -e UNICHART_TOKEN=<long random string> unichart-service
```
Set the same `UNICHART_TOKEN` in the backend; it is sent as `X-Service-Token`. Do not expose this
service to the internet: only the backend should reach it.

## Measured (40 real ChartQA charts + 15 synthetic, CPU on a laptop)
- About 8 s per chart; ~46 s to load the model; 202M parameters.
- Single-series charts: about as accurate as the AI model (95% vs 97% of cells within 5%).
- Several series: 56% vs 85%. Pies: failed. The backend escalates those to the AI model only when
  the person has agreed to it.

## Not covered
- No GPU configuration. CPU latency on a small Cloud Run instance has not been measured.
- The service does not classify chart type; the backend suggests one from the table.
