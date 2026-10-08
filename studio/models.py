import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

class Stamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta: abstract = True

class Brand(Stamped):
    name = models.CharField(max_length=150)
    slug = models.SlugField(unique=True)
    logo = models.CharField(max_length=300, blank=True)
    description = models.TextField(blank=True)
    website = models.URLField(blank=True)
    timezone = models.CharField(max_length=60, default='America/New_York')
    status = models.CharField(max_length=20, default='ACTIVE', choices=[('ACTIVE','Active'),('INACTIVE','Inactive')])
    brand_voice = models.TextField(blank=True)
    visual_style = models.TextField(blank=True)
    target_customer = models.TextField(blank=True)
    content_guidelines = models.TextField(blank=True)
    negative_prompt = models.TextField(blank=True)
    def __str__(self): return self.name
    def clean(self):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try: ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError: raise ValidationError({'timezone':'Use a valid IANA timezone.'})

class Membership(models.Model):
    brand = models.ForeignKey(Brand,on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE)
    role = models.CharField(max_length=20,choices=[('ADMIN','Admin'),('EDITOR','Editor'),('REVIEWER','Reviewer'),('VIEWER','Viewer')],default='EDITOR')
    class Meta: constraints = [models.UniqueConstraint(fields=['brand','user'],name='unique_brand_member')]

class TenantModel(Stamped):
    brand = models.ForeignKey(Brand,on_delete=models.PROTECT)
    class Meta: abstract = True
    def clean(self):
        super().clean()
        for f in self._meta.fields:
            if isinstance(f,models.ForeignKey) and f.name != 'brand' and getattr(self,f.attname,None):
                target = getattr(self,f.name)
                if hasattr(target,'brand_id') and target.brand_id != self.brand_id:
                    raise ValidationError({f.name:'This record belongs to another brand.'})
    def save(self,*args,**kwargs):
        self.clean()
        return super().save(*args,**kwargs)

class SocialHandle(TenantModel):
    platform = models.CharField(max_length=30)
    handle = models.CharField(max_length=150)
    class Meta: constraints = [models.UniqueConstraint(fields=['brand','platform'],name='unique_social_brand')]

class BrandSettings(TenantModel):
    brand = models.OneToOneField(Brand,on_delete=models.CASCADE,related_name='preferences')
    preferred_locations = models.TextField(default='rooftop terrace\ncity sidewalk\nboutique hotel lobby')
    photography_style = models.TextField(blank=True)
    preferred_model_types = models.TextField(blank=True)
    image_ratio = models.CharField(max_length=20,default='4:5')
    prohibited_content = models.TextField(blank=True)
    caption_tone = models.TextField(blank=True)
    preferred_poses = models.TextField(default='walking naturally\nleaning on a railing\nseated candidly')
    generation_enabled = models.BooleanField(default=False)
    daily_count = models.PositiveSmallIntegerField(default=3)
    generation_time = models.TimeField(default='09:00')
    cooldown_days = models.PositiveSmallIntegerField(default=3)
    max_product_repeats = models.PositiveSmallIntegerField(default=1)
    minimum_spacing_days = models.PositiveSmallIntegerField(default=1)
    def clean(self):
        super().clean()
        if not 1 <= self.daily_count <= 20: raise ValidationError('Daily count must be 1–20.')

class ContentCategory(TenantModel):
    name = models.CharField(max_length=80)
    direction = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    class Meta: constraints = [models.UniqueConstraint(fields=['brand','name'],name='unique_category_brand')]
    def __str__(self): return self.name

class ShopifyStore(TenantModel):
    brand = models.OneToOneField(Brand,on_delete=models.CASCADE,related_name='shopify')
    domain = models.CharField(max_length=200)
    token_env = models.CharField(max_length=100,blank=True)
    api_version = models.CharField(max_length=20,default='2026-07')
    last_sync_at = models.DateTimeField(null=True,blank=True)
    oauth_client_env = models.CharField(max_length=100,blank=True)

