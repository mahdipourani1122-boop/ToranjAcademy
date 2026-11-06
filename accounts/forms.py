from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import User

INPUT_CLASSES = (
    'w-full h-[48px] px-4 rounded-[12px] bg-toranj-inputBg border border-toranj-border '
    'text-toranj-textMain text-[15px] focus:outline-none focus:border-toranj-navy '
    'focus:ring-2 focus:ring-toranj-navy/15 transition-all'
)


class StudentRegistrationForm(forms.ModelForm):
    password = forms.CharField(
        label='رمز عبور',
        widget=forms.PasswordInput(attrs={
            'class': INPUT_CLASSES + ' pl-11',
            'placeholder': 'حداقل ۸ کاراکتر',
            'autocomplete': 'new-password',
            'minlength': '8',
            'required': True,
            'id': 'reg_password',
        })
    )
    confirm_password = forms.CharField(
        label='تکرار رمز عبور',
        widget=forms.PasswordInput(attrs={
            'class': INPUT_CLASSES + ' pl-11',
            'placeholder': 'تکرار رمز عبور',
            'autocomplete': 'new-password',
            'minlength': '8',
            'required': True,
            'id': 'reg_confirm_password',
        })
    )
    accepted_terms = forms.BooleanField(
        label='قوانین و مقررات آموزشی آکادمی زبان تُرنج را مطالعه کرده و می‌پذیرم.',
        required=True,
        error_messages={'required': 'پذیرش قوانین و مقررات آموزشی الزامی است.'},
        widget=forms.CheckboxInput(attrs={
            'class': 'w-4 h-4 rounded border-toranj-border text-toranj-navy focus:ring-toranj-navy'
        })
    )

    class Meta:
        model = User
        # فیلد role یا academy_username هرگز از سمت کلاینت پذیرفته نمی‌شود
        fields = ('first_name', 'last_name', 'phone', 'email', 'accepted_terms')
        widgets = {
            'first_name': forms.TextInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'مثال: علی', 'required': True}),
            'last_name': forms.TextInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'مثال: محمدی', 'required': True}),
            'phone': forms.TextInput(attrs={
                'class': INPUT_CLASSES,
                'placeholder': '09123456789',
                'dir': 'ltr',
                'pattern': '^09[0-9]{9}$',
                'maxlength': '11',
                'required': True,
            }),
            'email': forms.EmailInput(attrs={
                'class': INPUT_CLASSES,
                'placeholder': 'name@example.com (اختیاری)',
                'dir': 'ltr',
                'required': False,
            }),
        }

    def clean_phone(self):
        phone = self.cleaned_data.get('phone', '').strip()
        if not phone.startswith('09') or len(phone) != 11 or not phone.isdigit():
            raise ValidationError('شماره موبایل باید ۱۱ رقم و با ۰۹ شروع شود.')
        if User.objects.filter(phone=phone).exists():
            raise ValidationError('حساب کاربری با این شماره موبایل قبلاً ثبت شده است.')
        return phone

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        if not email:
            return None
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError('حساب کاربری با این آدرس ایمیل قبلاً ثبت شده است.')
        return email

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if password:
            validate_password(password)
        return password

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')
        if password and confirm_password and password != confirm_password:
            self.add_error('confirm_password', 'رمز عبور و تکرار آن با یکدیگر مطابقت ندارند.')
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data.get('email')
        # قوانین قطعی سمت سرور: نقش همیشه student، وضعیت در انتظار تأیید آموزشگاه، بدون ثبت‌نام یا پرداخت خودکار
        user.role = User.Role.STUDENT
        user.status = User.Status.PENDING
        user.academy_username = None
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
            from .models import StudentProfile
            StudentProfile.objects.get_or_create(user=user, defaults={'is_enrolled': False, 'is_paid': False})
        return user


class ToranjLoginForm(forms.Form):
    identifier = forms.CharField(
        label='نام کاربری آکادمی (TRJ-...) یا شماره موبایل',
        widget=forms.TextInput(attrs={
            'class': INPUT_CLASSES,
            'placeholder': 'TRJ-260001 یا 09123456789',
            'dir': 'ltr',
            'autocomplete': 'username',
            'required': True,
        })
    )
    password = forms.CharField(
        label='رمز عبور',
        widget=forms.PasswordInput(attrs={
            'class': INPUT_CLASSES + ' pl-11',
            'placeholder': '••••••••',
            'dir': 'ltr',
            'autocomplete': 'current-password',
            'required': True,
            'id': 'login_password',
        })
    )
    remember_me = forms.BooleanField(
        label='حفظ نشست در این مرورگر',
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'w-4 h-4 rounded border-toranj-border text-toranj-navy focus:ring-toranj-navy'
        })
    )

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        identifier = (cleaned_data.get('identifier') or '').strip()
        password = cleaned_data.get('password')

        if identifier and password:
            self.user_cache = authenticate(self.request, username=identifier, password=password)
            if self.user_cache is None:
                raise ValidationError('اطلاعات ورود (نام کاربری یا رمز عبور) صحیح نمی‌باشد.')
            if not self.user_cache.is_active or self.user_cache.status == User.Status.SUSPENDED:
                raise ValidationError('حساب کاربری شما مسدود یا غیرفعال شده است.')
        return cleaned_data

    def get_user(self):
        return self.user_cache


