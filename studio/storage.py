import io, uuid
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from django.conf import settings
from django.core.exceptions import ValidationError

def validate_image(data):
    if len(data) > 20 * 1024 * 1024: raise ValidationError('Images must be under 20 MB.')
    try:
        image = Image.open(io.BytesIO(data))
        image.verify()
        image = Image.open(io.BytesIO(data))
        if image.width * image.height > 40_000_000: raise ValidationError('Image dimensions exceed 40 megapixels.')
        return image.width, image.height, Image.MIME[image.format], image.format.lower()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValidationError('Upload a valid PNG, JPEG or WebP image.') from exc

def put(brand_id, folder, data, extension):
    key = f'brands/{brand_id}/{folder}/{uuid.uuid4()}.{extension}'
    if settings.STORAGE_BACKEND == 's3':
        import boto3
        boto3.client('s3',region_name=settings.S3_REGION,endpoint_url=settings.S3_ENDPOINT_URL).put_object(Bucket=settings.S3_BUCKET,Key=key,Body=data)
    else:
        path = settings.PRIVATE_STORAGE_ROOT / key
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data)
    return key

def read(key):
    if not key.startswith('brands/') or '..' in Path(key).parts: raise ValidationError('Invalid storage key.')
    if settings.STORAGE_BACKEND == 's3':
        import boto3
        return boto3.client('s3',region_name=settings.S3_REGION,endpoint_url=settings.S3_ENDPOINT_URL).get_object(Bucket=settings.S3_BUCKET,Key=key)['Body'].read()
    path = (settings.PRIVATE_STORAGE_ROOT / key).resolve()
    if not path.is_relative_to(settings.PRIVATE_STORAGE_ROOT.resolve()): raise ValidationError('Invalid storage key.')
    return path.read_bytes()

def make_asset(brand,data,filename,asset_type,source,**kwargs):
    from .models import Asset
    width,height,mime,ext = validate_image(data)
    folder = 'exports' if asset_type == 'instagram_export' else ('generations' if asset_type == 'generated_image' else 'references')
    key = put(brand.pk,folder,data,ext)
    return Asset.objects.create(brand=brand,storage_key=key,original_filename=Path(filename).name[:200],width=width,height=height,mime_type=mime,asset_type=asset_type,source=source,**kwargs)

def instagram_derivative(asset):
    from .models import Asset
    existing = Asset.objects.filter(original=asset,asset_type='instagram_export').first()
    if existing: return existing
    original = Image.open(io.BytesIO(read(asset.storage_key)))
    # Pad rather than crop: preserve the garment and every part of the original.
    image = ImageOps.pad(ImageOps.exif_transpose(original).convert('RGB'),(1080,1350),color='#f2f0eb')
    buffer = io.BytesIO()
    image.save(buffer,format='JPEG',quality=95)
    return make_asset(asset.brand,buffer.getvalue(),'instagram-1080x1350.jpg','instagram_export','derivative',generation=asset.generation,original=asset,approved=True)
