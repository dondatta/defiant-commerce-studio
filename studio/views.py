import json, uuid
from functools import wraps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST, require_http_methods
from django.utils import timezone
from .models import *
from .forms import *
from .permissions import brands_for, require_brand
from . import services, storage, shopify

def guarded(fn):
    @wraps(fn)
    def wrapped(request,*args,**kwargs):
        try: return fn(request,*args,**kwargs)
        except (ValidationError,IntegrityError,ValueError,KeyError) as exc:
            message='A duplicate or invalid relational record was rejected.' if isinstance(exc,IntegrityError) else str(exc)
            if request.path.startswith('/api/'): return JsonResponse({'error':message},status=400)
            return render(request,'studio/error.html',{'title':'Action needs attention','error':message},status=400)
    return wrapped

def context(request,brand=None,**kwargs):
    role = Membership.objects.filter(brand=brand,user=request.user).values_list('role',flat=True).first() if brand else None
    return {'brand':brand,'brands':brands_for(request.user).order_by('name'),'can_admin':request.user.is_superuser or role=='ADMIN','can_edit':request.user.is_superuser or role in ('ADMIN','EDITOR'),'can_review':request.user.is_superuser or role in ('ADMIN','EDITOR','REVIEWER'),**kwargs}

@login_required
def brands(request):
    return render(request,'studio/brands.html',context(request,title='Your brands'))

@login_required
@guarded
def create_brand(request):
    if not request.user.is_superuser: raise PermissionDenied
    form=BrandForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            brand=form.save()
            BrandSettings.objects.create(brand=brand)
            services.audit(brand,request.user,'brand.created',brand)
        return redirect('workspace',brand_id=brand.pk)
    return render(request,'studio/form.html',context(request,title='Create a brand',form=form))

@login_required
def workspace(request,brand_id):
    brand=require_brand(request.user,brand_id)
    generations=Generation.objects.filter(brand=brand).select_related('concept__category','product','character','job','result').prefetch_related('assets','reviews').order_by('-created_at')
    return render(request,'studio/workspace.html',context(request,brand,title='Workspace',generations=generations[:6],product_count=Product.objects.filter(brand=brand).count(),character_count=Character.objects.filter(brand=brand).count(),review_count=sum(g.state=='NEEDS_REVIEW' for g in generations),approved_count=sum(g.state in ('APPROVED','READY_TO_POST') for g in generations),batches=DailyBatch.objects.filter(brand=brand).order_by('-created_at')[:5]))

@login_required
def products(request,brand_id):
    brand=require_brand(request.user,brand_id)
    rows=Product.objects.filter(brand=brand).prefetch_related('images','variants','collections').order_by('title')
    return render(request,'studio/products.html',context(request,brand,title='Product library',products=rows,import_form=ImportForm()))

@login_required
@require_POST
@guarded
def import_products(request,brand_id):
    brand=require_brand(request.user,brand_id,write=True)
    form=ImportForm(request.POST,request.FILES)
    if not form.is_valid(): raise ValidationError('Choose a Shopify-style JSON file.')
    file=form.cleaned_data['file']
    if file.size>10*1024*1024: raise ValidationError('Import file must be under 10 MB.')
    count=shopify.import_products(brand,json.load(file),request.user)
    messages.success(request,f'Imported or updated {count} products.')
    return redirect('products',brand_id=brand.pk)

@login_required
@require_POST
@guarded
def sync_products(request,brand_id):
    brand=require_brand(request.user,brand_id,admin=True)
    if not hasattr(brand,'shopify'): raise ValidationError('Configure the Shopify store first.')
    count=shopify.sync_shopify(brand,request.user)
    messages.success(request,f'Synced {count} products.')
    return redirect('products',brand_id=brand.pk)

@login_required
def characters(request,brand_id):
    brand=require_brand(request.user,brand_id)
    return render(request,'studio/characters.html',context(request,brand,title='AI characters',characters=Character.objects.filter(brand=brand).prefetch_related('references__asset')))

@login_required
@guarded
def reference(request,brand_id,character_id):
    brand=require_brand(request.user,brand_id,write=True)
    character=get_object_or_404(Character,brand=brand,pk=character_id)
    form=ReferenceForm(request.POST or None,request.FILES or None)
    if request.method=='POST' and form.is_valid():
        file=form.cleaned_data['image']
        with transaction.atomic():
            asset=storage.make_asset(brand,file.read(),file.name,'character_reference','upload')
            ref=CharacterReference.objects.create(brand=brand,character=character,asset=asset,role=form.cleaned_data['role'])
            services.audit(brand,request.user,'character.reference_added',ref)
        messages.success(request,'Reference attached. Generation snapshots will retain this reference.')
        return redirect('characters',brand_id=brand.pk)
    return render(request,'studio/form.html',context(request,brand,title=f'Attach a reference · {character.name}',form=form,help='Use images you have permission to use. Face references are required for generation.'))

