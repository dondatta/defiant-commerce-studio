from django.http import Http404
from django.core.exceptions import PermissionDenied
from .models import Brand, Membership

def brands_for(user):
    if user.is_superuser: return Brand.objects.all()
    return Brand.objects.filter(membership__user=user).distinct()

def require_brand(user,brand_id,write=False,admin=False,review=False):
    try: brand = brands_for(user).get(pk=brand_id)
    except Brand.DoesNotExist: raise Http404('Brand not found.')
    if user.is_superuser: return brand
    role = Membership.objects.get(user=user,brand=brand).role
    if admin and role != 'ADMIN': raise PermissionDenied
    if write and role not in ('ADMIN','EDITOR'): raise PermissionDenied
    if review and role not in ('ADMIN','EDITOR','REVIEWER'): raise PermissionDenied
    return brand
