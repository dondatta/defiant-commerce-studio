import itertools, uuid
from collections import Counter
from datetime import timedelta
from string import Formatter
from zoneinfo import ZoneInfo
from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError
from django.db.models import Max
from django.utils import timezone
from .models import *
from . import storage, providers

def audit(brand,actor,action,obj,details=None):
    return AuditEvent.objects.create(brand=brand,actor=actor,action=action,object_type=type(obj).__name__,object_id=str(obj.pk),details=details or {})

def brand_today(brand): return timezone.now().astimezone(ZoneInfo(brand.timezone)).date()

def build_prompt(concept):
    brand = concept.brand
    components = dict(PromptComponent.objects.filter(brand=brand).values_list('key','text'))
    character = concept.character
    parts = {
        'brand_style':brand.visual_style,
        'brand_voice':brand.brand_voice,
        'guidelines':brand.content_guidelines,
        'target_customer':brand.target_customer,
        'character':f'{character.name}: {character.description}; {character.hair}; {character.skin_tone}; {character.facial_description}; {character.height_build}. {character.consistency_instructions}. Follow attached identity references; do not infer identity from the name.',
        'product':f'{concept.product.title}. {concept.product.description}. {concept.product.generation_notes}. Preserve clothing details from clothing references.',
        'category':f'{concept.category.name}. {concept.category.direction}',
        'location':concept.location,'pose':concept.pose,'composition':concept.composition,
        'lighting':concept.lighting,'camera':concept.camera,'platform':concept.platform,
        'requirements':components.get('requirements','Photorealistic image; realistic anatomy, hands and fabric; clothing clearly visible.'),
        'negative_prompt':brand.negative_prompt,
    }
    parts.update({k:v for k,v in components.items() if k not in parts or k in ('requirements',)})
    template = PromptTemplate.objects.filter(brand=brand,active=True).order_by('id').first()
    pattern = template.template if template else '{brand_style}\n{character}\n{product}\n{category}\n{location}\n{pose}\n{camera}\n{lighting}\n{composition}\n{requirements}\n{guidelines}'
    try:
        # Reject attribute traversal and indexing, not just unknown substitutions.
        for _,field,format_spec,conversion in Formatter().parse(pattern):
            if field and (field not in parts or format_spec or conversion): raise ValueError('Unknown prompt placeholder')
        prompt = pattern.format_map(parts)
    except (KeyError,ValueError) as exc: raise ValidationError('Prompt template contains an unsupported placeholder.') from exc
    return prompt,brand.negative_prompt

def ensure_eligible(concept):
    concept.clean()
    if concept.brand.status != 'ACTIVE': raise ValidationError('Brand is inactive.')
    if not concept.product.active or not concept.product.generation_eligible: raise ValidationError('Product is not eligible for generation.')
    if not concept.character.active or not concept.character.approved: raise ValidationError('Select an active, approved character.')
    if not concept.category.active: raise ValidationError('Category is inactive.')
    if not concept.character.references.filter(role='face').exists(): raise ValidationError('Attach at least one face reference before generating.')
    if not concept.product.images.exists(): raise ValidationError('Import a product image before generating.')

@transaction.atomic
def enqueue(concept,actor=None,parent=None,idempotency_key=None,overrides=None):
    ensure_eligible(concept)
    config = ProviderConfig.objects.filter(brand=concept.brand,enabled=True).first()
    if not config: raise ValidationError('Enable and configure an image provider in brand settings first.')
    prompt,negative = build_prompt(concept)
    prompt = concept.prompt or prompt
    negative = concept.negative_prompt or negative
    overrides = overrides or {}
    if parent and parent.brand_id != concept.brand_id: raise ValidationError('Parent belongs to another brand.')
    key = idempotency_key or str(uuid.uuid4())
    existing = Generation.objects.filter(idempotency_key=key).first()
    if existing:
        if existing.brand_id != concept.brand_id or existing.concept_id != concept.pk: raise ValidationError('Idempotency key belongs to another request.')
        return existing
    snapshot = dict(config.settings)
    snapshot['endpoint'] = config.endpoint
    snapshot['credential_env'] = config.credential_env
    snapshot['lora_model_id'] = concept.character.lora_model_id
    snapshot['conditioning'] = concept.character.conditioning
    seed = overrides.get('seed',concept.character.seed)
    generation = Generation.objects.create(brand=concept.brand,concept=concept,product=concept.product,character=concept.character,parent=parent,provider=config.kind,provider_model=config.model,prompt=overrides.get('prompt',prompt),negative_prompt=negative,provider_settings=snapshot,seed=seed,idempotency_key=key)
    for reference in concept.character.references.select_related('asset'):
        GenerationReference.objects.create(brand=concept.brand,generation=generation,asset=reference.asset,role=reference.role)
    for image in concept.product.images.order_by('position','id')[:3]:
        GenerationReference.objects.create(brand=concept.brand,generation=generation,url=image.url,role='clothing')
    GenerationJob.objects.create(brand=concept.brand,generation=generation,available_at=timezone.now())
    audit(concept.brand,actor,'generation.enqueued',generation,{'parent':str(parent.pk) if parent else None})
    return generation

