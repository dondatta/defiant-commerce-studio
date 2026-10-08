"""Provider boundary: immutable inputs in, original image bytes + metadata out."""
import base64, os, time, uuid
from dataclasses import dataclass
from urllib.parse import quote
from django.core.exceptions import ValidationError
from . import network, storage

@dataclass
class ProviderOutput:
    data: bytes
    external_id: str = ''
    metadata: dict = None
    cost: float | None = None

def reference_bytes(ref):
    if ref.asset_id: return storage.read(ref.asset.storage_key)
    if hasattr(ref, 'snapshot'): return storage.read(ref.snapshot.asset.storage_key)
    raise ValidationError('Product references must be snapshotted by the worker before provider submission.')

class OpenAIProvider:
    def generate_image(self,generation,config):
        key = os.getenv(generation.provider_settings.get("credential_env", config.credential_env))
        if not key: raise ValidationError(f'Missing credential binding: {config.credential_env}.')
        refs = list(generation.references.all())
        images = []
        for ref in refs:
            data = reference_bytes(ref)
            storage.validate_image(data)
            images.append((f'{ref.role}-{len(images)}.png',data))
        prompt = generation.prompt + '\nExclude: ' + generation.negative_prompt
        payload = {'model':generation.provider_model,'prompt':prompt,'n':1,'size':generation.provider_settings.get('size','1024x1536'),'quality':generation.provider_settings.get('quality','medium')}
        headers = {'Authorization':f'Bearer {key}','Idempotency-Key':str(generation.pk)}
        if images:
            files = [('image[]',(name,data,storage.validate_image(data)[2])) for name,data in images]
            response = network.request('POST','https://api.openai.com/v1/images/edits',headers=headers,data=payload,files=files)
        else:
            response = network.request('POST','https://api.openai.com/v1/images/generations',headers=headers,json=payload)
        body = response.json()
        output = body['data'][0]
        data = base64.b64decode(output['b64_json']) if output.get('b64_json') else network.download(output['url'])
        return ProviderOutput(data,str(body.get('created','')),{'usage':body.get('usage',{}),'revised_prompt':output.get('revised_prompt','')})

class ComfyUIProvider:
    def generate_image(self,generation,config):
        base = generation.provider_settings.get('endpoint',config.endpoint).rstrip('/')
        if not base: raise ValidationError('Configure a ComfyUI endpoint.')
        network.validate_url(base,allow_local=True)
        headers = {}
        if config.credential_env:
            token = os.getenv(generation.provider_settings.get('credential_env',config.credential_env))
            if token: headers['Authorization'] = f'Bearer {token}'
        workflow = generation.provider_settings.get('workflow')
        mapping = generation.provider_settings.get('inputs',{})
        if not workflow or not mapping: raise ValidationError('Configure an API-format ComfyUI workflow and input mappings.')
        import copy
        workflow = copy.deepcopy(workflow)
        def assign(name,value):
            spec = mapping.get(name)
            if spec: workflow[str(spec['node'])]['inputs'][spec['input']] = value
        assign('prompt',generation.prompt)
        assign('negative_prompt',generation.negative_prompt)
        assign('seed',generation.seed if generation.seed is not None else uuid.uuid4().int % (2**32))
        assign('lora',generation.provider_settings.get('lora_model_id',''))
        conditioning = generation.provider_settings.get('conditioning',{})
        for name,value in conditioning.items(): assign(name,value)
        ref_counts = {}
        for ref in generation.references.all():
            data = reference_bytes(ref)
            storage.validate_image(data)
            uploaded = network.request('POST',base+'/upload/image',allow_local=True,headers=headers,files={'image':(f'{generation.pk}-{ref.pk}.png',data,storage.validate_image(data)[2])},data={'type':'input','overwrite':'false'}).json()
            index = ref_counts.get(ref.role,0)
            mapping_name = f'{ref.role}_{index}' if index else ref.role
            if mapping_name not in mapping: raise ValidationError(f'Workflow needs a reference input mapping for {mapping_name}.')
            assign(mapping_name,uploaded['name'])
            ref_counts[ref.role] = index + 1
        from .models import AuditEvent
        from .services import audit
        submitted = AuditEvent.objects.filter(brand=generation.brand, object_id=str(generation.pk), action='provider.comfyui_submitted').order_by('id').first()
        if submitted:
            prompt_id = submitted.details['prompt_id']
        else:
            response = network.request('POST',base+'/prompt',allow_local=True,headers=headers,json={'prompt':workflow,'client_id':str(generation.pk)}).json()
            prompt_id = response['prompt_id']
            audit(generation.brand,None,'provider.comfyui_submitted',generation,{'prompt_id':prompt_id})
        for _ in range(120):
            history = network.request('GET',base+'/history/'+quote(prompt_id,safe=''),allow_local=True,headers=headers).json()
            result = history.get(prompt_id)
            if result:
                if result.get('status',{}).get('status_str') == 'error': raise ValidationError('ComfyUI workflow failed. Inspect its server logs.')
                for output in result.get('outputs',{}).values():
                    if output.get('images'):
                        image = output['images'][0]
                        data = network.request('GET',base+'/view',allow_local=True,headers=headers,params=image).content
                        return ProviderOutput(data,prompt_id,{'workflow_prompt_id':prompt_id})
            time.sleep(2)
        raise ValidationError('ComfyUI did not complete within four minutes. Inspect the remote job before retrying.')

PROVIDERS = {'openai':OpenAIProvider,'comfyui':ComfyUIProvider}

def generate_image(generation,config):
    if generation.provider not in PROVIDERS: raise ValidationError('Unsupported provider.')
    return PROVIDERS[generation.provider]().generate_image(generation,config)