@login_required
@guarded
def edit_record(request,brand_id,kind,record_id=None):
    admin=kind in ('brand','settings','provider','shopify','component','template','category','social')
    brand=require_brand(request.user,brand_id,write=not admin,admin=admin)
    mapping={'brand':(Brand,BrandForm),'settings':(BrandSettings,SettingsForm),'provider':(ProviderConfig,ProviderForm),'shopify':(ShopifyStore,ShopifyForm),'character':(Character,CharacterForm),'product':(Product,ProductForm),'concept':(ContentConcept,ConceptForm),'component':(PromptComponent,PromptComponentForm),'template':(PromptTemplate,PromptTemplateForm),'category':(ContentCategory,CategoryForm),'calendar':(CalendarEntry,CalendarForm),'social':(SocialHandle,SocialHandleForm)}
    if kind not in mapping: raise Http404
    model,form_class=mapping[kind]
    if kind=='brand': instance=brand
    elif kind in ('settings','provider','shopify'): instance=model.objects.filter(brand=brand).first() or model(brand=brand)
    elif record_id: instance=get_object_or_404(model,pk=record_id,brand=brand)
    else: instance=model(brand=brand)
    kwargs={'instance':instance}
    if kind in ('concept','product'): kwargs['brand']=brand
    form=form_class(request.POST or None,**kwargs)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            obj=form.save(commit=False)
            if kind=='concept': obj.created_by=request.user
            obj.save()
            if kind=='product':
                for field,through,target in [('preferred_models',ProductCharacter,'character'),('preferred_categories',ProductCategory,'category')]:
                    through.objects.filter(product=obj).delete()
                    for selected in form.cleaned_data[field]: through.objects.create(brand=brand,product=obj,**{target:selected})
            else: form.save_m2m()
            services.audit(brand,request.user,kind+'.saved',obj)
        messages.success(request,'Changes saved.')
        if kind=='concept': return redirect('concepts',brand_id=brand.pk)
        if kind=='character': return redirect('characters',brand_id=brand.pk)
        if kind=='product': return redirect('products',brand_id=brand.pk)
        if kind=='calendar': return redirect('calendar',brand_id=brand.pk)
        return redirect('settings',brand_id=brand.pk)
    return render(request,'studio/form.html',context(request,brand,title=kind.replace('_',' ').title(),form=form,help='Provider and Shopify credentials stay in environment variables. Enter binding names only.'))

@login_required
def settings_page(request,brand_id):
    brand=require_brand(request.user,brand_id,admin=True)
    return render(request,'studio/settings.html',context(request,brand,title='Brand configuration',components=PromptComponent.objects.filter(brand=brand),templates=PromptTemplate.objects.filter(brand=brand),categories=ContentCategory.objects.filter(brand=brand),handles=SocialHandle.objects.filter(brand=brand),members=Membership.objects.filter(brand=brand).select_related('user')))

@login_required
def concepts(request,brand_id):
    brand=require_brand(request.user,brand_id)
    return render(request,'studio/concepts.html',context(request,brand,title='Content concepts',concepts=ContentConcept.objects.filter(brand=brand).select_related('product','character','category').order_by('-created_at')))

@login_required
@require_POST
@guarded
def generate_concept(request,brand_id,concept_id):
    brand=require_brand(request.user,brand_id,write=True)
    concept=get_object_or_404(ContentConcept,brand=brand,pk=concept_id)
    generation=services.enqueue(concept,request.user,idempotency_key=f'concept:{concept.pk}:initial')
    messages.success(request,'Generation queued. Run the worker to process it.')
    return redirect('generation',brand_id=brand.pk,generation_id=generation.pk)

@login_required
@require_POST
@guarded
def daily_batch(request,brand_id):
    brand=require_brand(request.user,brand_id,write=True)
    additional=request.POST.get('additional')=='confirmed'
    batch,created=services.create_daily_batch(brand,request.user,additional=additional)
    messages.success(request,f'{batch.candidate_count} candidates queued.' if created else 'Today’s batch already exists; no duplicate jobs created.')
    return redirect('queue',brand_id=brand.pk)

@login_required
def queue(request,brand_id):
    brand=require_brand(request.user,brand_id)
    rows=Generation.objects.filter(brand=brand).select_related('concept__category','product','character','job','result').prefetch_related('assets','reviews').order_by('-created_at')
    for field in ('product','character'):
        value=request.GET.get(field)
        if value and value.isdigit(): rows=rows.filter(**{field+'_id':value})
    category=request.GET.get('category')
    if category and category.isdigit(): rows=rows.filter(concept__category_id=category)
    date=request.GET.get('date')
    if date:
        from django.utils.dateparse import parse_date
        day=parse_date(date)
        if day: rows=rows.filter(created_at__date=day)
    result=list(rows)
    status=request.GET.get('status')
    if status: result=[g for g in result if g.state==status]
    return render(request,'studio/queue.html',context(request,brand,title='Review queue',generations=result,products=Product.objects.filter(brand=brand),characters=Character.objects.filter(brand=brand),categories=ContentCategory.objects.filter(brand=brand)))