class Collection(TenantModel):
    shopify_id = models.CharField(max_length=150)
    title = models.CharField(max_length=200)
    class Meta: constraints = [models.UniqueConstraint(fields=['brand','shopify_id'],name='unique_collection_external')]

class Character(TenantModel):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    height_build = models.CharField(max_length=200,blank=True)
    hair = models.CharField(max_length=200,blank=True)
    skin_tone = models.CharField(max_length=100,blank=True)
    facial_description = models.TextField(blank=True)
    consistency_instructions = models.TextField(blank=True)
    lora_model_id = models.CharField(max_length=200,blank=True)
    seed = models.BigIntegerField(null=True,blank=True)
    conditioning = models.JSONField(default=dict,blank=True)
    approved = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    def __str__(self): return self.name

class Product(TenantModel):
    shopify_id = models.CharField(max_length=150)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    sku = models.CharField(max_length=100,blank=True)
    retail_price = models.DecimalField(max_digits=12,decimal_places=2,default=0)
    currency = models.CharField(max_length=3,default='USD')
    status = models.CharField(max_length=30,default='active')
    active = models.BooleanField(default=True)
    generation_eligible = models.BooleanField(default=True)
    generation_notes = models.TextField(blank=True)
    product_url = models.URLField(blank=True)
    collections = models.ManyToManyField(Collection,through='ProductCollection')
    preferred_models = models.ManyToManyField(Character,through='ProductCharacter')
    preferred_categories = models.ManyToManyField(ContentCategory,through='ProductCategory')
    class Meta: constraints = [models.UniqueConstraint(fields=['brand','shopify_id'],name='unique_product_external')]
    def __str__(self): return self.title

class ProductCollection(TenantModel):
    product = models.ForeignKey(Product,on_delete=models.CASCADE)
    collection = models.ForeignKey(Collection,on_delete=models.CASCADE)
    class Meta: constraints = [models.UniqueConstraint(fields=['product','collection'],name='unique_product_collection')]
class ProductCharacter(TenantModel):
    product = models.ForeignKey(Product,on_delete=models.CASCADE)
    character = models.ForeignKey(Character,on_delete=models.CASCADE)
    class Meta: constraints = [models.UniqueConstraint(fields=['product','character'],name='unique_product_character')]
class ProductCategory(TenantModel):
    product = models.ForeignKey(Product,on_delete=models.CASCADE)
    category = models.ForeignKey(ContentCategory,on_delete=models.CASCADE)
    class Meta: constraints = [models.UniqueConstraint(fields=['product','category'],name='unique_product_category')]

class Variant(TenantModel):
    product = models.ForeignKey(Product,on_delete=models.CASCADE,related_name='variants')
    shopify_id = models.CharField(max_length=150)
    title = models.CharField(max_length=200)
    sku = models.CharField(max_length=100,blank=True)
    price = models.DecimalField(max_digits=12,decimal_places=2,default=0)
    inventory_quantity = models.IntegerField(null=True,blank=True)
    available = models.BooleanField(default=True)
    class Meta: constraints = [models.UniqueConstraint(fields=['brand','shopify_id'],name='unique_variant_external')]

class ProductImage(TenantModel):
    product = models.ForeignKey(Product,on_delete=models.CASCADE,related_name='images')
    shopify_id = models.CharField(max_length=150)
    url = models.URLField(max_length=1000)
    alt = models.CharField(max_length=300,blank=True)
    position = models.PositiveIntegerField(default=0)
    class Meta: constraints = [models.UniqueConstraint(fields=['brand','shopify_id'],name='unique_product_image')]

class PromptComponent(TenantModel):
    key = models.CharField(max_length=50)
    text = models.TextField()
    class Meta: constraints = [models.UniqueConstraint(fields=['brand','key'],name='unique_prompt_component')]
class PromptTemplate(TenantModel):
    name = models.CharField(max_length=100)
    template = models.TextField()
    active = models.BooleanField(default=True)

