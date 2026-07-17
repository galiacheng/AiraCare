#!/usr/bin/env python
"""Provision the AiraCare Foundry IQ knowledge base (agentic retrieval over Azure AI Search).

Idempotent, REST-based (Search Service API ``2026-04-01`` GA). It:

  1. Creates a **blob knowledge source** over the ``knowledge`` container — Azure AI Search
     auto-generates the datasource, skillset (chunk + vectorize with ``text-embedding-3-small``),
     index, and indexer, then runs ingestion.
  2. Creates the **knowledge base** that references the knowledge source.
  3. Waits for the indexer to finish and prints the document count.
  4. Runs a retrieve smoke test.

Auth:
  * This script calls Search with the caller's AAD token (needs *Search Service Contributor* +
    *Search Index Data Contributor/Reader* on the service — run ``az login`` first).
  * The Search service's **system-assigned managed identity** reaches Blob Storage
    (*Storage Blob Data Reader*), so no storage key is embedded.
  * Embedding (ingestion-time) auth: by default the Search MI calls the model. On **AIServices**
    (multi-service) accounts the MI→OpenAI data-plane token can be rejected as ``DeploymentNotFound``;
    if that happens, set ``AIRACARE_EMBED_KEY`` (account key) and this script pins it on the
    embedding config so ingestion uses key auth. The key is read from the environment only — it is
    never written to source. Query-time (agent → Search) auth stays keyless via RBAC.

Environment variables (see the deploy notes in ``foundry-a2a-server/docs/production.md`` §8.5):
  AIRACARE_SEARCH_ENDPOINT       e.g. https://srch-airacare-kb.search.windows.net
  AIRACARE_SEARCH_KB             knowledge base name      (default: airacare-care-kb)
  AIRACARE_SEARCH_KS             knowledge source name    (default: airacare-guidelines-ks)
  AIRACARE_STORAGE_RESOURCE_ID   full ARM id of the storage account (for the MI connection string)
  AIRACARE_BLOB_CONTAINER        default: knowledge
  AIRACARE_EMBED_ENDPOINT        Azure OpenAI endpoint, e.g. https://cog-...openai.azure.com
  AIRACARE_EMBED_DEPLOYMENT      default: text-embedding-3-small
  AIRACARE_EMBED_KEY             optional; embedding account key for ingestion (see above)
"""

from __future__ import annotations

import json
import os
import sys
import time

import requests
from azure.identity import DefaultAzureCredential

API = "2026-04-01"
SCOPE = "https://search.azure.com/.default"


def _env(name: str, default: str | None = None) -> str:
    val = os.getenv(name, default)
    if not val:
        sys.exit(f"missing required env var: {name}")
    return val


def _token() -> str:
    return DefaultAzureCredential().get_token(SCOPE).token


def _req(method: str, url: str, token: str, body: dict | None = None) -> requests.Response:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    return requests.request(method, url, headers=headers, json=body, timeout=120)


def _put(url: str, token: str, body: dict, label: str) -> None:
    resp = _req("PUT", url, token, body)
    if resp.status_code not in (200, 201):
        print(f"--- {label} FAILED ({resp.status_code}) ---")
        print(resp.text)
        resp.raise_for_status()
    print(f"[ok] {label} ({resp.status_code})")


def main() -> None:
    endpoint = _env("AIRACARE_SEARCH_ENDPOINT").rstrip("/")
    kb_name = os.getenv("AIRACARE_SEARCH_KB", "airacare-care-kb")
    ks_name = os.getenv("AIRACARE_SEARCH_KS", "airacare-guidelines-ks")
    storage_id = _env("AIRACARE_STORAGE_RESOURCE_ID")
    container = os.getenv("AIRACARE_BLOB_CONTAINER", "knowledge")
    embed_endpoint = _env("AIRACARE_EMBED_ENDPOINT").rstrip("/")
    embed_deploy = os.getenv("AIRACARE_EMBED_DEPLOYMENT", "text-embedding-3-small")
    embed_key = os.getenv("AIRACARE_EMBED_KEY")  # optional key-auth fallback for ingestion

    token = _token()

    # 1. Blob knowledge source. connectionString uses the "ResourceId=" form so Search uses its
    #    own managed identity to read the container (no storage key). Image verbalization is off
    #    (text-only markdown), so no chat-completion model is needed.
    aoai_params = {
        "resourceUri": embed_endpoint,
        "deploymentId": embed_deploy,
        "modelName": embed_deploy,
    }
    if embed_key:
        # AIServices MI→OpenAI can 404 (DeploymentNotFound); pin the key for ingestion only.
        aoai_params["apiKey"] = embed_key
    ks_body = {
        "name": ks_name,
        "kind": "azureBlob",
        "description": "AiraCare dementia-care guideline corpus (non-PII).",
        "azureBlobParameters": {
            "connectionString": f"ResourceId={storage_id};",
            "containerName": container,
            "isADLSGen2": False,
            "ingestionParameters": {
                "disableImageVerbalization": True,
                "embeddingModel": {
                    "kind": "azureOpenAI",
                    "azureOpenAIParameters": aoai_params,
                },
            },
        },
    }
    _put(
        f"{endpoint}/knowledgesources/{ks_name}?api-version={API}",
        token,
        ks_body,
        f"knowledge source '{ks_name}'",
    )

    # 2. Knowledge base referencing the source.
    kb_body = {
        "name": kb_name,
        "description": "AiraCare care-guideline knowledge base for grounded caregiver advice.",
        "knowledgeSources": [{"name": ks_name}],
    }
    _put(
        f"{endpoint}/knowledgebases/{kb_name}?api-version={API}",
        token,
        kb_body,
        f"knowledge base '{kb_name}'",
    )

    # 3. Wait for the auto-generated indexer to finish ingesting.
    indexer = f"{ks_name}-indexer"
    print(f"[..] waiting for indexer '{indexer}' to finish ingestion")
    for _ in range(40):
        time.sleep(15)
        token = _token()  # refresh in case of long runs
        resp = _req("GET", f"{endpoint}/indexers/{indexer}/status?api-version={API}", token)
        if resp.status_code != 200:
            print(f"  (indexer status {resp.status_code}: {resp.text[:200]})")
            continue
        status = resp.json()
        last = status.get("lastResult") or {}
        state = last.get("status", status.get("status"))
        items = last.get("itemsProcessed", 0)
        errors = last.get("errors") or []
        print(f"  indexer: {state}, itemsProcessed={items}, errors={len(errors)}")
        if state == "success":
            break
        if state in ("transientFailure", "error"):
            if errors:
                print(json.dumps(errors[:3], indent=2))
            break

    # 4. Retrieve smoke test.
    print("[..] retrieve smoke test")
    token = _token()
    retrieve_body = {
        "intents": [{"type": "semantic", "search": "how to respond to nighttime wandering"}],
        "knowledgeSourceParams": [{"knowledgeSourceName": ks_name, "kind": "azureBlob"}],
    }
    resp = _req(
        "POST",
        f"{endpoint}/knowledgebases/{kb_name}/retrieve?api-version={API}",
        token,
        retrieve_body,
    )
    if resp.status_code != 200:
        print(f"--- retrieve FAILED ({resp.status_code}) ---")
        print(resp.text)
        resp.raise_for_status()
    print("[ok] retrieve returned:")
    print(json.dumps(resp.json(), indent=2)[:2500])


if __name__ == "__main__":
    main()
