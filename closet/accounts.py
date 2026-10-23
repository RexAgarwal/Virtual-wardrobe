from django import forms
from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.shortcuts import redirect, render


class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=False, help_text='Optional')
    invite = forms.CharField(required=False, label='Invite code')

    class Meta:
        model = User
        fields = ('username', 'email')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not settings.WARDROBE_INVITE_CODE:
            del self.fields['invite']

    def clean_invite(self):
        import hmac
        given = self.cleaned_data['invite'].strip()
        if not hmac.compare_digest(given.encode(), settings.WARDROBE_INVITE_CODE.encode()):
            raise forms.ValidationError('That invite code is not right.')
        return given


@login_not_required
def signup(request):
    if request.user.is_authenticated:
        return redirect('closet:item_list')
    form = SignUpForm(request.POST or None)
    if form.is_valid():
        user = form.save()
        login(request, user)
        return redirect('closet:item_list')
    return render(request, 'registration/signup.html', {'form': form})
