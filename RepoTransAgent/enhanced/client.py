"""OpenAI-compatible model client with bounded transport retries."""

import json
import logging
import os
import time
from datetime import datetime

import requests

logger = logging.getLogger(__name__)


class Generator:
    def __init__(self, args, logger=None, system_prompt=""):
        self.logger = logger or logging.getLogger(__name__)
        self.args = args
        self.model_name = args.model_name
        self.system_prompt = system_prompt
        self.load_config()
        self.init_conversation()

    def load_config(self):
        self.api_key = os.environ.get("REPOTRANS_API_KEY", "")
        self.base_url = os.environ.get("REPOTRANS_BASE_URL", "https://api.openai.com/v1").rstrip(
            "/"
        )
        if not self.api_key:
            raise RuntimeError("REPOTRANS_API_KEY is not set")
        self.max_retries = int(os.environ.get("REPOTRANS_MAX_RETRIES", "2"))
        if self.max_retries < 0:
            raise ValueError("REPOTRANS_MAX_RETRIES must be nonnegative")
        self.log_dir = self.args.artifacts_dir / "conversation_logs"

    def init_conversation(self, repo_path=None):
        self.messages = [
            {"role": "system", "content": [{"type": "text", "text": self.system_prompt}]}
        ]

    def clean_conversation(self):
        self.messages = []

    def slide_window_conversation(self):
        if len(self.messages) > 2:
            self.messages = self.messages[:1] + self.messages[-2:]

    def get_response(self, repo_name, history_conversation=None):
        if history_conversation:
            self.messages = history_conversation
        data = {"model": self.model_name, "messages": self.messages}
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "RepoTransBench-baseline/1.0",
            "Content-Type": "application/json",
        }
        for attempt in range(self.max_retries + 1):
            try:
                self.logger.info("Calling model endpoint %s/chat/completions", self.base_url)
                response = requests.post(
                    f"{self.base_url}/chat/completions", json=data, headers=headers, timeout=180
                )
                response.raise_for_status()
                body = response.json()
                content = body["choices"][0]["message"]["content"]
                self.record_conversation(self.model_name, self.messages, body, repo_name)
                self.messages.append(
                    {"role": "assistant", "content": [{"type": "text", "text": content}]}
                )
                return content
            except requests.exceptions.Timeout:
                detail = "[Requests Timeout]"
                self.logger.warning("Model request timed out (attempt %d)", attempt + 1)
            except requests.exceptions.RequestException as exc:
                detail = "[Requests Exception]"
                self.logger.warning(
                    "Model request failed (attempt %d): %s",
                    attempt + 1,
                    str(exc).replace(self.api_key, "[REDACTED]"),
                )
                if exc.response is not None and exc.response.status_code in {
                    400,
                    401,
                    402,
                    403,
                    404,
                }:
                    self.record_conversation(
                        self.model_name,
                        self.messages,
                        {"transport_error": True, "http_status": exc.response.status_code},
                        repo_name,
                    )
                    raise RuntimeError(
                        f"Model transport unavailable: HTTP {exc.response.status_code}"
                    ) from None
            except (KeyError, ValueError, TypeError) as exc:
                detail = "[Invalid model response]"
                self.logger.warning("Invalid model response (attempt %d): %s", attempt + 1, exc)
            except Exception as exc:
                detail = "[Request handling exception]"
                self.logger.warning(
                    "Request handling failed (attempt %d): %s",
                    attempt + 1,
                    str(exc).replace(self.api_key, "[REDACTED]"),
                )
            self.record_conversation(self.model_name, self.messages, detail, repo_name)
            if attempt < self.max_retries:
                time.sleep(5)
        # A transport outage is an incomplete experiment. Do not feed a fake
        # "invalid action" into the upstream loop and repeat failed requests
        # for every remaining agent iteration.
        raise RuntimeError("Model transport unavailable after bounded retries")

    def record_conversation(self, model_name, messages, response, repo_name=None):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.log_dir / f'{repo_name or "logs"}.json'
        conversation_data = {
            "model_name": model_name,
            "messages": messages,
            "response": response,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(log_path, "a", encoding="utf-8") as file:
            json.dump(conversation_data, file, ensure_ascii=False, indent=2)
            file.write("\n")
