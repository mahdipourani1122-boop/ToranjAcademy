import json
from urllib import request as urllib_request
from urllib.parse import urlencode
from urllib.error import URLError
from django.conf import settings


class SMSProviderNotConfiguredError(Exception):
    """زمانی رخ می‌دهد که کلیدهای درگاه پیامک در فایل .env تنظیم نشده باشند."""


class SMSDeliveryError(Exception):
    """زمانی رخ می‌دهد که سرویس‌دهنده پیامک پاسخ خطا برگرداند."""


def send_sms_otp_via_provider(phone: str, otp_code: str) -> bool:
    """
    ارسال کد یک‌بارمصرف از طریق سرویس‌دهنده واقعی (کاوه‌نگار، ملی‌پیامک یا وب‌هوک استاندارد).
    قانون امنیتی: مقدار otp_code هرگز در لاگ‌ها یا خروجی خطا چاپ نمی‌شود.
    """
    provider = getattr(settings, 'SMS_PROVIDER', '')
    api_key = getattr(settings, 'SMS_API_KEY', '')

    if not provider or not api_key:
        raise SMSProviderNotConfiguredError(
            'تنظیمات درگاه پیامک (SMS_PROVIDER و SMS_API_KEY) در متغیرهای محیطی سرور مقداردهی نشده است.'
        )

    try:
        if provider == 'kavenegar':
            template = getattr(settings, 'SMS_OTP_TEMPLATE', 'toranj-otp')
            url = f"https://api.kavenegar.com/v1/{api_key}/verify/lookup.json"
            data = urlencode({'receptor': phone, 'token': otp_code, 'template': template}).encode('utf-8')
            req = urllib_request.Request(url, data=data, method='POST')
            with urllib_request.urlopen(req, timeout=8) as resp:
                return resp.status == 200

        elif provider == ' webhook' or provider == 'webhook':
            webhook_url = getattr(settings, 'SMS_WEBHOOK_URL', '')
            if not webhook_url:
                raise SMSProviderNotConfiguredError('آدرس SMS_WEBHOOK_URL تنظیم نشده است.')
            payload = json.dumps({
                'to': phone,
                'sender': getattr(settings, 'SMS_SENDER_NUMBER', ''),
                'code': otp_code,
            }).encode('utf-8')
            req = urllib_request.Request(
                webhook_url,
                data=payload,
                headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
                method='POST'
            )
            with urllib_request.urlopen(req, timeout=8) as resp:
                return 200 <= resp.status < 300

        elif provider == 'melipayamak':
            url = 'https://rest.payamak-panel.com/api/SendSMS/SendSMS'
            payload = json.dumps({
                'username': getattr(settings, 'SMS_SENDER_NUMBER', ''),
                'password': api_key,
                'to': phone,
                'from': getattr(settings, 'SMS_SENDER_NUMBER', ''),
                'text': f"آکادمی زبان ترنج\nکد تأیید امنیتی شما: {otp_code}",
            }).encode('utf-8')
            req = urllib_request.Request(url, data=payload, headers={'Content-Type': 'application/json'}, method='POST')
            with urllib_request.urlopen(req, timeout=8) as resp:
                return 200 <= resp.status < 300

        else:
            raise SMSProviderNotConfiguredError(f'سرویس‌دهنده پیامک «{provider}» پشتیبانی نمی‌شود.')

    except URLError as exc:
        raise SMSDeliveryError('عدم برقراری ارتباط با درگاه پیامک. لطفاً دقایقی دیگر تلاش کنید.') from exc