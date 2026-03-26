import requests
import json
import uuid
from datetime import datetime
from connect import GigaChatAuth
import urllib3

urllib3.disable_warnings()


class GigaChatClient:
    def __init__(self, auth: GigaChatAuth, system_prompt: str = ""):
        self.auth = auth
        self.system_prompt = system_prompt
        self.history = []
        self.history_file = "chat_history.json"

    def send_message(self, message: str) -> dict:
        if not self.auth.access_token:
            print("Токен недействителен.")
            return {"error": "Нет токена"}

        url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.auth.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Session-ID": str(uuid.uuid4())
        }

        payload = {
            "model": "GigaChat-2",
            "messages": self._build_messages(message),
            "temperature": 0.7
        }

        try:
            response = requests.post(
                url,
                headers=headers,
                data=json.dumps(payload),
                verify=False
            )

            if response.status_code != 200:
                return {"error": response.status_code}

            result = response.json()
            content = result["choices"][0]["message"]["content"]
            usage = result.get("usage", {})

            record = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "user_message": message,
                "assistant_response": content,
                "tokens": {
                    "prompt": usage.get("prompt_tokens", 0),
                    "completion": usage.get("completion_tokens", 0),
                    "total": usage.get("total_tokens", 0)
                }
            }

            self.history.append(record)
            self._save_history()

            return record

        except requests.RequestException as e:
            return {"error": str(e)}

    def _build_messages(self, new_message: str):
        messages = []

        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})

        for item in self.history[-10:]:
            messages.append({"role": "user", "content": item["user_message"]})
            messages.append({"role": "assistant", "content": item["assistant_response"]})

        messages.append({"role": "user", "content": new_message})
        return messages

    def _save_history(self):
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self.history, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Ошибка сохранения истории: {e}")


def main():
    AUTH_KEY = "MDE5ZDAwYWMtMGQ3Yi03MGY1LWI3ZDUtNzc2NmY0ZTQxMGI0OmU4ZTczNTcxLTNjNTItNDkwNS1hZjdlLTFlOWYxMDZiYWRhYQ=="

    SYSTEM_PROMPT = """
Ты живёшь в деревне и говоришь очень глупо. 
Отвечай на всё максимально простыми словами.
"""

    auth = GigaChatAuth(AUTH_KEY)

    if not auth.get_new_token():
        print("Не удалось получить токен")
        return

    client = GigaChatClient(auth, SYSTEM_PROMPT)

    print("\nЧат с GigaChat (введи 'exit' для выхода)\n")

    while True:
        user_input = input("Ты: ")

        if user_input.lower() in ["exit", "выход"]:

            break

        result = client.send_message(user_input)

        if "error" in result:
            print(f"Ошибка: {result['error']}\n")
            continue

        print(f"GigaChat: {result['assistant_response']}")
        print(f"Токены: {result['tokens']}\n")


if __name__ == "__main__":
    main()