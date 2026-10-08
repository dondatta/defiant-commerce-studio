import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from studio.services import run_one_job
class Command(BaseCommand):
    help='Process queued image jobs. PostgreSQL supports concurrent workers; SQLite development uses one worker.'
    def add_arguments(self,parser):
        parser.add_argument('--once',action='store_true')
        parser.add_argument('--poll',type=float,default=2)
    def handle(self,*args,**options):
        while True:
            close_old_connections()
            worked=run_one_job()
            if options['once']: return
            if not worked: time.sleep(max(options['poll'],.5))
