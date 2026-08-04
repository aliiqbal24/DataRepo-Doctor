import uvicorn


def run() -> None:
    uvicorn.run("datarepo_doctor.api.app:create_app", factory=True, host="0.0.0.0", port=8000)
