import os
import json
import logging
from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic import BaseModel

load_dotenv()

def get_providers():
    return [
        {
            "name": "OmniRoute",
            "base_url": os.getenv("OMNIROUTE_BASE_URL", "http://127.0.0"),
            "api_key": os.getenv("OMNIROUTE_API_KEY"),
            "model": "auto"
        },
        {
            "name": "Groq",
            "base_url": "https://groq.com",
            "api_key": os.getenv("GROQ_API_KEY"),
            "model": "llama-3.3-70b-versatile"
        },
        {
            "name": "OpenRouter",
            "base_url": "https://openrouter.ai",
            "api_key": os.getenv("OPENROUTER_API_KEY"),
            "model": "meta-llama/llama-3.3-70b-instruct:free"
        },
        {
            "name": "DeepSeek",
            "base_url": "https://deepseek.com",
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "model": "deepseek-chat"
        }
    ]

class AssistantResponse(BaseModel):
    action: str = "chat"  # "create_task" | "complete_task" | "chat"
    task_title: str | None = None
    due_time: str | None = None
    reply_text: str

async def call_llm_raw(system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
    providers = get_providers()
    for prov in providers:
        if not prov["api_key"]:
            continue
        try:
            client = AsyncOpenAI(
                api_key=prov["api_key"],
                base_url=prov["base_url"],
                timeout=20.0
            )
            kwargs = {
                "model": prov["model"],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.3
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            resp = await client.chat.completions.create(**kwargs)
            content = resp.choices[0].message.content
            if content:
                return content
        except Exception as e:
            logging.warning(f"[AI Chain] Провайдер {prov['name']} не ответил: {e}. Переключаюсь на следующий...")
            continue

    raise RuntimeError("Все API-провайдеры в цепочке недоступны.")

def build_user_context(user) -> str:
    return (
        f"Имя пользователя: {user['name']}\n"
        f"Компания: {user['company_name']}\n"
        f"Продукт/деятельность: {user['company_product']}\n"
        f"Дополнительные сведения от пользователя: {user['extra_info']}"
    )

async def process_owner_message(user, text: str) -> AssistantResponse:
    system_prompt = f"""
Ты — персональный ИИ-бизнес-ассистент.
Контекст владельца:
{build_user_context(user)}

Проанализируй сообщение пользователя:
1. Если он просит напомнить или запланировать дело (например, "напомни утром позвонить Ивану и предложить такие-то условия") -> установи "action": "create_task", запиши суть в "task_title", а время в "due_time".
2. Если он сообщает, что выполнил задачу или решил проблему за день (например, "я позвонил Ивану, договорились" или "закрыл сделку с клиентом") -> установи "action": "complete_task", запиши что именно сделано в "task_title".
3. Если это обычный вопрос или диалог -> установи "action": "chat".

ОТВЕТЬ СТРОГО В ФОРМАТЕ ЧИСТОГО JSON:
{{
  "action": "create_task" | "complete_task" | "chat",
  "task_title": "описание задачи или выполненного дела (или null)",
  "due_time": "срок/время (или null)",
  "reply_text": "твой ответ пользователю с учетом контекста его компании"
}}
"""
    try:
        raw = await call_llm_raw(system_prompt, text, json_mode=True)
        clean_json = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(clean_json)
        return AssistantResponse(**data)
    except Exception:
        # Если модель не вернула JSON, возвращаем обычный текстовый ответ
        try:
            fallback_text = await call_llm_raw(f"Ты бизнес-ассистент.\n{build_user_context(user)}", text, json_mode=False)
            return AssistantResponse(action="chat", reply_text=fallback_text)
        except Exception:
            return AssistantResponse(
                action="chat",
                reply_text="⚠️ Все подключенные AI-провайдеры сейчас перегружены. Попробуйте через минуту."
            )

async def generate_reply_advice(user, source_name: str, sender: str, incoming_text: str) -> str:
    system_prompt = f"""
Ты — советник по переговорам и коммуникациям руководителя.
Данные о руководителе и его бизнесе:
{build_user_context(user)}

Руководителю пришло новое входящее сообщение ({source_name}) от: {sender}.
Задача:
1. Кратко оцени суть обращения.
2. Предложи 1–2 готовых текста ответа, которые руководитель может сразу скопировать и отправить, с учетом специфики его компании и дополнительных сведений.
"""
    try:
        return await call_llm_raw(system_prompt, f"Текст входящего сообщения:\n{incoming_text}", json_mode=False)
    except Exception:
        return "⚠️ Не удалось сгенерировать совет ответа (AI-провайдеры временно недоступны)."
