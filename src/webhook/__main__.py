import logging
import uvicorn

import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("src.webhook.server:app", host="0.0.0.0", port=port, reload=False)
