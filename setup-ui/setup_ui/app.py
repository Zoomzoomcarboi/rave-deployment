from fastapi import FastAPI

app = FastAPI(title="RAVE Setup", version="0.0.1")


@app.get("/")
def index() -> dict:
    return {
        "product": "RAVE Rear Awareness Vision Engine",
        "status": "architecture prototype",
        "warning": "No real camera, Hailo, pairing, or vehicle integration is active.",
    }


@app.get("/api/health")
def health() -> dict:
    return {
        "camera": "not_implemented",
        "accelerator": "not_implemented",
        "model": "mock",
        "comma": "not_paired",
        "ready": False,
    }
