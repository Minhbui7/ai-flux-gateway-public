import json

import azure.functions as func
from aiflux.ingestion import main
from runtime_check import verify_runtime


def ingest_usage(timer: func.TimerRequest) -> None:
    main()


def ingestion_ready(request: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(verify_runtime(request.params.get("subscription_id"))),
        mimetype="application/json",
        headers={"Cache-Control": "no-store"},
    )