class ProviderConfig(TenantModel):
    brand = models.OneToOneField(Brand,on_delete=models.CASCADE,related_name='provider')
    kind = models.CharField(max_length=30,choices=[('openai','OpenAI Images'),('comfyui','ComfyUI / RunPod')],default='openai')
    model = models.CharField(max_length=100,default='gpt-image-1')
    credential_env = models.CharField(max_length=100,default='DEFIANT_IMAGE_API_KEY')
    endpoint = models.URLField(blank=True)
    settings = models.JSONField(default=dict,blank=True)
    enabled = models.BooleanField(default=False)

class DailyBatch(TenantModel):
    date = models.DateField()
    slot = models.PositiveIntegerField(default=0)
    candidate_count = models.PositiveIntegerField()
    source = models.CharField(max_length=20,default='manual')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True)
    class Meta: constraints = [models.UniqueConstraint(fields=['brand','date','slot'],name='unique_daily_batch')]

class ContentConcept(TenantModel):
    product = models.ForeignKey(Product,on_delete=models.PROTECT)
    character = models.ForeignKey(Character,on_delete=models.PROTECT)
    category = models.ForeignKey(ContentCategory,on_delete=models.PROTECT)
    batch = models.ForeignKey(DailyBatch,on_delete=models.PROTECT,null=True,blank=True,related_name='concepts')
    location = models.CharField(max_length=300)
    pose = models.CharField(max_length=300)
    composition = models.CharField(max_length=300,default='vertical 4:5; clothing clearly visible')
    lighting = models.CharField(max_length=300,default='believable environmental lighting, subtle depth of field')
    camera = models.CharField(max_length=300,default='natural influencer fashion photography')
    platform = models.CharField(max_length=30,default='Instagram')
    content_format = models.CharField(max_length=30,default='feed_image')
    prompt = models.TextField(blank=True)
    negative_prompt = models.TextField(blank=True)
    status = models.CharField(max_length=30,default='PLANNED')
    scheduled_date = models.DateField(null=True,blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True)

class Generation(TenantModel):
    id = models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False)
    concept = models.ForeignKey(ContentConcept,on_delete=models.PROTECT,related_name='generations')
    product = models.ForeignKey(Product,on_delete=models.PROTECT)
    character = models.ForeignKey(Character,on_delete=models.PROTECT)
    parent = models.ForeignKey('self',on_delete=models.PROTECT,null=True,blank=True,related_name='regenerations')
    provider = models.CharField(max_length=30)
    provider_model = models.CharField(max_length=100)
    prompt = models.TextField()
    negative_prompt = models.TextField(blank=True)
    provider_settings = models.JSONField(default=dict)
    seed = models.BigIntegerField(null=True,blank=True)
    idempotency_key = models.CharField(max_length=200,unique=True)
    def save(self,*args,**kwargs):
        if not self._state.adding: raise ValidationError('Generation history is immutable.')
        return super().save(*args,**kwargs)
    def delete(self,*args,**kwargs): raise ValidationError('Generation history is immutable.')
    @property
    def state(self):
        review = self.reviews.order_by('-created_at','-id').first()
        if review: return review.decision
        if hasattr(self,'result'): return 'NEEDS_REVIEW'
        if hasattr(self,'job'): return self.job.status
        return 'PLANNED'
    @property
    def output(self): return self.assets.filter(asset_type='generated_image').first()

class Asset(TenantModel):
    asset_type = models.CharField(max_length=40)
    storage_key = models.CharField(max_length=500,unique=True)
    original_filename = models.CharField(max_length=200)
    width = models.PositiveIntegerField(null=True)
    height = models.PositiveIntegerField(null=True)
    mime_type = models.CharField(max_length=100)
    source = models.CharField(max_length=100)
    generation = models.ForeignKey(Generation,on_delete=models.PROTECT,null=True,blank=True,related_name='assets')
    original = models.ForeignKey('self',on_delete=models.PROTECT,null=True,blank=True)
    approved = models.BooleanField(default=False)

