import requests
import uuid
from typing import Optional


class GigaChatAuth:
    def __init__(self, auth_token: str):
        self.auth_token = auth_token
        self.access_token: Optional[str] = None

    def get_new_token(self) -> bool:

        url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": str(uuid.uuid4()),
            "Authorization": f"Basic {self.auth_token}"
        }

        payload = {
            "scope": "GIGACHAT_API_PERS"
        }

        try:
            response = requests.post(url, headers=headers, data=payload, verify=False)

            if response.status_code == 200:
                self.access_token = response.json().get("access_token")
                print("Токен есть")
                return True
            else:
                print(f"Ошибка авторизации: {response.status_code}")
                return False

        except requests.RequestException as e:
            print(f"Ошибка подключения: {e}")
            return False