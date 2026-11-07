import asyncio
import imaplib
import email
from email.header import decode_header
import logging
from aiogram import Bot
import database as db
from ai_chain import generate_reply_advice

def decode_mime_words(s):
    if not s:
        return ""
    decoded_fragments = decode_header(s)
    result = []
    for frag, encoding in decoded_fragments:
        if isinstance(frag, bytes):
            result.append(frag.decode(encoding or "utf-8", errors="ignore"))
        else:
            result.append(frag)
    return "".join(result)

def fetch_unseen_emails_sync(imap_server: str, login: str, password: str):
    messages_data = []
    try:
        mail = imaplib.IMAP4_SSL(imap_server, timeout=15)
        mail.login(login, password)
        mail.select("INBOX")
        status, response = mail.search(None, "UNSEEN")
        if status != "OK":
            mail.logout()
            return messages_data

        email_ids = response[0].split()
        # Берем максимум 3 новых письма за раз, чтобы не перегрузить чат
        for e_id in email_ids[-3:]:
            res, msg_data = mail.fetch(e_id, "(RFC822)")
            if res != "OK":
                continue
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    subject = decode_mime_words(msg.get("Subject", "Без темы"))
                    sender = decode_mime_words(msg.get("From", "Неизвестный"))
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition")):
                                payload = part.get_payload(decode=True)
                                if payload:
                                    body = payload.decode(errors="ignore")
                                    break
                    else:
                        payload = msg.get_payload(decode=True)
                        if payload:
                            body = payload.decode(errors="ignore")

                    messages_data.append({
                        "sender": sender,
                        "subject": subject,
                        "body": body.strip()[:1200]
                    })
        mail.logout()
    except Exception as e:
        logging.warning(f"[Email Worker] Ошибка проверки почты {login}: {e}")
    return messages_data

async def check_all_users_email(bot: Bot):
    users = await db.get_all_users()
    for u in users:
        if not u["imap_server"] or not u["email_login"] or not u["email_password"]:
            continue

        new_emails = await asyncio.to_thread(
            fetch_unseen_emails_sync,
            u["imap_server"],
            u["email_login"],
            u["email_password"]
        )

        for mail_item in new_emails:
            full_text = f"Тема: {mail_item['subject']}\nТекст: {mail_item['body']}"
            advice = await generate_reply_advice(
                user=u,
                source_name="Электронная почта (Email)",
                sender=mail_item["sender"],
                incoming_text=full_text
            )
            notification = (
                f"📧 <b>Новое письмо на почту!</b>\n"
                f"<b>От кого:</b> {mail_item['sender']}\n"
                f"<b>Тема:</b> {mail_item['subject']}\n\n"
                f"<b>Текст письма:</b>\n<i>{mail_item['body']}</i>\n\n"
                f"💡 <b>Совет ИИ по ответу:</b>\n{advice}"
            )
            try:
                await bot.send_message(u["user_id"], notification, parse_mode="HTML")
            except Exception as e:
                logging.error(f"Не удалось отправить уведомление юзеру {u['user_id']}: {e}")