class CharacterReference(TenantModel):
    character = models.ForeignKey(Character,on_delete=models.CASCADE,related_name='references')
    asset = models.ForeignKey(Asset,on_delete=models.PROTECT)
    role = models.CharField(max_length=30,choices=[('face','Face'),('body','Full body'),('style','Style'),('controlnet','ControlNet')])

class GenerationReference(TenantModel):
    generation = models.ForeignKey(Generation,on_delete=models.PROTECT,related_name='references')
    asset = models.ForeignKey(Asset,on_delete=models.PROTECT,null=True)
    url = models.URLField(max_length=1000,blank=True)
    role = models.CharField(max_length=30)

class GenerationResult(TenantModel):
    generation = models.OneToOneField(Generation,on_delete=models.PROTECT,related_name='result')
    external_id = models.CharField(max_length=200,blank=True)
    duration_seconds = models.FloatField(null=True)
    cost = models.DecimalField(max_digits=10,decimal_places=5,null=True)
    metadata = models.JSONField(default=dict)
    def save(self,*args,**kwargs):
        if not self._state.adding: raise ValidationError('Generation results are immutable.')
        return super().save(*args,**kwargs)

class GenerationJob(TenantModel):
    generation = models.OneToOneField(Generation,on_delete=models.PROTECT,related_name='job')
    status = models.CharField(max_length=30,default='PLANNED')
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    available_at = models.DateTimeField()
    locked_at = models.DateTimeField(null=True)
    lease_token = models.UUIDField(null=True)
    error = models.TextField(blank=True)
    class Meta: indexes = [models.Index(fields=['status','available_at'])]

class ReviewDecision(TenantModel):
    generation = models.ForeignKey(Generation,on_delete=models.PROTECT,related_name='reviews')
    decision = models.CharField(max_length=30,choices=[('APPROVED','Approved'),('REJECTED','Rejected'),('REGENERATE','Regenerate'),('READY_TO_POST','Ready to post')])
    notes = models.TextField(blank=True)
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)

class CalendarEntry(TenantModel):
    date = models.DateField()
    platform = models.CharField(max_length=30,default='Instagram')
    concept = models.ForeignKey(ContentConcept,on_delete=models.PROTECT)
    generation = models.OneToOneField(Generation,on_delete=models.PROTECT)
    intended_posting_time = models.DateTimeField(null=True,blank=True)
    actual_posting_time = models.DateTimeField(null=True,blank=True)
    post_url = models.URLField(blank=True)
    notes = models.TextField(blank=True)

class PerformanceData(TenantModel):
    calendar_entry = models.ForeignKey(CalendarEntry,on_delete=models.PROTECT)
    impressions = models.PositiveIntegerField(default=0)
    reach = models.PositiveIntegerField(default=0)
    likes = models.PositiveIntegerField(default=0)
    comments = models.PositiveIntegerField(default=0)
    saves = models.PositiveIntegerField(default=0)
    shares = models.PositiveIntegerField(default=0)
    clicks = models.PositiveIntegerField(default=0)
    product_views = models.PositiveIntegerField(default=0)
    add_to_cart = models.PositiveIntegerField(default=0)
    purchases = models.PositiveIntegerField(default=0)
    revenue = models.DecimalField(max_digits=14,decimal_places=2,default=0)
    attributed_revenue = models.DecimalField(max_digits=14,decimal_places=2,default=0)
    roas = models.DecimalField(max_digits=10,decimal_places=4,null=True)

class AuditEvent(TenantModel):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True)
    action = models.CharField(max_length=100)
    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=100)
    details = models.JSONField(default=dict)
    def save(self,*args,**kwargs):
        if not self._state.adding: raise ValidationError('Audit history is append-only.')
        return super().save(*args,**kwargs)

class ResolvedReference(TenantModel):
    reference = models.OneToOneField(GenerationReference,on_delete=models.PROTECT,related_name='snapshot')
    asset = models.ForeignKey(Asset,on_delete=models.PROTECT)
