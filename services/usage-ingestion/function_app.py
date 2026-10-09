import azure.functions as func

from aiflux.ingestion import main

app = func.FunctionApp()


@app.timer_trigger(schedule="0 */5 * * * *", arg_name="timer", run_on_startup=False, use_monitor=True)
def ingest_usage(timer: func.TimerRequest) -> None:
    main()
