"""Local browser smoke check. Temporary login account is removed at completion."""
import os, sys, secrets
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django
django.setup()
from django.contrib.auth import get_user_model
from studio.models import Brand
from playwright.sync_api import sync_playwright
password=secrets.token_urlsafe(30)
user=get_user_model().objects.create_superuser('browser-check-'+secrets.token_hex(5),'check@example.invalid',password)
brand=Brand.objects.order_by('id').first()
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
        page=browser.new_page(viewport={'width':1440,'height':1100})
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('http://127.0.0.1:8000/login/')
        page.locator('[name=username]').fill(user.username)
        page.locator('[name=password]').fill(password)
        page.get_by_role('button',name='Sign in').click()
        page.wait_for_url('**/brands/')
        page.screenshot(path='/tmp/defiant-brands.png',full_page=True)
        for route in ('','products/','characters/','concepts/','queue/','calendar/','assets/','settings/','history/','edit/provider/','edit/concept/','edit/character/'):
            response=page.goto(f'http://127.0.0.1:8000/brands/{brand.pk}/{route}')
            assert response.status==200,(route,response.status)
            assert page.locator('body').inner_text()
        page.goto(f'http://127.0.0.1:8000/brands/{brand.pk}/')
        page.screenshot(path='/tmp/defiant-workspace.png',full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path='/tmp/defiant-mobile.png',full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile horizontal overflow'
        assert not errors,errors
        browser.close()
        print('Browser login, 12 workspace routes, desktop/mobile layouts and JavaScript checks passed.')
finally:
    user.delete()
