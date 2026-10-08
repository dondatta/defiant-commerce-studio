import io, json, tempfile
from datetime import timedelta, time
from unittest.mock import patch
from PIL import Image
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction, DatabaseError
from django.test import TestCase, override_settings, Client
from django.utils import timezone
from django.urls import reverse
from .models import *
from . import services, storage, shopify
from .providers import ProviderOutput, OpenAIProvider, ComfyUIProvider
from .network import ProviderHTTPError, validate_url

def image_bytes(color='navy'):
    buffer=io.BytesIO(); Image.new('RGB',(80,100),color).save(buffer,format='PNG'); return buffer.getvalue()

class StudioTests(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.override=override_settings(PRIVATE_STORAGE_ROOT=__import__('pathlib').Path(self.tmp.name))
        self.override.enable(); self.addCleanup(self.override.disable)
        User=get_user_model()
        self.user=User.objects.create_user('editor',password='test-password-good')
        self.viewer=User.objects.create_user('viewer',password='test-password-good')
        self.admin=User.objects.create_superuser('admin','admin@example.com','test-password-good')
        self.brand=Brand.objects.create(name='Test Fashion',slug='test-fashion')
        self.other=Brand.objects.create(name='Other Brand',slug='other-brand')
        Membership.objects.create(brand=self.brand,user=self.user,role='EDITOR')
        Membership.objects.create(brand=self.brand,user=self.viewer,role='VIEWER')
        self.prefs=BrandSettings.objects.create(brand=self.brand,daily_count=3,max_product_repeats=3,cooldown_days=0,minimum_spacing_days=0)
        BrandSettings.objects.create(brand=self.other)
        self.character=Character.objects.create(brand=self.brand,name='Adult persona',approved=True)
        self.other_character=Character.objects.create(brand=self.other,name='Private persona')
        self.ref=storage.make_asset(self.brand,image_bytes(),'face.png','character_reference','upload')
        CharacterReference.objects.create(brand=self.brand,character=self.character,asset=self.ref,role='face')
        self.product=Product.objects.create(brand=self.brand,shopify_id='100',title='Dress',retail_price='50')
        ProductImage.objects.create(brand=self.brand,product=self.product,shopify_id='200',url='https://cdn.shopify.com/test.png')
        self.categories=[ContentCategory.objects.create(brand=self.brand,name=name) for name in ('Style','Travel','Product')]
        self.config=ProviderConfig.objects.create(brand=self.brand,enabled=True)
        self.concept=ContentConcept.objects.create(brand=self.brand,product=self.product,character=self.character,category=self.categories[0],location='Cafe',pose='Walking')
        self.client.force_login(self.user)
        download_patch=patch('studio.network.download',return_value=image_bytes())
        download_patch.start(); self.addCleanup(download_patch.stop)
    def enqueue(self): return services.enqueue(self.concept,self.user)
    def completed(self):
        generation=self.enqueue()
        with patch('studio.providers.generate_image',return_value=ProviderOutput(image_bytes(),'remote-1',{})):
            self.assertTrue(services.run_one_job())
        return Generation.objects.get(pk=generation.pk)
    def test_brand_visibility_and_creation_permissions(self):
        self.assertContains(self.client.get('/brands/'),'Test Fashion')
        self.assertNotContains(self.client.get('/brands/'),'Other Brand')
        self.assertEqual(self.client.get('/brands/new/').status_code,403)
        self.assertEqual(self.client.get(f'/brands/{self.other.pk}/').status_code,404)
    def test_brand_create_update_and_deactivate(self):
        self.client.force_login(self.admin)
        response=self.client.post('/api/brands/',data=json.dumps({'name':'Third','slug':'third','timezone':'UTC','status':'ACTIVE'}),content_type='application/json')
        self.assertEqual(response.status_code,201,response.content)
        pk=response.json()['id']
        response=self.client.patch(f'/api/brands/{pk}/',data=json.dumps({'name':'Updated','status':'INACTIVE'}),content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(Brand.objects.get(pk=pk).status,'INACTIVE')
        self.assertEqual(AuditEvent.objects.filter(brand_id=pk).count(),2)
    def test_cross_brand_api_and_file_access(self):
        other_asset=storage.make_asset(self.other,image_bytes(),'secret.png','character_reference','upload')
        for url in (f'/api/brands/{self.other.pk}/products/',f'/brands/{self.other.pk}/assets/{other_asset.pk}/file/',f'/api/brands/{self.brand.pk}/characters/{self.other_character.pk}/'):
            self.assertEqual(self.client.get(url).status_code,404,url)
    def test_viewer_cannot_mutate_or_review(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(f'/brands/{self.brand.pk}/daily/').status_code,403)
        gen=self.completed()
        self.assertEqual(self.client.post(f'/brands/{self.brand.pk}/generations/{gen.pk}/',{'action':'APPROVED'}).status_code,403)
        self.assertEqual(self.client.get(f'/brands/{self.brand.pk}/settings/').status_code,403)
    def test_staff_admin_does_not_expose_other_tenants(self):
        self.user.is_staff=True; self.user.save()
        self.assertEqual(self.client.get('/admin/studio/brand/').status_code,403)
    def test_cross_brand_concept_post_rejected(self):
        response=self.client.post(f'/api/brands/{self.brand.pk}/concepts/',data=json.dumps({'product':self.product.pk,'character':self.other_character.pk,'category':self.categories[0].pk,'location':'Cafe','pose':'Walking','composition':'4:5','lighting':'Natural','camera':'Portrait','platform':'Instagram','content_format':'feed_image'}),content_type='application/json')
        self.assertEqual(response.status_code,400)
    def test_cross_brand_model_and_database_guards(self):
        with self.assertRaises(ValidationError): CharacterReference.objects.create(brand=self.other,character=self.other_character,asset=self.ref,role='face')
        with self.assertRaises(DatabaseError),transaction.atomic(): CharacterReference.objects.filter(character=self.character).update(character=self.other_character)
    def test_session_api_requires_csrf(self):
        client=Client(enforce_csrf_checks=True); client.force_login(self.user)
        self.assertEqual(client.post(f'/api/brands/{self.brand.pk}/actions/daily/',data='{}',content_type='application/json').status_code,403)
    def test_character_management_and_reference_upload(self):
        self.client.post(f'/brands/{self.brand.pk}/edit/character/',{'name':'New adult','description':'Adult reference-based character','conditioning':'{}','active':'on'})
        character=Character.objects.get(name='New adult',brand=self.brand)
        from django.core.files.uploadedfile import SimpleUploadedFile
        response=self.client.post(f'/brands/{self.brand.pk}/characters/{character.pk}/references/',{'role':'face','image':SimpleUploadedFile('ref.png',image_bytes(),content_type='image/png')})
        self.assertEqual(response.status_code,302,response.content)
        self.assertEqual(character.references.count(),1)
    def test_import_sync_and_duplicate_prevention(self):
        payload={'products':[{'id':'301','title':'Top','status':'active','images':[{'id':'302','src':'https://cdn.shopify.com/top.png'}],'variants':[{'id':'303','title':'Small','sku':'TOP-S','price':'25.00','inventory_quantity':3}],'collections':[{'id':'304','title':'New'}]}]}
        self.assertEqual(shopify.import_products(self.brand,payload,self.user),1)
        product=Product.objects.get(brand=self.brand,shopify_id='301')
        product.generation_eligible=False; product.save()
        payload['products'][0]['title']='Updated top'
        shopify.import_products(self.brand,payload,self.user)
        self.assertEqual(Product.objects.filter(brand=self.brand,shopify_id='301').count(),1)
        self.assertEqual(Variant.objects.filter(brand=self.brand,shopify_id='303').count(),1)
        product.refresh_from_db(); self.assertFalse(product.generation_eligible); self.assertEqual(product.title,'Updated top')
        shopify.import_products(self.other,payload,self.admin)
        self.assertEqual(Product.objects.filter(shopify_id='301').count(),2)
    def test_invalid_import_rolls_back(self):
        with self.assertRaises(ValidationError): shopify.import_products(self.brand,{'products':[{'id':'new','title':'Valid'},{'title':'Missing ID'}]})
        self.assertFalse(Product.objects.filter(shopify_id='new').exists())
    def test_prompt_components_are_tenant_scoped_and_editable(self):
        PromptComponent.objects.create(brand=self.brand,key='requirements',text='Show precise fabric texture')
        PromptComponent.objects.create(brand=self.other,key='requirements',text='PRIVATE OTHER BRAND')
        PromptTemplate.objects.create(brand=self.brand,name='Template',template='{brand_style}\n{character}\n{product}\n{requirements}')
        prompt,_=services.build_prompt(self.concept)
        self.assertIn('Show precise fabric texture',prompt); self.assertIn('Dress',prompt); self.assertNotIn('PRIVATE OTHER BRAND',prompt)
    def test_template_rejects_attribute_traversal(self):
        PromptTemplate.objects.create(brand=self.brand,name='Unsafe',template='{character.__class__}')
        with self.assertRaises(ValidationError): services.build_prompt(self.concept)
    def test_reference_prerequisites(self):
        self.character.approved=False; self.character.save()
        with self.assertRaises(ValidationError): self.enqueue()
        self.character.approved=True; self.character.save()
        self.character.references.all().delete()
        with self.assertRaises(ValidationError): self.enqueue()
    def test_exact_daily_count_variety_and_idempotency(self):
        batch,created=services.create_daily_batch(self.brand,self.user)
        self.assertTrue(created); self.assertEqual(batch.concepts.count(),3)
        concepts=list(batch.concepts.all())
        for field in ('category_id','location','pose'): self.assertEqual(len({getattr(c,field) for c in concepts}),3)
        self.assertEqual(Generation.objects.filter(concept__batch=batch).count(),3)
        duplicate,created=services.create_daily_batch(self.brand,self.user)
        self.assertFalse(created); self.assertEqual(duplicate.pk,batch.pk); self.assertEqual(GenerationJob.objects.count(),3)
        extra,created=services.create_daily_batch(self.brand,self.user,additional=True)
        self.assertTrue(created); self.assertEqual(extra.slot,1); self.assertEqual(GenerationJob.objects.count(),6)
    def test_batch_rotates_products_characters_and_framing(self):
        for i in range(2):
            product=Product.objects.create(brand=self.brand,shopify_id=f'extra-{i}',title=f'Extra product {i}')
            ProductImage.objects.create(brand=self.brand,product=product,shopify_id=f'extra-image-{i}',url='https://cdn.shopify.com/test.png')
            character=Character.objects.create(brand=self.brand,name=f'Adult {i}',approved=True)
            CharacterReference.objects.create(brand=self.brand,character=character,asset=self.ref,role='face')
        batch,_=services.create_daily_batch(self.brand,self.user)
        concepts=list(batch.concepts.all())
        for field in ('product_id','character_id','composition'):
            self.assertEqual(len({getattr(c,field) for c in concepts}),3)

    def test_insufficient_variety_is_atomic(self):
        self.prefs.preferred_locations='One'; self.prefs.save()
        with self.assertRaises(ValidationError): services.create_daily_batch(self.brand,self.user)
        self.assertEqual(DailyBatch.objects.count(),0); self.assertEqual(GenerationJob.objects.count(),0)
    def test_daily_mix_components(self):
        for i in range(1,4): PromptComponent.objects.create(brand=self.brand,key=f'daily_mix_{i}',text=f'Mix direction {i}')
        batch,_=services.create_daily_batch(self.brand,self.user)
        for i,concept in enumerate(batch.concepts.order_by('id'),1): self.assertEqual(concept.camera,f'Mix direction {i}')
    def test_product_repeat_limit(self):
        self.prefs.max_product_repeats=1; self.prefs.save()
        with self.assertRaises(ValidationError): services.create_daily_batch(self.brand,self.user)
    def test_cooldown_prevents_repeated_character_location(self):
        self.prefs.cooldown_days=3; self.prefs.save()
        services.create_daily_batch(self.brand,self.user)
        with self.assertRaises(ValidationError): services.create_daily_batch(self.brand,self.user,additional=True)
    def test_schedule_due_and_disabled_brands(self):
        self.assertEqual(services.schedule_due(),[])
        self.prefs.generation_enabled=True; self.prefs.generation_time=time(0); self.prefs.save()
        self.assertEqual(services.schedule_due(),[(self.brand.pk,'created')])
        self.assertEqual(services.schedule_due(),[(self.brand.pk,'existing')])
        self.assertEqual(DailyBatch.objects.get().source,'scheduled')
    def test_future_schedule_not_due(self):
        self.prefs.generation_enabled=True; self.prefs.generation_time=time(23,59); self.prefs.save()
        with patch('studio.services.timezone.now',return_value=timezone.datetime(2026,10,6,12,tzinfo=__import__('datetime').timezone.utc)):
            self.assertEqual(services.schedule_due(),[])
    def test_generation_snapshot_and_successful_persistence(self):
        gen=self.completed()
        self.assertEqual(gen.state,'NEEDS_REVIEW'); self.assertEqual(gen.output.width,80)
        self.assertEqual(gen.references.count(),2); self.assertEqual(gen.result.external_id,'remote-1')
        self.assertEqual(storage.read(gen.output.storage_key),image_bytes())
        self.assertFalse(services.run_one_job())
        self.assertEqual(GenerationResult.objects.count(),1)
    def test_generation_history_cannot_be_changed_or_deleted(self):
        gen=self.enqueue()
        gen.prompt='Changed'
        with self.assertRaises(ValidationError): gen.save()
        for operation in ('update','delete'):
            with self.assertRaises(DatabaseError),transaction.atomic():
                qs=Generation.objects.filter(pk=gen.pk)
                qs.update(prompt='Changed') if operation=='update' else qs.delete()
    def test_review_history_is_append_only(self):
        gen=self.completed(); decision=services.review(gen,self.user,'APPROVED','Keep this')
        with self.assertRaises(DatabaseError),transaction.atomic(): ReviewDecision.objects.filter(pk=decision.pk).update(notes='Hide previous choice')
    def test_approval_rejection_and_calendar(self):
        gen=self.completed()
        services.review(gen,self.user,'APPROVED','Great fit')
        self.assertEqual(gen.state,'APPROVED'); self.assertEqual(CalendarEntry.objects.count(),1)
        services.review(gen,self.user,'READY_TO_POST')
        self.assertEqual(gen.state,'READY_TO_POST')
        services.review(gen,self.user,'REJECTED','Anatomy issue')
        self.assertEqual(gen.state,'REJECTED'); self.assertEqual(CalendarEntry.objects.count(),0)
        self.assertEqual(gen.reviews.count(),3)
    def test_no_review_before_provider_completion(self):
        gen=self.enqueue()
        with self.assertRaises(ValidationError): services.review(gen,self.user,'APPROVED')
        self.assertFalse(CalendarEntry.objects.exists())
    def test_no_ready_to_post_before_approval(self):
        gen=self.completed()
        with self.assertRaises(ValidationError): services.review(gen,self.user,'READY_TO_POST')
    def test_regeneration_keeps_original(self):
        gen=self.completed(); original_prompt=gen.prompt; original_key=gen.output.storage_key
        child=services.regenerate(gen,self.user,{'pose':'Turn naturally'},mode='new_seed')
        gen.refresh_from_db()
        self.assertEqual(child.parent_id,gen.pk); self.assertEqual(child.concept.pose,'Turn naturally')
        self.assertEqual(gen.prompt,original_prompt); self.assertEqual(gen.output.storage_key,original_key)
        self.assertNotEqual(child.concept_id,gen.concept_id); self.assertIsNotNone(child.seed)
    def test_regeneration_removes_old_approval_from_calendar(self):
        gen=self.completed()
        services.review(gen,self.user,'APPROVED')
        self.assertTrue(CalendarEntry.objects.filter(generation=gen).exists())
        services.regenerate(gen,self.user)
        self.assertFalse(CalendarEntry.objects.filter(generation=gen).exists())
        self.assertEqual(gen.state,'REGENERATE')
        self.assertEqual(gen.reviews.filter(decision='APPROVED').count(),1)
        self.assertFalse(gen.output.approved)

    def test_regeneration_cross_brand_blocked(self):
        gen=self.enqueue()
        with self.assertRaises(ValidationError): services.regenerate(gen,self.user,{'character':self.other_character})
        self.assertEqual(Generation.objects.count(),1)
    def test_provider_failure_and_safe_retry(self):
        gen=self.enqueue()
        with patch('studio.providers.generate_image',side_effect=ProviderHTTPError(429)): services.run_one_job()
        gen.job.refresh_from_db(); self.assertEqual(gen.job.status,'PLANNED'); self.assertEqual(gen.job.attempts,1)
        self.assertGreater(gen.job.available_at,timezone.now()); self.assertFalse(services.run_one_job())
        GenerationJob.objects.filter(generation=gen).update(available_at=timezone.now())
        with patch('studio.providers.generate_image',return_value=ProviderOutput(image_bytes())): services.run_one_job()
        gen.job.refresh_from_db(); self.assertEqual(gen.job.status,'GENERATED'); self.assertEqual(gen.job.attempts,2)
        self.assertEqual(AuditEvent.objects.filter(action='generation.attempt_failed').count(),1)
    def test_nonretryable_provider_failure(self):
        gen=self.enqueue()
        with patch('studio.providers.generate_image',side_effect=ProviderHTTPError(401)): services.run_one_job()
        gen.job.refresh_from_db(); self.assertEqual(gen.job.status,'FAILED'); self.assertFalse(hasattr(gen,'result'))
    def test_retry_bound(self):
        gen=self.enqueue(); GenerationJob.objects.filter(generation=gen).update(attempts=2)
        with patch('studio.providers.generate_image',side_effect=ProviderHTTPError(429)): services.run_one_job()
        gen.job.refresh_from_db(); self.assertEqual(gen.job.status,'FAILED'); self.assertEqual(gen.job.attempts,3)
    def test_ambiguous_provider_failure_not_automatically_repeated(self):
        import requests
        gen=self.enqueue()
        with patch('studio.providers.generate_image',side_effect=requests.Timeout()): services.run_one_job()
        gen.job.refresh_from_db(); self.assertEqual(gen.job.status,'FAILED')
    def test_stale_lease_requires_manual_review(self):
        gen=self.enqueue()
        GenerationJob.objects.filter(generation=gen).update(status='GENERATING',locked_at=timezone.now()-timedelta(minutes=31))
        self.assertFalse(services.run_one_job())
        gen.job.refresh_from_db(); self.assertEqual(gen.job.status,'FAILED')
    def test_job_claim_not_repeated(self):
        gen=self.enqueue(); first=services.claim_job()
        self.assertIsNotNone(first); self.assertIsNone(services.claim_job()); self.assertEqual(first.attempts,1)
    def test_instagram_export_preserves_original_and_approval(self):
        gen=self.completed()
        response=self.client.post(f'/brands/{self.brand.pk}/generations/{gen.pk}/export/')
        self.assertEqual(response.status_code,400)
        services.review(gen,self.user,'APPROVED')
        original=storage.read(gen.output.storage_key)
        derivative=storage.instagram_derivative(gen.output)
        self.assertEqual((derivative.width,derivative.height),(1080,1350))
        self.assertEqual(storage.read(gen.output.storage_key),original)
        self.assertEqual(storage.instagram_derivative(gen.output).pk,derivative.pk)
        response=self.client.get(f'/brands/{self.brand.pk}/assets/{derivative.pk}/file/?download=1')
        self.assertEqual(response.status_code,200); self.assertEqual(response['Cache-Control'],'private, no-store')
    def test_original_asset_metadata_cannot_be_replaced(self):
        gen=self.completed()
        with self.assertRaises(DatabaseError),transaction.atomic(): Asset.objects.filter(pk=gen.output.pk).update(storage_key='brands/2/secret.png')
    def test_network_blocks_private_destinations(self):
        for url in ('http://127.0.0.1/test','https://169.254.169.254/','https://user:password@example.com/'):
            with self.assertRaises(ValidationError): validate_url(url)
    def test_ui_pages_and_real_data(self):
        gen=self.completed()
        for route in ('workspace','products','characters','concepts','queue','calendar','assets'):
            response=self.client.get(reverse(route,args=[self.brand.pk])); self.assertEqual(response.status_code,200,(route,response.content[:200]))
        self.assertContains(self.client.get(reverse('queue',args=[self.brand.pk])),'Dress')
        self.assertEqual(self.client.get(reverse('generation',args=[self.brand.pk,gen.pk])).status_code,200)
        self.assertEqual(self.client.get(reverse('regenerate',args=[self.brand.pk,gen.pk])).status_code,200)
        self.client.force_login(self.admin)
        for route in ('settings','history'): self.assertEqual(self.client.get(reverse(route,args=[self.brand.pk])).status_code,200)
    def test_reviewer_can_review_but_not_generate(self):
        Membership.objects.filter(brand=self.brand,user=self.viewer).update(role='REVIEWER')
        self.client.force_login(self.viewer)
        gen=self.completed()
        response=self.client.post(f'/api/brands/{self.brand.pk}/actions/review/{gen.pk}/',data=json.dumps({'decision':'APPROVED','notes':'Reviewed'}),content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(self.client.post(f'/api/brands/{self.brand.pk}/actions/daily/',data='{}',content_type='application/json').status_code,403)

    def test_product_reference_snapshot_is_reused_and_immutable(self):
        gen=self.enqueue()
        with patch('studio.network.download',return_value=image_bytes('blue')) as download:
            services.resolve_references(gen)
            services.resolve_references(gen)
        self.assertEqual(download.call_count,1)
        snapshot=ResolvedReference.objects.get(reference__generation=gen)
        self.assertEqual(storage.read(snapshot.asset.storage_key),image_bytes('blue'))
        with self.assertRaises(DatabaseError),transaction.atomic():
            ResolvedReference.objects.filter(pk=snapshot.pk).update(asset=self.ref)
    def test_edit_calendar_preserves_generation(self):
        gen=self.completed(); services.review(gen,self.user,'APPROVED')
        entry=CalendarEntry.objects.get(generation=gen)
        response=self.client.post(f'/brands/{self.brand.pk}/edit/calendar/{entry.pk}/',{'date':'2026-10-09','platform':'Instagram','notes':'Launch day','intended_posting_time':'2026-10-09T14:00'})
        self.assertEqual(response.status_code,302,response.content)
        entry.refresh_from_db(); self.assertEqual(str(entry.date),'2026-10-09'); self.assertEqual(entry.generation_id,gen.pk)
    def test_seed_configuration_is_idempotent_and_preserves_edits(self):
        from django.core.management import call_command
        call_command('seed_studio',stdout=io.StringIO())
        seeded=Brand.objects.get(slug='infatuation-apparel')
        seeded.brand_voice='Custom voice'; seeded.save()
        call_command('seed_studio',stdout=io.StringIO())
        seeded.refresh_from_db(); self.assertEqual(seeded.brand_voice,'Custom voice')
        self.assertEqual(Character.objects.filter(brand=seeded,name='Nyla').count(),1)
        self.assertEqual(seeded.preferences.daily_count,3)
    def test_shopify_graphql_sync_mapping_and_idempotency(self):
        from unittest.mock import Mock
        store=ShopifyStore.objects.create(brand=self.brand,domain='test-fashion.myshopify.com',token_env='SHOPIFY_TEST_TOKEN')
        connection=lambda nodes:{'nodes':nodes,'pageInfo':{'hasNextPage':False}}
        row={'id':'gid://shopify/Product/800','title':'Synced dress','descriptionHtml':'A dress','status':'ACTIVE','handle':'synced-dress','onlineStoreUrl':None,'images':connection([{'id':'gid://shopify/MediaImage/801','url':'https://cdn.shopify.com/dress.png','altText':'Dress'}]),'collections':connection([{'id':'gid://shopify/Collection/802','title':'Best sellers'}]),'variants':connection([{'id':'gid://shopify/ProductVariant/803','title':'Small','sku':'SYNC-S','price':'75.00','inventoryQuantity':4,'availableForSale':True}])}
        response=Mock(); response.json.return_value={'data':{'products':{**connection([row]),'pageInfo':{'hasNextPage':False,'endCursor':None}}}}
        with patch.dict('os.environ',{'SHOPIFY_TEST_TOKEN':'test-only'}),patch('studio.shopify.request',return_value=response):
            self.assertEqual(shopify.sync_shopify(self.brand,self.user),1)
            self.assertEqual(shopify.sync_shopify(self.brand,self.user),1)
        product=Product.objects.get(brand=self.brand,shopify_id=row['id'])
        self.assertEqual(product.variants.get().inventory_quantity,4)
        self.assertEqual(product.collections.get().title,'Best sellers')
        store.refresh_from_db(); self.assertIsNotNone(store.last_sync_at)

class ProviderAdapterTests(TestCase):
    setUp = StudioTests.setUp
    enqueue = StudioTests.enqueue
    def test_openai_uses_actual_reference_bytes(self):
        gen=self.enqueue()
        services.resolve_references(gen)
        import base64
        response=__import__('unittest.mock',fromlist=['Mock']).Mock()
        response.json.return_value={'created':123,'data':[{'b64_json':base64.b64encode(image_bytes()).decode()}],'usage':{}}
        with patch.dict('os.environ',{'DEFIANT_IMAGE_API_KEY':'test-only'}),patch('studio.network.download',return_value=image_bytes()),patch('studio.network.request',return_value=response) as request:
            output=OpenAIProvider().generate_image(gen,self.config)
        self.assertEqual(output.data,image_bytes())
        args,kwargs=request.call_args
        self.assertEqual(args[1],'https://api.openai.com/v1/images/edits')
        self.assertEqual(len(kwargs['files']),2)
        self.assertIn('reference',kwargs['data']['prompt'])
    def test_comfyui_maps_references_seed_and_workflow(self):
        gen=self.enqueue()
        # New immutable snapshot with an explicitly mapped workflow.
        settings={'workflow':{'1':{'inputs':{}},'2':{'inputs':{}},'3':{'inputs':{}}},'inputs':{'prompt':{'node':'1','input':'text'},'face':{'node':'2','input':'image'},'clothing':{'node':'3','input':'image'}}}
        GenerationJob.objects.filter(generation=gen).update(status='FAILED')
        self.config.kind='comfyui'; self.config.endpoint='https://comfy.example.com'; self.config.settings=settings; self.config.save()
        child=services.regenerate(gen,self.user)
        services.resolve_references(child)
        from unittest.mock import Mock
        responses=[Mock(),Mock(),Mock(),Mock(),Mock()]
        responses[0].json.return_value={'name':'face.png'}
        responses[1].json.return_value={'name':'clothing.png'}
        responses[2].json.return_value={'prompt_id':'job-1'}
        responses[3].json.return_value={'job-1':{'outputs':{'save':{'images':[{'filename':'out.png','subfolder':'','type':'output'}]}}}}
        responses[4].content=image_bytes()
        with patch('studio.network.validate_url'),patch('studio.network.download',return_value=image_bytes()),patch('studio.network.request',side_effect=responses) as request:
            output=ComfyUIProvider().generate_image(child,self.config)
        self.assertEqual(output.data,image_bytes())
        workflow=request.call_args_list[2].kwargs['json']['prompt']
        self.assertEqual(workflow['2']['inputs']['image'],'face.png'); self.assertEqual(workflow['3']['inputs']['image'],'clothing.png')
