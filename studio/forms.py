import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django import forms
from .models import *

class BrandForm(forms.ModelForm):
    class Meta:
        model=Brand
        fields=['name','slug','logo','description','website','timezone','status','brand_voice','visual_style','target_customer','content_guidelines','negative_prompt']
    def clean_timezone(self):
        value=self.cleaned_data['timezone']
        try: ZoneInfo(value)
        except ZoneInfoNotFoundError: raise forms.ValidationError('Enter an IANA timezone such as America/New_York.')
        return value
class SettingsForm(forms.ModelForm):
    class Meta:
        model=BrandSettings
        exclude=['brand','created_at','updated_at']
    def clean(self):
        data=super().clean()
        if data.get('generation_enabled'):
            count=data.get('daily_count',3)
            for field in ('preferred_locations','preferred_poses'):
                if len(set(x.strip() for x in data.get(field,'').splitlines() if x.strip()))<count:
                    self.add_error(field,'Add enough distinct choices for the daily candidate count.')
        return data
class CharacterForm(forms.ModelForm):
    class Meta:
        model=Character
        exclude=['brand','created_at','updated_at']
class ProductForm(forms.ModelForm):
    class Meta:
        model=Product
        fields=['active','generation_eligible','generation_notes','preferred_models','preferred_categories']
    def __init__(self,*args,brand,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['preferred_models'].queryset=Character.objects.filter(brand=brand)
        self.fields['preferred_categories'].queryset=ContentCategory.objects.filter(brand=brand)
class ConceptForm(forms.ModelForm):
    class Meta:
        model=ContentConcept
        fields=['product','character','category','location','pose','composition','lighting','camera','platform','content_format','prompt','negative_prompt','scheduled_date']
    def __init__(self,*args,brand,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['product'].queryset=Product.objects.filter(brand=brand,active=True,generation_eligible=True)
        self.fields['character'].queryset=Character.objects.filter(brand=brand,active=True,approved=True)
        self.fields['category'].queryset=ContentCategory.objects.filter(brand=brand,active=True)
class ProviderForm(forms.ModelForm):
    class Meta:
        model=ProviderConfig
        exclude=['brand','created_at','updated_at']
    def clean_credential_env(self):
        value=self.cleaned_data['credential_env']
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',value): raise forms.ValidationError('Enter an environment variable name, never a credential value.')
        return value
    def clean_settings(self):
        value=self.cleaned_data['settings']
        if not isinstance(value,dict): raise forms.ValidationError('Provider settings must be a JSON object.')
        def check(item):
            if isinstance(item,dict):
                for key,val in item.items():
                    if key.lower() in ('api_key','token','authorization','password','secret'): raise forms.ValidationError('Do not store credentials in settings. Use an environment binding.')
                    check(val)
            elif isinstance(item,list):
                for val in item: check(val)
        check(value)
        return value
    def clean(self):
        data=super().clean()
        if data.get('enabled') and data.get('kind')=='comfyui' and not data.get('endpoint'): self.add_error('endpoint','Configure the ComfyUI endpoint.')
        if data.get('endpoint'):
            from .network import validate_url
            validate_url(data['endpoint'],allow_local=True)
        return data
class ShopifyForm(forms.ModelForm):
    class Meta:
        model=ShopifyStore
        fields=['domain','token_env','api_version','oauth_client_env']
    def clean_domain(self):
        value=self.cleaned_data['domain'].strip().lower()
        if not re.fullmatch(r'[a-z0-9][a-z0-9-]*\.myshopify\.com',value): raise forms.ValidationError('Use store-name.myshopify.com.')
        return value
    def clean_token_env(self):
        value=self.cleaned_data['token_env']
        if value and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',value): raise forms.ValidationError('Enter a binding name, not a token.')
        return value
class PromptComponentForm(forms.ModelForm):
    class Meta:
        model=PromptComponent
        fields=['key','text']
class PromptTemplateForm(forms.ModelForm):
    class Meta:
        model=PromptTemplate
        fields=['name','template','active']
class CategoryForm(forms.ModelForm):
    class Meta:
        model=ContentCategory
        fields=['name','direction','active']
class ReferenceForm(forms.Form):
    role=forms.ChoiceField(choices=CharacterReference._meta.get_field('role').choices)
    image=forms.FileField()
class ImportForm(forms.Form):
    file=forms.FileField(help_text='Shopify-style JSON: {"products": [{"id": ..., "title": ..., "images": [...], "variants": [...]}]}')
class ReviewForm(forms.Form):
    action=forms.ChoiceField(choices=[('APPROVED','Approve'),('REJECTED','Reject'),('READY_TO_POST','Ready to post')])
    notes=forms.CharField(widget=forms.Textarea,required=False)
class RegenerateForm(ConceptForm):
    mode=forms.ChoiceField(choices=[('same','Same concept'),('new_seed','New seed'),('consistency','Stronger identity'),('realism','Stronger realism')])
class MembershipForm(forms.ModelForm):
    class Meta:
        model=Membership
        fields=['user','role']

class CalendarForm(forms.ModelForm):
    class Meta:
        model=CalendarEntry
        fields=['date','platform','intended_posting_time','notes']
        widgets={'date':forms.DateInput(attrs={'type':'date'}),'intended_posting_time':forms.DateTimeInput(attrs={'type':'datetime-local'},format='%Y-%m-%dT%H:%M')}
class SocialHandleForm(forms.ModelForm):
    class Meta:
        model=SocialHandle
        fields=['platform','handle']