@login_required
@guarded
def generation_detail(request,brand_id,generation_id):
    brand=require_brand(request.user,brand_id,review=request.method=='POST')
    gen=get_object_or_404(Generation,pk=generation_id,brand=brand)
    form=ReviewForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        services.review(gen,request.user,form.cleaned_data['action'],form.cleaned_data['notes'])
        messages.success(request,'Review decision recorded.')
        return redirect('generation',brand_id=brand.pk,generation_id=gen.pk)
    return render(request,'studio/generation.html',context(request,brand,title='Generation detail',generation=gen,form=form))

@login_required
@guarded
def regenerate(request,brand_id,generation_id):
    brand=require_brand(request.user,brand_id,write=True)
    gen=get_object_or_404(Generation,brand=brand,pk=generation_id)
    form=RegenerateForm(request.POST or None,instance=gen.concept,brand=brand)
    if request.method=='POST' and form.is_valid():
        fields=['product','character','category','location','pose','camera','composition','lighting','prompt']
        changes={name:form.cleaned_data[name] for name in fields}
        child=services.regenerate(gen,request.user,changes,mode=form.cleaned_data['mode'])
        return redirect('generation',brand_id=brand.pk,generation_id=child.pk)
    return render(request,'studio/form.html',context(request,brand,title='Regenerate · preserve the original',form=form,help='Creates a new concept and generation. Original prompts, references and images remain in history.'))

@login_required
@require_POST
@guarded
def retry_job(request,brand_id,generation_id):
    brand=require_brand(request.user,brand_id,write=True)
    gen=get_object_or_404(Generation,brand=brand,pk=generation_id)
    if request.POST.get('confirm')!='yes': raise ValidationError('Confirm you checked the remote provider for an existing result; retry may incur another charge.')
    updated=GenerationJob.objects.filter(generation=gen,status='FAILED').update(status='PLANNED',attempts=0,available_at=timezone.now(),error='')
    if not updated: raise ValidationError('Only failed jobs can be retried.')
    services.audit(brand,request.user,'job.retry_requested',gen)
    return redirect('generation',brand_id=brand.pk,generation_id=gen.pk)

@login_required
def calendar(request,brand_id):
    brand=require_brand(request.user,brand_id)
    entries=CalendarEntry.objects.filter(brand=brand).select_related('generation','concept__character','concept__product').order_by('date')
    return render(request,'studio/calendar.html',context(request,brand,title='Content calendar',entries=entries))

@login_required
def assets(request,brand_id):
    brand=require_brand(request.user,brand_id)
    return render(request,'studio/assets.html',context(request,brand,title='Asset library',assets=Asset.objects.filter(brand=brand).order_by('-created_at')))

@login_required
@guarded
def asset_file(request,brand_id,asset_id):
    brand=require_brand(request.user,brand_id)
    asset=get_object_or_404(Asset,pk=asset_id,brand=brand)
    response=HttpResponse(storage.read(asset.storage_key),content_type=asset.mime_type)
    response['Cache-Control']='private, no-store'
    if request.GET.get('download'):
        from django.utils.http import content_disposition_header
        response['Content-Disposition']=content_disposition_header(True,asset.original_filename)
    return response

@login_required
@require_POST
@guarded
def export_image(request,brand_id,generation_id):
    brand=require_brand(request.user,brand_id,review=True)
    gen=get_object_or_404(Generation,pk=generation_id,brand=brand)
    if gen.state not in ('APPROVED','READY_TO_POST') or not gen.output: raise ValidationError('Approve the completed image before exporting.')
    derivative=storage.instagram_derivative(gen.output)
    services.audit(brand,request.user,'asset.exported',derivative)
    return redirect(f'/brands/{brand.pk}/assets/{derivative.pk}/file/?download=1')

@login_required
def history(request,brand_id):
    brand=require_brand(request.user,brand_id,admin=True)
    return render(request,'studio/history.html',context(request,brand,title='Audit & usage',events=AuditEvent.objects.filter(brand=brand).order_by('-created_at')[:250],jobs=GenerationJob.objects.filter(brand=brand).order_by('-created_at')[:30],results=GenerationResult.objects.filter(brand=brand)))

@login_required
@require_POST
@guarded
def add_member(request,brand_id):
    from django.contrib.auth import get_user_model
    brand=require_brand(request.user,brand_id,admin=True)
    role=request.POST.get('role','VIEWER')
    if role not in ('ADMIN','EDITOR','REVIEWER','VIEWER'): raise ValidationError('Invalid role.')
    user=get_user_model().objects.filter(username=request.POST.get('username','')).first()
    if not user: raise ValidationError('No existing account with that username. Platform admins can create accounts in /admin/.')
    member,_=Membership.objects.update_or_create(brand=brand,user=user,defaults={'role':role})
    services.audit(brand,request.user,'membership.saved',member)
    return redirect('settings',brand_id=brand.pk)
