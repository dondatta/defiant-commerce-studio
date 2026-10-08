import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from studio.services import schedule_due
class Command(BaseCommand):
    help='Enqueue due brand-local daily batches without duplicate submissions.'
    def add_arguments(self,parser): parser.add_argument('--once',action='store_true')
    def handle(self,*args,**options):
        while True:
            close_old_connections()
            for brand_id,outcome in schedule_due(): self.stdout.write(f'Brand {brand_id}: {outcome}')
            if options['once']: return
            time.sleep(30)
