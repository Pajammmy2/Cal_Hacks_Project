"""python -m ember_staff  ->  http://127.0.0.1:8100 (localhost only; the data never leaves this laptop)."""
import os

import uvicorn


def main():
    port = int(os.environ.get("EMBER_STAFF_PORT", "8100"))
    uvicorn.run("ember_staff.app:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()
