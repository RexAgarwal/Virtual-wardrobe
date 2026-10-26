from django import forms

from .models import Item, Outfit, Perfume, Trip, WatchItem


class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ['name', 'photo', 'category', 'color', 'season', 'formality',
                  'brand', 'price', 'tags', 'status', 'notes']
        widgets = {
            'formality': forms.NumberInput(attrs={'type': 'range', 'min': 1, 'max': 5}),
            'notes': forms.Textarea(attrs={'rows': 3}),
            'photo': forms.ClearableFileInput(attrs={'accept': 'image/*', 'capture': 'environment'}),
        }


class OutfitForm(forms.ModelForm):
    items = forms.ModelMultipleChoiceField(
        queryset=Item.objects.exclude(status=Item.Status.GONE),
        widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['items'].queryset = user.items.exclude(status=Item.Status.GONE)

    class Meta:
        model = Outfit
        fields = ['name', 'occasion', 'items', 'notes']
        widgets = {'notes': forms.Textarea(attrs={'rows': 3})}


class TripForm(forms.ModelForm):
    items = forms.ModelMultipleChoiceField(
        queryset=Item.objects.exclude(status=Item.Status.GONE),
        widget=forms.CheckboxSelectMultiple, required=False)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['items'].queryset = user.items.exclude(status=Item.Status.GONE)

    class Meta:
        model = Trip
        fields = ['name', 'destination', 'start', 'end']
        widgets = {
            'start': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'end': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }

    def clean(self):
        data = super().clean()
        if data.get('start') and data.get('end') and data['end'] < data['start']:
            self.add_error('end', 'Return date is before the departure date.')
        return data


class PerfumeForm(forms.ModelForm):
    class Meta:
        model = Perfume
        fields = ['name', 'brand', 'photo', 'concentration', 'family', 'notes', 'season', 'occasion',
                  'size_ml', 'price', 'rating', 'status', 'comments']
        widgets = {
            'rating': forms.NumberInput(attrs={'type': 'range', 'min': 0, 'max': 5}),
            'comments': forms.Textarea(attrs={'rows': 3}),
            'photo': forms.ClearableFileInput(attrs={'accept': 'image/*', 'capture': 'environment'}),
        }
        labels = {'comments': 'Your thoughts'}

    def clean_rating(self):
        return min(max(self.cleaned_data['rating'] or 0, 0), 5)


class WatchItemForm(forms.ModelForm):
    image_url = forms.CharField(required=False, widget=forms.HiddenInput)  # a picture found on the shop's page

    class Meta:
        model = WatchItem
        fields = ['name', 'url', 'kind', 'price', 'currency', 'photo', 'priority', 'status', 'notes']
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
            'photo': forms.ClearableFileInput(attrs={'accept': 'image/*'}),
            'currency': forms.TextInput(attrs={'maxlength': 3, 'placeholder': 'INR'}),
        }

    def clean_currency(self):
        return self.cleaned_data['currency'].strip().upper()