@transaction.atomic
def create_daily_batch(brand,actor=None,source='manual',additional=False):
    # Lock per-brand preferences: serializes batch selection on PostgreSQL.
    prefs = BrandSettings.objects.select_for_update().get(brand=brand)
    day = brand_today(brand)
    if not additional:
        existing = DailyBatch.objects.filter(brand=brand,date=day,slot=0).first()
        if existing: return existing,False
    slot = ((DailyBatch.objects.filter(brand=brand,date=day).aggregate(n=Max('slot'))['n'] or 0)+1) if additional else 0
    products = list(Product.objects.filter(brand=brand,active=True,generation_eligible=True,images__isnull=False).distinct().order_by('id'))
    characters = list(Character.objects.filter(brand=brand,active=True,approved=True,references__role='face').distinct().order_by('id'))
    categories = list(ContentCategory.objects.filter(brand=brand,active=True).order_by('id'))
    locations = list(dict.fromkeys(x.strip() for x in prefs.preferred_locations.splitlines() if x.strip()))
    poses = list(dict.fromkeys(x.strip() for x in prefs.preferred_poses.splitlines() if x.strip()))
    count = prefs.daily_count
    if not characters or not products: raise ValidationError('Import eligible products with images and approve a character with face references first.')
    if min(len(categories),len(locations),len(poses)) < count: raise ValidationError(f'Provide at least {count} distinct categories, locations and poses to respect daily variety.')
    if len(products)*prefs.max_product_repeats < count: raise ValidationError('Not enough products for the configured maximum product repeats.')
    recent = list(ContentConcept.objects.filter(brand=brand,created_at__gte=timezone.now()-timedelta(days=max(prefs.cooldown_days,prefs.minimum_spacing_days))).values('product_id','character_id','category_id','location','pose','created_at'))
    def usage(field,value): return sum(row[field] == value for row in recent)
    products.sort(key=lambda x:usage('product_id',x.pk))
    characters.sort(key=lambda x:usage('character_id',x.pk))
    categories.sort(key=lambda x:usage('category_id',x.pk))
    # Stable daily rotation, then rank by recent usage.
    offset = day.toordinal() % len(locations)
    locations = locations[offset:]+locations[:offset]
    locations.sort(key=lambda x:usage('location',x))
    poses.sort(key=lambda x:usage('pose',x))
    choices=[]; used_products=Counter(); used_characters=Counter()
    for i in range(count):
        selected=None
        products.sort(key=lambda p:(used_products[p.pk],usage('product_id',p.pk)))
        characters.sort(key=lambda c:(used_characters[c.pk],usage('character_id',c.pk)))
        for product,character in itertools.product(products,characters):
            if used_products[product.pk] >= prefs.max_product_repeats: continue
            if product.preferred_models.exists() and not product.preferred_models.filter(pk=character.pk).exists(): continue
            category=categories[i]
            if product.preferred_categories.exists() and not product.preferred_categories.filter(pk=category.pk).exists(): continue
            if any(row['character_id']==character.pk and row['location']==locations[i] and row['created_at'] >= timezone.now()-timedelta(days=prefs.cooldown_days) for row in recent): continue
            if any(row['product_id']==product.pk and row['category_id']==category.pk and row['pose']==poses[i] and row['created_at'] >= timezone.now()-timedelta(days=prefs.minimum_spacing_days) for row in recent): continue
            selected=(product,character,category,locations[i],poses[i]); break
        if not selected: raise ValidationError('Cooldowns or product preferences leave too few valid concepts. Add variety or adjust brand rules.')
        choices.append(selected); used_products[selected[0].pk]+=1; used_characters[selected[1].pk]+=1
    batch = DailyBatch.objects.create(brand=brand,date=day,slot=slot,candidate_count=count,source=source,created_by=actor)
    components = dict(PromptComponent.objects.filter(brand=brand).values_list('key','text'))
    for i,(product,character,category,location,pose) in enumerate(choices):
        concept=ContentConcept.objects.create(brand=brand,product=product,character=character,category=category,batch=batch,location=location,pose=pose,camera=components.get(f'daily_mix_{i%3+1}','realistic social-commerce photography'),composition=components.get(f'daily_framing_{i+1}',f"{prefs.image_ratio}; {('full-body','three-quarter','mid-length')[i%3]} fashion portrait; clothing clearly visible"),scheduled_date=day,created_by=actor)
        audit(brand,actor,'concept.created',concept)
        enqueue(concept,actor,idempotency_key=f'batch:{batch.pk}:{i}')
    audit(brand,actor,'batch.created',batch,{'count':count,'source':source})
    return batch,True