class TwoFactorVerifyForm(forms.Form):
    METHOD_CHOICES = [
        ('otp', 'کد ۶ رقمی پیامک (SMS OTP)'),
        ('totp', 'اپلیکیشن احراز هویت (Authenticator)'),
        ('recovery', 'کد بازیابی پشتیبان (Recovery Code)'),
    ]
    method = forms.ChoiceField(choices=METHOD_CHOICES, initial='otp', widget=forms.HiddenInput())
    code = forms.CharField(
        label='کد امنیتی',
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': INPUT_CLASSES + ' text-center font-mono tracking-widest text-lg',
            'placeholder': '123456',
            'dir': 'ltr',
            'autocomplete': 'one-time-code',
            'required': True,
        })
    )
    trust_device = forms.BooleanField(
        label='اعتماد به این دستگاه به مدت ۳۰ روز (مخصوص زبان‌آموز)',
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'w-4 h-4 rounded border-toranj-border text-toranj-navy focus:ring-toranj-navy'
        })
    )


class TOTPVerifyActivationForm(forms.Form):
    code = forms.CharField(
        label='کد ۶ رقمی نمایش‌داده‌شده در اپلیکیشن',
        min_length=6,
        max_length=6,
        widget=forms.TextInput(attrs={
            'class': INPUT_CLASSES + ' text-center font-mono tracking-widest text-lg',
            'placeholder': '000000',
            'dir': 'ltr',
            'pattern': '^[0-9]{6}$',
            'required': True,
        })
    )


class TOTPDisableForm(forms.Form):
    current_password = forms.CharField(
        label='رمز عبور فعلی جهت تأیید هویت',
        widget=forms.PasswordInput(attrs={
            'class': INPUT_CLASSES,
            'placeholder': 'رمز عبور فعلی خود را وارد کنید',
            'dir': 'ltr',
            'required': True,
        })
    )


class PasswordChangeSecureForm(forms.Form):
    current_password = forms.CharField(
        label='رمز عبور فعلی',
        widget=forms.PasswordInput(attrs={'class': INPUT_CLASSES + ' pl-11', 'dir': 'ltr', 'id': 'cur_pwd'})
    )
    new_password = forms.CharField(
        label='رمز عبور جدید',
        widget=forms.PasswordInput(attrs={'class': INPUT_CLASSES + ' pl-11', 'dir': 'ltr', 'id': 'new_pwd', 'minlength': '8'})
    )
    confirm_new_password = forms.CharField(
        label='تکرار رمز عبور جدید',
        widget=forms.PasswordInput(attrs={'class': INPUT_CLASSES + ' pl-11', 'dir': 'ltr', 'id': 'conf_pwd', 'minlength': '8'})
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        pwd = self.cleaned_data.get('current_password')
        if not self.user.check_password(pwd):
            raise ValidationError('رمز عبور فعلی صحیح نیست.')
        return pwd

    def clean_new_password(self):
        pwd = self.cleaned_data.get('new_password')
        if pwd:
            validate_password(pwd, self.user)
        return pwd

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get('new_password')
        p2 = cleaned.get('confirm_new_password')
        if p1 and p2 and p1 != p2:
            self.add_error('confirm_new_password', 'رمز عبور جدید و تکرار آن مطابقت ندارند.')
        return cleaned


class ToranjPasswordResetForm(PasswordResetForm):
    email = forms.EmailField(
        label='آدرس ایمیل ثبت‌شده',
        widget=forms.EmailInput(attrs={'class': INPUT_CLASSES, 'placeholder': 'name@example.com', 'dir': 'ltr', 'required': True})
    )


class ToranjSetPasswordForm(SetPasswordForm):
    new_password1 = forms.CharField(
        label='رمز عبور جدید',
        widget=forms.PasswordInput(attrs={'class': INPUT_CLASSES + ' pl-11', 'dir': 'ltr', 'id': 'rst_pwd1', 'required': True})
    )
    new_password2 = forms.CharField(
        label='تکرار رمز عبور جدید',
        widget=forms.PasswordInput(attrs={'class': INPUT_CLASSES + ' pl-11', 'dir': 'ltr', 'id': 'rst_pwd2', 'required': True})
    )