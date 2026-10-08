import json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from studio.models import Brand, BrandSettings, Character, ContentCategory, PromptComponent, PromptTemplate
class Command(BaseCommand):
    help='Idempotently load tenant configuration data. Existing tenant edits are preserved; no users or generated assets are created.'
    def add_arguments(self,parser):
        parser.add_argument('--file',default=str(Path(__file__).resolve().parents[2]/'seed_data'/'default-brand.json'))
    @transaction.atomic
    def handle(self,*args,**options):
        with open(options['file']) as file: data=json.load(file)
        slug=data['brand']['slug']
        brand,created=Brand.objects.get_or_create(slug=slug,defaults=data['brand'])
        if created:
            from studio.services import audit
            audit(brand,None,'brand.created',brand,{'source':'seed_configuration'})
        BrandSettings.objects.get_or_create(brand=brand,defaults=data.get('settings',{}))
        for key,model,identity in [('characters',Character,'name'),('categories',ContentCategory,'name'),('components',PromptComponent,'key'),('templates',PromptTemplate,'name')]:
            for record in data.get(key,[]): model.objects.get_or_create(brand=brand,**{identity:record[identity]},defaults=record)
        self.stdout.write(self.style.SUCCESS(f'{brand.name}: '+('created' if created else 'existing data preserved')))