@transaction.atomic
def regenerate(generation,actor,changes=None,mode='same',idempotency_key=None):
    changes=changes or {}
    allowed={'product','character','category','location','pose','camera','composition','lighting','prompt'}
    if set(changes)-allowed: raise ValidationError('Unsupported regeneration fields.')
    original=generation.concept
    data={field:getattr(original,field) for field in ['product','character','category','location','pose','camera','composition','lighting','platform','content_format','negative_prompt']}
    data.update(changes)
    concept=ContentConcept.objects.create(brand=generation.brand,created_by=actor,**data)
    overrides={}
    if mode=='new_seed': overrides['seed']=uuid.uuid4().int%(2**32)
    if mode in ('consistency','realism'):
        prompt,_=build_prompt(concept)
        overrides['prompt']=prompt+ ('\nMatch face and body identity closely to all reference images.' if mode=='consistency' else '\nPrioritize realistic skin texture, accurate anatomy, fabric and physically believable lighting.')
    child=enqueue(concept,actor,parent=generation,idempotency_key=idempotency_key,overrides=overrides)
    ReviewDecision.objects.create(brand=generation.brand,generation=generation,decision='REGENERATE',reviewer=actor,notes=f'Regenerated as {child.pk}')
    CalendarEntry.objects.filter(generation=generation).delete()
    generation.assets.update(approved=False)
    audit(generation.brand,actor,'generation.regenerated',generation,{'child':str(child.pk),'mode':mode})
    return child

@transaction.atomic
def review(generation,actor,decision,notes=''):
    if decision not in ('APPROVED','REJECTED','READY_TO_POST'): raise ValidationError('Invalid review decision.')
    generation=Generation.objects.select_for_update().get(pk=generation.pk)
    if not hasattr(generation,'result'): raise ValidationError('Only completed generations can be reviewed.')
    if decision=='READY_TO_POST' and generation.state not in ('APPROVED','READY_TO_POST'): raise ValidationError('Approve the image before marking it ready to post.')
    record=ReviewDecision.objects.create(brand=generation.brand,generation=generation,reviewer=actor,decision=decision,notes=notes)
    generation.assets.update(approved=decision in ('APPROVED','READY_TO_POST'))
    if decision in ('APPROVED','READY_TO_POST'):
        CalendarEntry.objects.get_or_create(generation=generation,defaults={'brand':generation.brand,'concept':generation.concept,'date':generation.concept.scheduled_date or brand_today(generation.brand)})
    else: CalendarEntry.objects.filter(generation=generation).delete()
    audit(generation.brand,actor,'generation.'+decision.lower(),generation,{'review_id':record.pk})
    return record

