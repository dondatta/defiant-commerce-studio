import os, re
from decimal import Decimal, InvalidOperation
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .models import Product, Variant, ProductImage, Collection, ProductCollection
from .services import audit
from .network import request

def external_id(value,label):
    if value is None or str(value).strip() == '': raise ValidationError(f'{label} requires a Shopify ID.')
    return str(value)

@transaction.atomic
def import_products(brand,payload,actor=None):
    rows=payload.get('products') if isinstance(payload,dict) else payload
    if not isinstance(rows,list) or len(rows)>10000: raise ValidationError('Upload a JSON products array (maximum 10,000 records).')
    count=0
    for row in rows:
        if not isinstance(row,dict): raise ValidationError('Each product must be an object.')
        product_id=external_id(row.get('id'),'Product')
        title=str(row.get('title','')).strip()
        if not title: raise ValidationError('Each product needs a title.')
        variants=row.get('variants',[])
        first=variants[0] if variants else {}
        try: price=Decimal(str(first.get('price',row.get('price','0'))))
        except InvalidOperation as exc: raise ValidationError('Product price must be a decimal.') from exc
        if not price.is_finite() or price<0: raise ValidationError('Product price must be finite and nonnegative.')
        status=str(row.get('status','active')).lower()
        defaults={'title':title,'description':row.get('body_html',row.get('description','')),'sku':first.get('sku','') or '', 'retail_price':price,'status':status,'active':status=='active','product_url':row.get('url',''),'currency':row.get('currency','USD')}
        product,created=Product.objects.update_or_create(brand=brand,shopify_id=product_id,defaults=defaults)
        variant_ids=[]
        for v in variants:
            vid=external_id(v.get('id'),'Variant'); variant_ids.append(vid)
            try: variant_price=Decimal(str(v.get('price',price)))
            except InvalidOperation as exc: raise ValidationError('Variant price must be a decimal.') from exc
            if not variant_price.is_finite() or variant_price<0: raise ValidationError('Invalid variant price.')
            inventory=v.get('inventory_quantity')
            Variant.objects.update_or_create(brand=brand,shopify_id=vid,defaults={'product':product,'title':v.get('title','Default'),'sku':v.get('sku','') or '', 'price':variant_price,'inventory_quantity':inventory,'available':v.get('available',inventory is None or inventory>0)})
        Variant.objects.filter(product=product).exclude(shopify_id__in=variant_ids).delete()
        image_ids=[]
        for i,image in enumerate(row.get('images',[])):
            iid=external_id(image.get('id'),'Image'); image_ids.append(iid)
            url=image.get('src',image.get('url',''))
            if not url.startswith('https://'): raise ValidationError('Product images must use HTTPS.')
            ProductImage.objects.update_or_create(brand=brand,shopify_id=iid,defaults={'product':product,'url':url,'alt':image.get('alt','') or '', 'position':i})
        ProductImage.objects.filter(product=product).exclude(shopify_id__in=image_ids).delete()
        collection_ids=[]
        for item in row.get('collections',[]):
            cid=external_id(item.get('id'),'Collection')
            collection,_=Collection.objects.update_or_create(brand=brand,shopify_id=cid,defaults={'title':item.get('title','Untitled')})
            ProductCollection.objects.get_or_create(brand=brand,product=product,collection=collection)
            collection_ids.append(collection.pk)
        ProductCollection.objects.filter(product=product).exclude(collection_id__in=collection_ids).delete()
        count+=1
    audit(brand,actor,'shopify.imported',brand,{'count':count})
    return count

QUERY='''query Products($cursor: String) {
 products(first: 50, after: $cursor) {
  pageInfo { hasNextPage endCursor }
  nodes { id title descriptionHtml status handle onlineStoreUrl
   images(first: 100) { pageInfo {hasNextPage} nodes { id url altText } }
   collections(first: 100) { pageInfo {hasNextPage} nodes { id title } }
   variants(first: 100) { pageInfo {hasNextPage} nodes { id title sku price inventoryQuantity availableForSale } }
  }
 }
}'''

def sync_shopify(brand,actor=None):
    store=brand.shopify
    domain=store.domain.strip().lower()
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]*\.myshopify\.com',domain): raise ValidationError('Use the canonical store-name.myshopify.com domain.')
    if not re.fullmatch(r'20\d\d-(01|04|07|10)',store.api_version): raise ValidationError('Invalid Shopify API version.')
    token=os.getenv(store.token_env)
    if not token: raise ValidationError(f'Missing Shopify binding: {store.token_env or "configure token_env"}.')
    rows=[]; cursor=None
    for _ in range(200):
        body=request('POST',f'https://{domain}/admin/api/{store.api_version}/graphql.json',headers={'X-Shopify-Access-Token':token},json={'query':QUERY,'variables':{'cursor':cursor}}).json()
        if body.get('errors'): raise ValidationError('Shopify GraphQL rejected the query. Verify read_products and inventory permissions in the store app.')
        connection=body['data']['products']
        for row in connection['nodes']:
            if any(row[field]['pageInfo']['hasNextPage'] for field in ('images','collections','variants')):
                raise ValidationError('A product exceeds 100 images, collections or variants; use a complete manual JSON import for this catalog. No partial sync was saved.')
            rows.append({'id':row['id'],'title':row['title'],'body_html':row['descriptionHtml'],'status':row['status'].lower(),'url':row['onlineStoreUrl'] or f'https://{domain}/products/{row["handle"]}','images':[{'id':i['id'],'src':i['url'],'alt':i['altText']} for i in row['images']['nodes']],'collections':row['collections']['nodes'],'variants':[{'id':v['id'],'title':v['title'],'sku':v['sku'],'price':v['price'],'inventory_quantity':v.get('inventoryQuantity'),'available':v['availableForSale']} for v in row['variants']['nodes']]})
        if not connection['pageInfo']['hasNextPage']: break
        cursor=connection['pageInfo']['endCursor']
    else: raise ValidationError('Catalog exceeds 10,000 products; split a manual import. No partial sync was saved.')
    count=import_products(brand,rows,actor)
    store.last_sync_at=timezone.now(); store.save()
    audit(brand,actor,'shopify.synced',store,{'count':count})
    return count
