from django.contrib import admin
from django.apps import apps
from .models import Generation, GenerationResult, AuditEvent, ReviewDecision, GenerationReference, ResolvedReference
class PlatformOnlyAdmin(admin.ModelAdmin):
    def has_module_permission(self,request): return request.user.is_superuser
    def has_view_permission(self,request,obj=None): return request.user.is_superuser
    def has_add_permission(self,request): return request.user.is_superuser
    def has_change_permission(self,request,obj=None): return request.user.is_superuser
    def has_delete_permission(self,request,obj=None): return False
    def save_model(self,request,obj,form,change):
        super().save_model(request,obj,form,change)
        from .models import Brand
        from .services import audit
        brand = obj if isinstance(obj,Brand) else getattr(obj,'brand',None)
        if brand: audit(brand,request.user,'admin.record_saved',obj,{'changed_fields':form.changed_data})
class HistoryAdmin(PlatformOnlyAdmin):
    def has_add_permission(self,request): return False
    def has_change_permission(self,request,obj=None): return False
for model in apps.get_app_config('studio').get_models():
    admin.site.register(model,HistoryAdmin if model in (Generation,GenerationResult,AuditEvent,ReviewDecision,GenerationReference,ResolvedReference) else PlatformOnlyAdmin)
admin.site.site_header='Defiant · Platform administration'
