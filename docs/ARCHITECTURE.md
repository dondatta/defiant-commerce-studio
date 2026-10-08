# Standalone boundaries

This project has no CMM imports, shared database, runtime dependency or asset dependencies. The only available existing checkout was cd-remotion, which contains the promo video rather than an AI Studio. No CMM files were modified.

Django 5.2 is the web/API/authentication boundary. Its server-rendered interface uses session authentication, CSRF-protected mutations and role-aware navigation. A Brand plus Membership defines workspace access. Platform superusers can manage all brands; brand ADMIN can configure their own brand, EDITOR creates content, REVIEWER reviews/exports, VIEWER reads. All routes resolve authorized brands before accessing IDs, including asset downloads. The Django admin is platform-superuser-only.

The service layer composes prompts, plans batches, enqueues immutable generation requests, appends review decisions, and regenerates into separate concepts/generations. Frontend filters do not provide tenant security. Model validation and SQLite/PostgreSQL triggers reject cross-brand foreign keys and moving records between brands. Through tables for product preferences/collections carry their own brand relationships. SQL triggers also reject updates/deletes to generation requests, results, references and review/audit history. Assets retain immutable storage metadata; approval flags can change. Resolved product-reference bytes are saved in private storage before submission, preserving provider inputs if a Shopify image changes later.

The database is standalone SQLite for single-worker development, PostgreSQL for production/concurrent workers. Migrations include unique external IDs per brand, unique daily batch slots, one job/result/calendar entry per generation, and a queue index. Core relational objects are normalized. JSON is used only for provider configuration, reference conditioning, output metadata and audit details.

## Models

Brand, Membership, SocialHandle, BrandSettings; ShopifyStore, Product, Variant, ProductImage, Collection and explicit ProductCollection/ProductCharacter/ProductCategory relationships; Character and CharacterReference; ContentCategory, PromptComponent, PromptTemplate; ContentConcept, DailyBatch; ProviderConfig, Generation, GenerationReference, ResolvedReference, GenerationJob, GenerationResult; Asset; ReviewDecision, CalendarEntry, PerformanceData; AuditEvent.

Generations snapshot prompt, negative prompt, product/character IDs, provider/model/configuration, requested seed, parent, timestamp, and references. Results append external ID, dimensions via Asset, original image, duration, provider metadata and optional provider-reported cost. Job state handles PLANNED/GENERATING/GENERATED/FAILED. Completed unreviewed outputs are NEEDS_REVIEW. Append-only reviews yield APPROVED/REJECTED/REGENERATE/READY_TO_POST. POSTED fields exist on calendar/performance foundations, but no publishing service is active.

## Worker and scheduler

Web requests enqueue; a separate `worker` process claims jobs using conditional updates and PostgreSQL row locks with skip_locked. SQLite requires one worker and one scheduler. Successful work writes the original plus a single result transactionally and requires review. HTTP 429 rejection responses retry with exponential delay up to three attempts; authentication/configuration/ambiguous connection failures become FAILED. Stale 30-minute leases require manual inspection. Manual retry requires explicit acknowledgement of potential remote charges. ComfyUI prompt IDs are recorded in the audit trail and reused on retries after a known submission. A crash between remote acceptance and recording its ID remains an unavoidable ambiguity without provider-side idempotency: inspect remote state before retrying.

The scheduler evaluates each enabled brand's IANA timezone and preferred local time every 30 seconds. `(brand, date, slot=0)` is the scheduled/manual primary batch key. Manual content reuses today's batch; an explicitly confirmed additional batch receives another slot. Batch creation, concepts and jobs share one transaction. Scheduling failures are visible in the audit log and do not stop unrelated tenants.

Planner rules require exactly the configured count, distinct categories/locations/poses, eligible products, approved characters with face references, configured product repeat limits, product-specific preferences and character/location plus similar-concept cooldowns. Recent usage ranks less-used choices first. This is a deterministic rules planner, not visual similarity scoring or machine learning. Strict or conflicting preferences may leave no plan; the user must add eligible choices or adjust rules rather than accept silent rule violations. Daily mix directions are editable brand PromptComponents.

## Provider boundary

`providers.generate_image(generation, config)` returns original bytes, external ID and metadata. OpenAI uses Images edits with actual identity/clothing reference files (rather than character names alone). `gpt-image-1` defaults to 1024×1536 originals; exact 4:5 output is made as a separate 1080×1350 derivative. OpenAI does not expose seed/LoRA/IPAdapter/ControlNet controls through this adapter; requested seeds/conditioning are recorded but only supported ComfyUI workflows apply them. Identity/clothing fidelity remains a model limitation requiring human review.

ComfyUI/RunPod uses an API-format workflow, upload/image, prompt, history and view endpoints. Input mappings inject text, negative prompts, seeds, LoRA filenames, conditioning settings and every uploaded face/body/style/clothing/ControlNet reference. Models and custom nodes must already be installed remotely. RunPod support is the ComfyUI pod HTTP API, not RunPod serverless job APIs. Additional providers can implement the same interface.

## Storage and commerce

Storage supports private local files and private S3 objects via the SDK authentication chain. Keys are brand-prefixed. All downloads pass authenticated brand authorization; no public media serving route exists. Generated originals are retained. Export pads proportionally to 1080×1350 instead of cropping a garment; no logo/watermark is added. Brand-specific watermark customization is not implemented. Files created before a failed transaction can remain unreferenced; retention/orphan maintenance and backup operations are deployment work.

Shopify JSON imports upsert by brand/external IDs, including variants, images and collection relationships, preserving creative eligibility and notes. Live GraphQL sync uses per-brand canonical myshopify.com domain and token binding, with pagination for products. It refuses catalogs with products exceeding 100 nested variants/images/collections or 10,000 products rather than silently saving partial data. Manual complete imports can handle these cases. Shopify OAuth app installation, token exchange/rotation, webhooks and scheduled catalog sync remain future integration work; the per-brand integration schema can store the resulting credential binding without replacing the catalog schema. Import/sync records do not delete products merely absent from the payload.

## Production boundary

This is a working local milestone, not a production deployment. PostgreSQL and S3 adapters are implemented but not exercised against real infrastructure. Deployment requires a production WSGI server/reverse proxy, TLS, private bucket IAM, secret provisioning, backup/monitoring, migrations, process supervision, rate limits and storage retention. Password reset/invitation email, OAuth onboarding and social publishing are not implemented. No production resources were created and no real generation charges were incurred during verification.
