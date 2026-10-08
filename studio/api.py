"""Session-authenticated JSON API. Unsafe methods retain Django CSRF enforcement."""
import json
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.views.decorators.http import require_http_methods
from .models import *
from .forms import BrandForm, CharacterForm, ConceptForm, ProviderForm, SettingsForm, ShopifyForm
from .permissions import brands_for, require_brand
from .services import audit, enqueue, review, regenerate, create_daily_batch, build_prompt
from .shopify import import_products, sync_shopify
from .views import guarded

def payload(request):
    try: data=json.loads(request.body or b'{}')
    except json.JSONDecodeError: raise ValidationError('Expected valid JSON.')
    if not isinstance(data,dict): raise ValidationError('Expected a JSON object.')
    return data

def serialize(obj):
    result={}
    for f in obj._meta.concrete_fields:
        value=getattr(obj,f.attname)
        if hasattr(value,'isoformat'): value=value.isoformat()
        if f.name in ('id','parent') or f.get_internal_type() in ('DecimalField','UUIDField'): value=str(value) if value is not None else None
        result[f.attname]=value
    if isinstance(obj,Generation):
        result['status']=obj.state
        result['output_asset_id']=obj.output.pk if obj.output else None
    return result

@login_required
@require_http_methods(['GET','POST','PATCH'])
@guarded
def brands_api(request,brand_id=None):
    if request.method=='GET':
        if brand_id: return JsonResponse(serialize(require_brand(request.user,brand_id)))
        return JsonResponse({'brands':[serialize(b) for b in brands_for(request.user)]})
    if brand_id: instance=require_brand(request.user,brand_id,admin=True)
    else:
        if not request.user.is_superuser: raise PermissionDenied
        instance=Brand()
    data=payload(request)
    if request.method=='PATCH': data={**{f.name:getattr(instance,f.name) for f in instance._meta.fields if f.name!='id'},**data}
    form=BrandForm(data,instance=instance)
    if not form.is_valid(): return JsonResponse({'errors':form.errors.get_json_data()},status=400)
    with transaction.atomic():
        obj=form.save()
        BrandSettings.objects.get_or_create(brand=obj)
        audit(obj,request.user,'brand.saved',obj)
    return JsonResponse(serialize(obj),status=201 if not brand_id else 200)

@login_required
@require_http_methods(['GET','POST','PATCH'])
@guarded
def resource(request,brand_id,kind,record_id=None):
    resources={'products':Product,'characters':Character,'concepts':ContentConcept,'generations':Generation,'categories':ContentCategory,'assets':Asset,'calendar':CalendarEntry,'audit':AuditEvent,'batches':DailyBatch,'settings':BrandSettings,'provider':ProviderConfig,'shopify':ShopifyStore}
    if kind not in resources: raise Http404
    admin=kind in ('settings','provider','shopify','audit')
    brand=require_brand(request.user,brand_id,write=request.method!='GET' and not admin,admin=admin)
    model=resources[kind]
    if request.method=='GET':
        if record_id: return JsonResponse(serialize(get_object_or_404(model,brand=brand,pk=record_id)))
        return JsonResponse({'results':[serialize(row) for row in model.objects.filter(brand=brand).order_by('-created_at')[:500]]})
    forms={'characters':CharacterForm,'concepts':ConceptForm,'settings':SettingsForm,'provider':ProviderForm,'shopify':ShopifyForm}
    if kind not in forms: return JsonResponse({'error':'This resource is read-only; use an action endpoint.'},status=405)
    instance=get_object_or_404(model,brand=brand,pk=record_id) if record_id else model(brand=brand)
    data=payload(request)
    if request.method=='PATCH': data={**{f.name:getattr(instance,f.attname) for f in instance._meta.fields if f.name not in ('id','brand')},**data}
    kwargs={'instance':instance}
    if kind=='concepts': kwargs['brand']=brand
    form=forms[kind](data,**kwargs)
    if not form.is_valid(): return JsonResponse({'errors':form.errors.get_json_data()},status=400)
    obj=form.save(commit=False)
    if kind=='concepts': obj.created_by=request.user
    obj.save()
    audit(brand,request.user,kind+'.saved',obj)
    return JsonResponse(serialize(obj),status=201)

@login_required
@require_http_methods(['POST'])
@guarded
def action(request,brand_id,kind,record_id=None):
    brand=require_brand(request.user,brand_id,admin=kind=='sync',review=kind=='review',write=kind not in ('sync','review'))
    data=payload(request)
    if kind=='import': return JsonResponse({'count':import_products(brand,data,request.user)})
    if kind=='sync': return JsonResponse({'count':sync_shopify(brand,request.user)})
    if kind=='daily':
        batch,created=create_daily_batch(brand,request.user,additional=data.get('confirm_additional') is True)
        return JsonResponse({'batch':serialize(batch),'created':created})
    if kind in ('generate','prompt'):
        concept=get_object_or_404(ContentConcept,brand=brand,pk=record_id)
        if kind=='prompt':
            prompt,negative=build_prompt(concept)
            return JsonResponse({'prompt':prompt,'negative_prompt':negative})
        return JsonResponse(serialize(enqueue(concept,request.user,idempotency_key=f'concept:{concept.pk}:initial')),status=202)
    if kind in ('review','regenerate'):
        gen=get_object_or_404(Generation,brand=brand,pk=record_id)
        if kind=='review': return JsonResponse(serialize(review(gen,request.user,data['decision'],data.get('notes',''))))
        changes=data.get('changes',{})
        if not isinstance(changes,dict): raise ValidationError('changes must be an object.')
        for key,model in [('product',Product),('character',Character),('category',ContentCategory)]:
            if key in changes: changes[key]=get_object_or_404(model,brand=brand,pk=changes[key])
        return JsonResponse(serialize(regenerate(gen,request.user,changes,mode=data.get('mode','same'))),status=202)
    raise Http404
