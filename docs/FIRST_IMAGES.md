# Generate Infatuation's first three real daily images

These steps require real catalog images, authorized adult persona reference images and a funded/configured image provider. None are replaced by test fixtures.

1. Run setup, create a superuser and start web/worker/scheduler with the commands in README. Sign in, open Brands, and select Infatuation Apparel.
2. Import your real Shopify catalog from Products → Import JSON. Alternatively configure Brand settings → Shopify store: canonical `your-store.myshopify.com`, API version `2026-07`, and a variable name such as `SHOPIFY_INFATUATION_TOKEN`. Inject its Admin API token securely into the web process, then use Sync Shopify. Ensure the app has catalog and inventory read access. OAuth installation is not implemented; a store-authorized Admin API token is required for live sync.
3. Mark the desired products active and eligible. Each needs at least one valid HTTPS image. The seeded brand allows a product to appear up to three times in a batch; choose three products if you prefer no repeats and set the repeat limit to one.
4. Open AI characters → Nyla. Define her appearance/consistency from the reference material you have permission to use. Upload at least one **face** reference; add body/style references as appropriate. Mark Nyla approved and active. The seed contains no reference images and does not assert that text alone creates identity consistency.
5. Choose an image provider in Brand settings. Provider access must be enabled for the brand. Credentials are environment variable bindings, never values entered in the form.

### Option A: OpenAI Images

- Inject the credential securely as `DEFIANT_IMAGE_API_KEY` into the worker. Permit HTTPS access to `api.openai.com` and your real product-image CDN(s) in the cloud environment.
- Provider: `openai`; model: `gpt-image-1` (or an Images model your account supports); binding: `DEFIANT_IMAGE_API_KEY`; settings: `{"size":"1024x1536","quality":"medium"}`; Enabled checked. No endpoint is required.
- The worker submits identity/clothing reference bytes to Images edits. Character consistency and garment fidelity are model-dependent; seed/LoRA/ControlNet are not supported by this adapter.

### Option B: ComfyUI / RunPod pod

- Bring up your own ComfyUI pod with the required model, custom nodes and workflow. Configure its final HTTPS base URL and authentication binding in brand provider settings. Permit that endpoint in the cloud network policy. Private hosts require an explicit `COMFYUI_ALLOWED_HOSTS` entry in the worker.
- Export your actual workflow in **API format**. Store it in provider settings as `workflow`. Supply `inputs` mappings to the correct node/input keys. Example shape (node IDs must come from your workflow):

```json
{
  "workflow": {"...": "your API-format workflow, not this example"},
  "inputs": {
    "prompt": {"node": "6", "input": "text"},
    "negative_prompt": {"node": "7", "input": "text"},
    "seed": {"node": "3", "input": "seed"},
    "face": {"node": "20", "input": "image"},
    "body": {"node": "21", "input": "image"},
    "clothing": {"node": "22", "input": "image"},
    "lora": {"node": "24", "input": "lora_name"}
  }
}
```

- Each attached reference needs a mapping: first `face`, then `face_1`, `face_2`; first `clothing`, then `clothing_1`, etc. Body/style/ControlNet use their role names. Character `conditioning` keys map to correspondingly named provider `inputs`. Put no secrets in workflow/settings JSON. Only add LoRA/model IDs that exist remotely.
- This adapter targets the pod's ComfyUI HTTP API. It does not target the RunPod serverless API.

6. Check the brand's daily settings: three candidates, three or more active categories, distinct locations/poses, suitable cooldowns. The seed supplies 12 locations, six poses, 15 categories and three editable daily mix components. Review these before enabling generation. For your first manual batch, scheduling can remain disabled.
7. Click **Generate today's content** once. It creates exactly three candidate concepts and jobs: product-focused, lifestyle and aspirational. Clicking again returns the existing primary batch. An additional paid batch requires the explicit confirmation control. If prerequisites/rules cannot be satisfied, the batch fails atomically with an actionable message.
8. Leave the worker running. Open Review queue to see results or failures. Jobs return original assets, prompt/settings/reference snapshots and external IDs. Nothing becomes approved automatically. A failed job shows the diagnosis; fix configuration, inspect remote state and explicitly confirm a retry. Avoid resubmitting an ambiguously completed remote operation.
9. Inspect clothing/anatomy/identity and approve, reject or regenerate each result. Regeneration creates a new generation with parent lineage. Approval adds the image to Content calendar; use Plan date & time as needed.
10. From an approved generation, choose **Export Instagram · 1080 × 1350**. The derivative is proportionally padded, leaving the full-resolution original untouched. Mark READY_TO_POST only after approval. Download and publish manually.
11. For daily automation, enable the brand's generation schedule and choose the local preferred time. Keep both scheduler and worker supervised/running. The scheduler and manual action share the same primary daily-batch key; no automatic social posting exists.

## What is still needed for real images

- The real Infatuation Shopify catalog/store domain and authorized catalog access (or complete manual JSON export).
- Authorized Nyla face/body/style reference images and appearance/approval decisions.
- A funded OpenAI Images credential, or a running ComfyUI/RunPod endpoint with installed model/workflow and any required authentication.
- Cloud network permission for the chosen provider endpoint and real product-image hosts.

A local passing test with a mocked provider does not establish that an account/model is available or that image fidelity meets brand standards. Live generation and live Shopify sync remain unverified until these inputs are provided.
