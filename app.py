"""Start the Smart Network Diagnosis web application."""

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "api.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )


if __name__ == "__main__":
    main()