def schedule_due():
    outcomes=[]
    for prefs in BrandSettings.objects.filter(generation_enabled=True,brand__status='ACTIVE').select_related('brand'):
        now=timezone.now().astimezone(ZoneInfo(prefs.brand.timezone))
        if now.time().replace(tzinfo=None)<prefs.generation_time: continue
        try:
            batch,created=create_daily_batch(prefs.brand,source='scheduled')
            outcomes.append((prefs.brand_id,'created' if created else 'existing'))
        except (ValidationError,IntegrityError) as exc:
            # Keep schedule errors visible and do not stop other brands.
            if not AuditEvent.objects.filter(brand=prefs.brand,action='schedule.failed',created_at__date=timezone.now().date()).exists():
                audit(prefs.brand,None,'schedule.failed',prefs,{'error':str(exc)[:500]})
            outcomes.append((prefs.brand_id,'failed'))
    return outcomes

@transaction.atomic
def claim_job():
    now=timezone.now()
    # A remote call may have succeeded before a crash. Do not automatically resubmit stale leases.
    stale=GenerationJob.objects.filter(status='GENERATING',locked_at__lt=now-timedelta(minutes=30))
    stale.update(status='FAILED',error='Worker lease expired. Inspect the provider before manually retrying to avoid duplicate remote charges.')
    qs=GenerationJob.objects.filter(status='PLANNED',available_at__lte=now,brand__status='ACTIVE').order_by('available_at','id')
    from django.db import connection
    if connection.features.has_select_for_update_skip_locked: qs=qs.select_for_update(skip_locked=True)
    job=qs.first()
    if not job: return None
    token=uuid.uuid4()
    claimed=GenerationJob.objects.filter(pk=job.pk,status='PLANNED').update(status='GENERATING',locked_at=now,lease_token=token,attempts=job.attempts+1)
    if not claimed: return None
    job.refresh_from_db()
    return job

def resolve_references(gen):
    from .network import download
    for ref in gen.references.filter(asset__isnull=True):
        if hasattr(ref, 'snapshot'): continue
        data = download(ref.url)
        with transaction.atomic():
            asset = storage.make_asset(gen.brand,data,'product-reference.png','product_reference','shopify_snapshot',generation=gen)
            ResolvedReference.objects.create(brand=gen.brand,reference=ref,asset=asset)
    return gen

def run_one_job():
    job=claim_job()
    if not job: return False
    gen=job.generation
    try:
        config=ProviderConfig.objects.get(brand=job.brand,enabled=True,kind=gen.provider)
        if hasattr(gen,'result'):
            GenerationJob.objects.filter(pk=job.pk,lease_token=job.lease_token).update(status='GENERATED',error='',locked_at=None)
            return True
        started=timezone.now()
        resolve_references(gen)
        output=providers.generate_image(gen,config)
        with transaction.atomic():
            current=GenerationJob.objects.select_for_update().get(pk=job.pk)
            if current.status!='GENERATING' or current.lease_token != job.lease_token: return True
            asset=storage.make_asset(job.brand,output.data,'original.png','generated_image',gen.provider,generation=gen)
            GenerationResult.objects.create(brand=job.brand,generation=gen,external_id=output.external_id,duration_seconds=(timezone.now()-started).total_seconds(),cost=output.cost,metadata=output.metadata or {})
            current.status='GENERATED'; current.error=''; current.locked_at=None; current.save()
            audit(job.brand,None,'generation.completed',gen,{'asset':asset.pk,'attempt':job.attempts})
    except Exception as exc:
        from .network import ProviderHTTPError
        # Only retry definitive pre-generation rejection responses; ambiguous network failures require review.
        retryable=isinstance(exc,ProviderHTTPError) and exc.status == 429
        message=str(exc) if isinstance(exc,(ValidationError,ProviderHTTPError)) else f'{type(exc).__name__}: provider or storage operation failed; inspect worker logs.'
        import logging
        logging.getLogger(__name__).error('Generation %s attempt %s: %s',gen.pk,job.attempts,message)
        status='PLANNED' if retryable and job.attempts<job.max_attempts else 'FAILED'
        GenerationJob.objects.filter(pk=job.pk,lease_token=job.lease_token).update(status=status,error=message[:1000],available_at=timezone.now()+timedelta(seconds=30*2**job.attempts),locked_at=None)
        audit(job.brand,None,'generation.attempt_failed',gen,{'attempt':job.attempts,'error':message[:500],'retry':status=='PLANNED'})
    return True
