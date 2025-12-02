# apps/api/services/dbpedia_service.py
import os
import json
import hashlib
import time
from urllib.parse import quote
import asyncio
import httpx

BASE_DIR = os.path.dirname(__file__)
CACHE_DIR = os.path.normpath(os.path.join(BASE_DIR, "../../cache/dbpedia"))
os.makedirs(CACHE_DIR, exist_ok=True)

class DBPediaService:
    def __init__(self, endpoint="https://dbpedia.org/sparql", cache_ttl=60*60*24*30, timeout=8.0):
        self.endpoint = os.getenv("DBPEDIA_ENDPOINT", endpoint)
        self.cache_ttl = int(os.getenv("DBPEDIA_CACHE_TTL", cache_ttl))
        self.timeout = float(os.getenv("DBPEDIA_TIMEOUT", timeout))
        self._client = httpx.AsyncClient(timeout=self.timeout)
        self._cache_lock = asyncio.Lock()

    def _cache_path(self, key: str):
        h = hashlib.sha1(key.encode()).hexdigest()
        return os.path.join(CACHE_DIR, f"{h}.json")

    async def _read_cache(self, key: str):
        path = self._cache_path(key)
        if not os.path.exists(path):
            return None
        try:
            # read without locking (read-mostly). If stale we return None.
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if time.time() - data.get("_fetched_at", 0) > self.cache_ttl:
                return None
            return data.get("payload")
        except Exception:
            return None

    async def _write_cache(self, key: str, payload):
        path = self._cache_path(key)
        try:
            async with self._cache_lock:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump({"_fetched_at": time.time(), "payload": payload}, f, ensure_ascii=False)
        except Exception:
            pass

    async def lookup_abstract(self, condition_name: str):
        """
        Async lookup. Returns dict: {"matched": bool, "resource": str?, "abstract": str?, "labels": [..]}
        """
        if not condition_name:
            return {"matched": False}
        key = f"abstract:{condition_name.strip().lower()}"
        cached = await self._read_cache(key)
        if cached is not None:
            return cached

        # try direct resource
        resource = "http://dbpedia.org/resource/" + quote(condition_name.replace(" ", "_"))
        query = f"""
        PREFIX dbo: <http://dbpedia.org/ontology/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?abstract ?label WHERE {{
          <{resource}> dbo:abstract ?abstract .
          OPTIONAL {{ <{resource}> rdfs:label ?label . FILTER (lang(?label) = 'en') }}
          FILTER (lang(?abstract) = 'en')
        }} LIMIT 1
        """
        resp = await self._sparql(query)
        if resp:
            bindings = resp.get("results", {}).get("bindings", [])
            if bindings:
                b = bindings[0]
                abstract = b.get("abstract", {}).get("value", "")
                label = b.get("label", {}).get("value", condition_name)
                result = {"matched": True, "resource": resource, "abstract": abstract, "labels": [label]}
                await self._write_cache(key, result)
                return result

        # fallback: search by label (less strict)
        safe_label = condition_name.replace('"', '')
        search_query = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX dbo: <http://dbpedia.org/ontology/>
        SELECT ?s ?abstract ?label WHERE {{
          ?s rdfs:label ?label .
          OPTIONAL {{ ?s dbo:abstract ?abstract . FILTER (lang(?abstract) = 'en') }}
          FILTER (lang(?label) = 'en' && (lcase(str(?label)) = "{safe_label.lower()}" || contains(lcase(str(?label)), "{safe_label.lower()}")))
        }} LIMIT 3
        """
        resp2 = await self._sparql(search_query)
        if resp2:
            bindings = resp2.get("results", {}).get("bindings", [])
            if bindings:
                b = bindings[0]
                s = b.get("s", {}).get("value")
                abstract = b.get("abstract", {}).get("value", "")
                label = b.get("label", {}).get("value", condition_name)
                result = {"matched": True, "resource": s, "abstract": abstract, "labels": [label]}
                await self._write_cache(key, result)
                return result

        result = {"matched": False}
        await self._write_cache(key, result)
        return result

    async def _sparql(self, query: str):
        try:
            url = self.endpoint + "?query=" + quote(query)
            headers = {"Accept": "application/sparql-results+json"}
            r = await self._client.get(url, headers=headers)
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    async def close(self):
        try:
            await self._client.aclose()
        except Exception:
            pass
